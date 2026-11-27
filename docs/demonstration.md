# Demonstrate the stack

This guide starts the stack on a laptop and shows each behavior of the released stack in the order a presenter follows on a fresh stack: the HTTP flows, scaling, Broker dispatch and delivery, monitoring, load routing, the warehouse, database failover, the sharded cache, and the end-shift saga. Every step uses plain `docker` and `docker compose` commands, `curl`, and the scripts in `scripts/`. Each section from [Load the warehouse](#load-the-warehouse) on also names the code that implements the behavior.

The diagram in [architecture](architecture.md) shows the replicated topology.

Run every command from the repository root. Compose names the project `student-id-please`, so the containers are `student-id-please-<service>-<n>` and the network is `student-id-please_default`. If `.env` sets `COMPOSE_PROJECT_NAME`, replace `student-id-please` with that name in the commands that name a container or the network.

## Start the stack

1. Generate the ignored `.env` and `.local/stack/` files. The command refuses to overwrite existing configuration and prints no credentials:

	```sh
	python3 scripts/setup.py
	```

2. To receive Discord alerts, set `DISCOVERY_DISCORD_WEBHOOK_URL` in `.env`. Leave it empty to send none.
3. Start the stack and wait until every container is healthy:

	```sh
	docker compose up -d --wait
	```

	The command returns when every container is running and every container with a health check reports healthy. Each domain service starts two replicas. A stack from a release before the replicated databases needs new volumes, as [existing volumes](contracts/replication.md#existing-volumes) explains.

4. Seed the University Record catalog once. Without it, starting a session returns `409 DEPENDENCY_REJECTED`:

	```sh
	python3 scripts/seed_university_catalog.py
	```

	On a fresh stack the script prints `University catalog: 69 created, 0 already present, 0 failed (of 69)`. Later runs print `0 created, 69 already present`.

5. Create the read-only roles that the ETL uses. Until you do, each ETL run reports every source as `failed` with `unauthorized`:

	```sh
	python3 scripts/warehouse_roles.py
	```

	The script prints one `ok` line for each of the seven databases. Running it again is safe.

To stop the stack and keep its data, run `docker compose down`. Never add `--volumes` to a stack you want to keep.

## Run the HTTP checks

The Postman collections run through the public Gateway. The [guided demo](../postman/GUIDED-DEMO.md) walks through registration, a shift, overload, and the administrator routes, in Postman or with Newman. It ends by finding the shift's saga `completed` in the saga listing, with player 2 as a temporary administrator. Run it first on a fresh stack, so that the later sections have a played shift, cached values, and warehouse rows:

```sh
./scripts/run_newman.sh
./scripts/run_newman.sh --with-overload
```

The first command ends with `85 requests; 261/261 assertions passed; 0 failures`. Without `--with-overload`, it skips requests 28 and 29. [HTTP checks](../postman/HTTP-CHECKS.md) describes the read-only public folder and the private Discovery health folder.

Each service has its own collection in `postman/`: `applicant`, `credential`, `discord-dms`, `moderation`, `server-rules`, and `university-record`. The runner creates what a collection needs through the public Gateway, then runs it with the same redaction and report:

```sh
./scripts/run_newman.sh --service applicant
```

The runner registers disposable players, builds a team and a Session with an assigned Moderator, starts the shift and opens a case where the collection needs one, and grants a disposable player administrator access for the run. It revokes that access when the run ends, as the [catalog seed](../scripts/seed_university_catalog.py) does. The grant runs `docker compose exec player` in the repository root. Pass `--compose-dir DIR` when the stack runs from another directory. `server-rules` needs a published rule version, and `moderation` opens a second case for its ban folder. The report goes to `.local/postman/<service>/newman-htmlextra.html`. To see which services handle a request, follow its `X-Request-ID` in the Broker log as [the guided demo](../postman/GUIDED-DEMO.md#follow-a-request-through-the-services) describes.

## Get an administrator token

The Broker listings need a global administrator. The catalog seed stores a disposable player in `.local/stack/seed-admin.json`. Grant it administrator access, then log in and keep its access token in `ADMIN_TOKEN`. The password goes through a pipe, so it never appears in the command line or the output:

```sh
docker compose exec player python -m app.admin "$(python3 -c 'import json; print(json.load(open(".local/stack/seed-admin.json"))["player_id"])')" --grant
export ADMIN_TOKEN="$(python3 -c 'import json; c = json.load(open(".local/stack/seed-admin.json")); print(json.dumps({"email": c["email"], "password": c["password"]}))' \
	| curl -fsS -H 'Content-Type: application/json' -H "Idempotency-Key: $(python3 -c 'import uuid; print(uuid.uuid4())')" -d @- http://127.0.0.1:8080/api/v1/auth/login \
	| python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')"
```

The grant prints `Account authority updated. Log in again to obtain a token with the current claim.` The token is valid for 15 minutes. Log in again after that. `scripts/seed_university_catalog.py` and `scripts/check_sagas.py` grant and revoke the same player, so grant it again after you run either one. The later sections also use this token where they need any player's token. To revoke the access when you finish, run the grant command with `--revoke`.

## Scale a service

The domain services are `player`, `session`, `applicant`, `credential`, `university-record`, `server-rules`, `moderation`, and `discord-dms`. Each one scales with `--scale`. A new container generates its own instance ID, registers its own container address with Discovery, and receives traffic after its first ready probe. The [resilience contract](contracts/resilience.md) defines this identity.

1. Raise Applicant to four replicas. `--no-deps` leaves the other services untouched:

	```sh
	docker compose up -d --no-deps --scale applicant=4 applicant
	```

2. List the Applicant containers and their health:

	```sh
	docker compose ps applicant
	```

3. In a second terminal, follow the Message Broker, Discovery, and Applicant:

	```sh
	docker compose logs -f --tail 50 --timestamps message-broker discovery applicant
	```

	Discovery logs each new registration. The Broker's `dispatch` records name the `target_instance_id`, so you can see requests spread across the four replicas. To follow one replica, pass its index, for example `docker compose logs -f --index 2 applicant`.

4. Stop one replica. Copy a container ID from the `docker compose ps applicant` output, then run:

	```sh
	docker stop <container-id>
	```

	The replica removes its own instance with reason `shutdown` before its listener closes. Discovery stops routing to it at once, and the instance never needs reactivation. A container that dies without a graceful stop leaves routing when its lease expires.

5. Return Applicant to two replicas:

	```sh
	docker compose up -d --no-deps --scale applicant=2 applicant
	```

	Compose removes the extra containers. Each one deregisters on its way out.

The same commands work for every domain service listed above. Gateway, the Message Broker, `broker-db`, Discovery, the Moderation outbox publisher, etcd, `redis`, `warehouse-db`, and the ETL run as one instance each. The database nodes and the cache nodes are declared services, such as `player-db-1` and `cache-1`, because each one needs its own volume or its own place on the cache ring. They do not scale with `--scale`.

## Watch Broker dispatch

Gateway sends each public request to the Message Broker over REST with its target service. Client requests stay REST end to end. Domain services send every peer call to the Broker as a typed gRPC call on port `50051`. The Broker selects the ready replica with the lowest load, alternating between replicas with equal load, and writes one `INFO` `dispatch` record for each attempt. The [load routing contract](contracts/routing.md) defines selection and rerouting. After a shift has started, list the dispatch records:

```sh
docker compose logs --no-log-prefix message-broker | grep '"event":"dispatch"'
```

Each record names the `caller`, the `target_service`, the selected `target_instance_id` and `registration_id`, the `route`, the `status`, and the `outcome`. For a peer call, `route` is the full RPC method name, such as `/student_id.session.v1.SessionService/GetSessionContext`, and the record also has the gRPC `code`. `caller` is `gateway` for public traffic and the service name, such as `session` or `moderation`, for a peer call. A peer call keeps the `request_id` of the public request that caused it.

Gateway's control listener on `:8083` answers only `/healthz`. It returns `404 NOT_FOUND` for every other path. Status and log export use each process's gRPC `ControlService`.

## Watch request threads

Each admitted Broker request runs on its own operating-system thread, which ends with the request. Overlapping requests therefore show different `thread_id` values, and a finished request's ID does not serve another request:

```sh
docker compose logs --no-log-prefix message-broker | grep '"event":"dispatch"' | grep -o '"thread_id":[0-9]*' | sort | uniq -c | sort -rn | head
```

The `threads` object in the topic listing below reports the active request threads and the bound.

## List topics

An administrator lists the topics, their producers and subscribers, the ready instances per subscriber, delivery counts by state, and the depth of each targeted queue:

```sh
curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8080/api/v1/admin/broker/topics
```

Stop every replica of a subscriber with `docker compose stop credential` and list again. Its `ready_instances` drops to 0 while `subscribed` stays `true`, and new deliveries to it stay `pending` until `docker compose start credential`.

## Watch topic delivery

Producers publish each domain event to the Broker by topic. The Broker stores the event in `broker-db` with one delivery per subscribing service and pushes each delivery to one ready replica of that service. Each replica declares its topics when it registers, and the Broker derives the subscriptions from them. After the stack is healthy, list the subscriptions:

```sh
docker compose exec broker-db psql -U broker -c 'select * from subscriptions'
```

A healthy stack lists every allowed pair from the [topics table](contracts/queues.md#topics). `CaseInitialized` has three rows: `applicant`, `credential`, and `university_record`.

After a shift has started and one decision is made, list the delivery attempts:

```sh
docker compose logs --no-log-prefix message-broker | grep '"event":"delivery"'
```

Each record names the `event_type`, `event_id`, `target_service`, the selected `target_instance_id`, the `attempt`, the `status`, and the `outcome`: `delivered`, `retry`, or `dead_lettered`. One `CaseInitialized` shows one delivered record for each of its three subscribers, each on one replica.

Count the deliveries per topic, subscriber, and state:

```sh
docker compose exec broker-db psql -U broker -c 'select e.topic, d.subscriber, d.state, count(*) from deliveries d join events e using (event_id) group by 1, 2, 3 order by 1, 2, 3'
```

`done` counts the deliveries the subscriber accepted. `pending` and `in_flight` rows wait for a ready replica or their next attempt, and `dead_lettered` rows moved to the dead-letter table.

## Inspect dead letters

The Broker gives each delivery at most `BROKER_DELIVERY_MAX_ATTEMPTS` attempts, 5 by default, waiting 1, 5, then 30 seconds between them. A delivery that the consumer rejects with 409 or 422, or that fails every attempt, moves to the `dead_letters` table in `broker-db`. The [dead-letter contract](contracts/dead-letters.md) defines the rules. An administrator lists the newest dead letters:

```sh
curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" 'http://127.0.0.1:8080/api/v1/admin/broker/dead-letters?limit=20'
```

Each item names the event, topic, producer, subscriber, `reason`, attempts, and last status, and never the payload. Pass `next_cursor` as `cursor` for the next page, and filter with `topic` or `subscriber`.

Publish an event that the consumer rejects. Export Moderation's service token, then publish a `DecisionScored` event whose `score_delta` breaks the scoring rule:

```sh
export SERVICE_TOKEN="$(sed -n "s/^MODERATION_SERVICE_TOKEN='\(.*\)'$/\1/p" .env)"
docker run --rm --network student-id-please_default -e SERVICE_TOKEN -v "$PWD/proto:/proto:ro,z" fullstorydev/grpcurl:v1.9.1 \
	-plaintext -import-path /proto -proto student_id/broker/v1/broker.proto \
	-expand-headers -H 'x-service-name: moderation' -H 'x-service-token: ${SERVICE_TOKEN}' \
	-d "$(python3 -c 'import json, uuid, datetime; c = str(uuid.uuid4()); print(json.dumps({"topic": "DecisionScored", "event": {"event_id": str(uuid.uuid4()), "event_type": "DecisionScored", "schema_version": 1, "occurred_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "producer": "moderation", "correlation_id": c, "payload_json": json.dumps({"decision_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "case_id": c, "moderator_id": str(uuid.uuid4()), "action": "accept", "correct": True, "score_delta": 3, "penalty": 0})}}))')" \
	message-broker:50051 student_id.broker.v1.BrokerService/PublishEvent
```

Session answers with 422, and the listing shows the delivery with reason `rejected` after one attempt. Other topics keep delivering.

Make one consumer fail on every attempt while it stays ready. Without permission to insert into its ledger, Player answers each delivery with a retryable 500. An unavailable or read-only database would make Player unready instead, and the delivery would wait:

```sh
docker compose exec player-db-1 sh -c 'PGPASSWORD=$APP_PASSWORD psql "host=player-db-1,player-db-2,player-db-3 user=$APP_USER dbname=$APP_DB target_session_attrs=read-write" -c "REVOKE INSERT ON progression_ledger FROM player"'
```

Apply a disciplinary action as the global administrator with `POST /api/v1/disciplinary-actions`. After five attempts, about a minute, the `DisciplinaryActionApplied` delivery to Player appears in the listing with reason `exhausted`. Restore the permission before you continue, because the end-shift saga also inserts into the ledger:

```sh
docker compose exec player-db-1 sh -c 'PGPASSWORD=$APP_PASSWORD psql "host=player-db-1,player-db-2,player-db-3 user=$APP_USER dbname=$APP_DB target_session_attrs=read-write" -c "GRANT INSERT ON progression_ledger TO player"'
```

Accepted events survive a Broker restart. Stop Credential, start a case, restart the Broker and its database, then start Credential again:

```sh
docker compose stop credential
docker compose restart broker-db message-broker
docker compose start credential
```

The `CaseInitialized` delivery to Credential waits as `pending` with no attempts, and it is delivered once after Credential is ready.

## Call a service over gRPC

Every process serves plaintext gRPC on port `50051` of the Compose network, with no host port and no reflection. Use `grpcurl` with the checked-in protos. It runs in a one-off container on the Compose network, `student-id-please_default`. Export the operator control token from `.env` first, so the value never appears in the command line or the output:

```sh
export CONTROL_TOKEN="$(sed -n "s/^OPERATOR_CONTROL_TOKEN='\(.*\)'$/\1/p" .env)"
```

Read the status of one Applicant replica with `ControlService.GetStatus`. Compose names the replicas `student-id-please-applicant-1`, `student-id-please-applicant-2`, and so on:

```sh
docker run --rm --network student-id-please_default -e CONTROL_TOKEN -v "$PWD/proto:/proto:ro,z" fullstorydev/grpcurl:v1.9.1 \
	-plaintext -import-path /proto -proto student_id/control/v1/control.proto \
	-expand-headers -H 'x-control-name: operator' -H 'x-control-token: ${CONTROL_TOKEN}' \
	student-id-please-applicant-1:50051 student_id.control.v1.ControlService/GetStatus
```

The response names the `service_name`, `instance_id`, `boot_id`, readiness, and `load`. A wrong token returns `Unauthenticated`. List the ready instances that Discovery knows, with their `grpc_url`:

```sh
docker run --rm --network student-id-please_default -e CONTROL_TOKEN -v "$PWD/proto:/proto:ro,z" fullstorydev/grpcurl:v1.9.1 \
	-plaintext -import-path /proto -proto student_id/discovery/v1/discovery.proto \
	-expand-headers -H 'x-control-name: operator' -H 'x-control-token: ${CONTROL_TOKEN}' \
	-d '{"service_name": "applicant"}' \
	discovery:50051 student_id.discovery.v1.DiscoveryService/ListInstances
```

Business RPCs accept only the Broker's hop credential and a signed assertion, so `grpcurl` cannot call them directly. Watch them in the Broker's `dispatch` records instead.

## Scale Discord DMs

Clients open chat on the DMs proxy, `dms-proxy`, which publishes `127.0.0.1:${DMS_PORT:-8009}`. Gateway returns that one URL from every negotiation. The proxy is Caddy. It resolves the `discord-dms` replicas through Compose DNS every 5 seconds and sends each new WebSocket to the replica with the fewest connections. Chat connections are balanced by the DMs proxy because Lab 2 requires chat to bypass Gateway and the Broker, while service-to-service balancing stays in the Broker.

Raise DMs to three replicas:

```sh
docker compose up -d --no-deps --scale discord-dms=3 discord-dms
docker compose ps discord-dms
```

The replicas share the ticket secret, PostgreSQL history, and Redis delivery, so players connected to different replicas exchange messages. A new replica receives new connections after the next DNS refresh. Stopping a replica closes its connections. A client reconnects by negotiating a new ticket through Gateway, and the proxy sends the new connection to a remaining replica. Return to two replicas with `docker compose up -d --no-deps --scale discord-dms=2 discord-dms`.

## Monitor the stack

Prometheus and Grafana start with the stack and publish only to `127.0.0.1`. Every process serves `/metrics` on the private port `9464` of the container network. Prometheus reads its targets from Discovery every 5 seconds, so a scaled replica appears after it registers. The [metrics contract](contracts/metrics.md) defines the catalogue.

1. Open Grafana at `http://127.0.0.1:3000` and sign in as `admin`. The password is `GRAFANA_ADMIN_PASSWORD` in `.env`. Read it without printing the other secrets:

	```sh
	grep '^GRAFANA_ADMIN_PASSWORD=' .env
	```

2. Open the `Student ID services` dashboard. It shows request rate, 5xx ratio, 4xx rate, p50 and p95 latency, load by replica, ready and unavailable instances, dependency failures, scrape health, and the version of each replica. Open `Student ID broker` for the Broker's view: dispatch rate and load per replica, in-flight attempts, failures, reroutes, breaker trips, targeted queue depth, delivery outcomes, pending deliveries, and dead letters. The `service` variable filters both dashboards.

3. Check that Prometheus scrapes every replica. Every series has the `up` value 1:

	```sh
	curl -s 'http://127.0.0.1:9090/api/v1/query?query=up'
	```

4. Query a metric directly, for example the Broker's dispatch rate for each replica of Player:

	```sh
	curl -s --get 'http://127.0.0.1:9090/api/v1/query' \
		--data-urlencode 'query=sum by (target_instance) (rate(student_id_broker_dispatch_total{target_service="player"}[1m]))'
	```

The metrics port is not published, and Gateway and the DMs proxy return no exposition. Discovery's target list needs the `prometheus` credential, so a request without the headers fails with `401`.

### Follow a request in the logs

Promtail ships the structured records of every service to Loki, and Grafana shows them next to the metrics. Open the `Student ID logs` dashboard to filter by `service`, `level`, and free text. It shows the log rate for each service and level above the matching lines.

To follow one request across services, send a request with a known ID and search for it in Grafana Explore with the `Loki` data source:

```sh
curl -s -o /dev/null -H 'X-Request-ID: 7d6f1c52-3a0e-4c0b-9f43-0b6e5f1d2a10' http://127.0.0.1:8080/api/v1/players/me
```

```text
{service=~".+"} |= "7d6f1c52-3a0e-4c0b-9f43-0b6e5f1d2a10" | json
```

This request has no token, so only Gateway records it. With a valid bearer token, the result also lists the Broker and domain service records with the same `request_id`, ordered by time. Each line carries `event`, `instance_id`, `outcome`, and `duration_ms`. Add `| level="WARN"` or `| event="dispatch"` to narrow the result. Only `service` and `level` are labels, so filter other fields after `| json`.

## Watch load routing and rerouting

The Broker sends each request to the replica with the lowest load and reroutes an eligible request after a failed attempt. The [load routing contract](contracts/routing.md) defines the rules. These steps use native Docker commands on a running stack.

1. Make sure Player has two replicas, then send sequential requests as a player. `TOKEN` holds a player access token, such as the token from [Get an administrator token](#get-an-administrator-token):

	```sh
	docker compose up -d --no-deps --scale player=2 player
	for i in $(seq 20); do curl -s -o /dev/null -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/v1/players/me; done
	docker compose logs --no-log-prefix message-broker | grep '"event":"dispatch"' | grep -o '"target_instance_id":"[^"]*"' | sort | uniq -c
	```

	Equal loads alternate, so each replica receives about half of the dispatches.

2. Load one replica unevenly. Start a third Player replica with a smaller admission limit, send 64 concurrent requests, and compare the shares:

	```sh
	docker compose run -d --no-deps -e MAX_CONCURRENT_TASKS=4 player
	seq 64 | xargs -P 64 -I{} curl -s -o /dev/null -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/v1/players/me
	```

	The small replica receives fewer dispatches. In Grafana, `Student ID broker` shows the dispatch rates diverge while the load of each replica converges. Stop the extra container with `docker stop` and `docker rm` when you finish.

3. Pause one replica. Copy a Player container ID from `docker compose ps player`:

	```sh
	docker pause <container-id>
	seq 10 | xargs -P 10 -I{} curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/v1/players/me
	```

	Every request returns `200`. Each request that chose the paused replica logged a `timeout` dispatch, then a `reroute` with `decision` `sent`, then a second dispatch on the other replica with the same `request_id`:

	```sh
	docker compose logs --no-log-prefix message-broker | grep -E '"event":"(dispatch|reroute)"' | tail -40
	docker compose logs --no-log-prefix message-broker | grep '"event":"reroute"' | grep -o '"decision":"[a-z_]*"' | sort | uniq -c
	```

4. Unpause the replica. Three timeouts within the breaker window trip its breaker, and Discovery records the removal. Reactivate the replica by the [re-entry rules](contracts/resilience.md#removal-re-entry-and-writes):

	```sh
	docker unpause <container-id>
	```

	The broker dashboard shows the reroutes by decision, the breaker trip, and the extra `removed` instance.

## Load the warehouse

The ETL service copies analytics data from the eight domain services into `warehouse-db`, as the [warehouse contract](contracts/warehouse.md) defines. It runs every `ETL_INTERVAL`, five minutes by default, and connects to each datastore as `warehouse_reader`.

1. After the guided demo has played a shift, run one load:

	```sh
	docker compose run --rm etl --once
	```

	Each `etl_source` record reports one service with `outcome` `ok`, and one `etl_run` record closes the run. The command exits with status 0 when all eight load, and with status 3 when the interval run holds the lock. Run it again to see `rows_written` at 0 for every source.

2. Query the facts. Each ended shift has one row with its duration, its processed cases, its score, and its decisions:

	```sh
	docker compose exec warehouse-db psql -U warehouse -c "
		SELECT s.session_id, s.duration_seconds, f.processed_count, f.score, count(d.decision_id) AS decisions,
			count(*) FILTER (WHERE d.correct) AS correct
		FROM warehouse.fact_shift_score f JOIN warehouse.dim_shift s USING (session_id)
		LEFT JOIN warehouse.fact_decision d USING (session_id) GROUP BY 1, 2, 3, 4"
	```

3. Read the history of runs. The newest eight rows are the last run, one for each source:

	```sh
	docker compose exec warehouse-db psql -U warehouse -c "
		SELECT source, outcome, rows_read, rows_written, error_kind, finished_at
		FROM warehouse.etl_runs ORDER BY finished_at DESC LIMIT 8"
	```

4. Stop one source and run a load. That source reports `failed` with `unavailable`, the other seven load, and the command exits with status 1. Start the source again:

	```sh
	docker compose stop dms-db-1 dms-db-2 dms-db-3
	docker compose run --rm etl --once
	docker compose start dms-db-1 dms-db-2 dms-db-3
	```

	The three nodes elect a leader within about 30 seconds. `docker compose ps dms-db-1 dms-db-2 dms-db-3` then shows them healthy.

5. Show that the reader role cannot read a hidden column. The first command fails with `permission denied for table players`. The second reads a listed column and prints the player count:

	```sh
	docker compose exec player-db-1 psql -h /tmp -U postgres -d player_db -c 'SET ROLE warehouse_reader' -c 'SELECT password_hash FROM players'
	docker compose exec player-db-1 psql -h /tmp -U postgres -d player_db -c 'SET ROLE warehouse_reader' -c 'SELECT count(*) FROM players'
	```

6. Show the same rule in MongoDB, which has no field grants. The reader can count the documents of the `warehouse_applicant_cases` view, and reading the `applicant_cases` collection fails with `MongoServerError: not authorized on applicant to execute command { find: "applicant_cases" ...`. Export the reader password from `.env` first, so it never appears in the command line:

	```sh
	export WAREHOUSE_READER_PASSWORD="$(sed -n "s/^WAREHOUSE_READER_PASSWORD='\(.*\)'$/\1/p" .env)"
	docker compose exec -e WAREHOUSE_READER_PASSWORD mongodb-1 sh -c 'mongosh --quiet -u warehouse_reader -p "$WAREHOUSE_READER_PASSWORD" --authenticationDatabase applicant applicant --eval "print(db.warehouse_applicant_cases.countDocuments()); db.applicant_cases.findOne()"'
	```

These files implement the load:

- CPR: the `warehouse-db` and `etl` services in [`compose.yaml`](../compose.yaml), and [`scripts/warehouse_roles.py`](../scripts/warehouse_roles.py), which creates the `warehouse_reader` role, its column grants, and the MongoDB views.
- `ChillGuysStudio/etl-service`: `cmd/etl/main.go` reads the configuration and runs once or on the interval. `internal/pipeline/pipeline.go` runs each source and keeps the append cursors. `internal/pgsource/pgsource.go` and `internal/mongosource/mongosource.go` extract and transform the sources. `internal/warehouse/warehouse.go` and `internal/warehouse/tables.go` hold the schema migrations, the run lock, and the idempotent upserts.

## Fail over a database

Player, Session, Moderation, Discord DMs, and Server Rules each have three PostgreSQL nodes under Patroni, with one shared etcd. Applicant and Credential share a MongoDB replica set with three members, and University Record has its own. The [replication contract](contracts/replication.md) defines the topology. Run one failure at a time, and start each stopped node before the next step.

1. Show the nodes of every PostgreSQL database. In each list, one node is the `Leader`, one is the `Sync Standby`, and one is a `Replica`, and both standbys show `streaming` with a lag of 0:

	```sh
	for db in player session moderation dms rules; do docker compose exec $db-db-1 patronictl -c /config/patroni.yml list; done
	```

2. In a second terminal, send a Player read twice a second and count the answers:

	```sh
	for i in $(seq 70); do curl -s -w ' %{http_code}\n' -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8080/api/v1/players/me | grep -o '"code":"[A-Z_]*"\|[0-9]\{3\}$' | xargs; sleep 0.5; done | uniq -c
	```

3. While the loop runs, kill the Player leader that the list names, for example `player-db-2`, and list the nodes again:

	```sh
	docker compose kill player-db-2
	docker compose exec player-db-1 patronictl -c /config/patroni.yml list
	```

	The loop first prints `code:STORAGE_UNAVAILABLE 503`, while Player still runs requests and cannot reach a writable database. It then prints `code:NO_HEALTHY_INSTANCES 503`, while both Player replicas report unready. Within 25 seconds the synchronous standby is the `Leader`, and the loop ends with a run of `200`. Discovery removes no Player replica, because the [storage outage rules](contracts/resilience.md#storage-outages) keep a datastore failure out of the breakers.

4. Start the node again. Within about 20 seconds it is listed as a `Replica` that is `streaming`:

	```sh
	docker compose start player-db-2
	docker compose exec player-db-1 patronictl -c /config/patroni.yml list
	```

5. Stop etcd and register a player through Gateway with `POST /api/v1/players`. The registration returns `201`, because `failsafe_mode` keeps each leader writable while it reaches its other nodes. Then start etcd:

	```sh
	docker compose stop etcd
	docker compose start etcd
	```

6. List the members of both MongoDB replica sets. Each set has one `PRIMARY` and two `SECONDARY` members:

	```sh
	for set in mongodb university-mongodb; do docker compose exec $set-2 sh -c 'mongosh --quiet -u "$MONGO_ADMIN_USERNAME" -p "$MONGO_ADMIN_PASSWORD" --authenticationDatabase admin --eval "rs.status().members.forEach(m => print(m.name, m.stateStr))"'; done
	```

7. Kill the member that the list shows as `PRIMARY`, for example `mongodb-1`. List the members again on one that still runs. The killed member is `(not reachable/healthy)`. Another member becomes `PRIMARY` within 15 seconds, or within about 30 seconds when the first election round fails, so list again until one is. Then start the killed member. It returns as `SECONDARY`:

	```sh
	docker compose kill mongodb-1
	docker compose start mongodb-1
	```

To check every database, run the failover check. For each database it writes a marker, kills the primary, waits until another member accepts a second marker, starts the killed member, and reads both markers from it. It takes three to four minutes for all seven databases. Name databases to check only those: `player-db`, `session-db`, `moderation-db`, `dms-db`, `rules-db`, `mongodb`, and `university-mongodb`:

```sh
python3 scripts/check_failover.py
python3 scripts/check_failover.py player-db university-mongodb
```

Each database prints one line, such as `ok      player-db: killed player-db-2, player-db-1 accepted writes after 19.5 s, player-db-2 rejoined with both markers`. The command exits with status 0 when every line is `ok`.

These files implement the failover:

- CPR: [`compose.yaml`](../compose.yaml) declares `etcd`, the `x-patroni` nodes `<database>-1` to `<database>-3`, the `x-mongo` members, and the multi-host connection strings of each service and of the ETL. [`config/patroni/patroni.yml`](../config/patroni/patroni.yml) holds the Patroni settings, [`config/patroni/start.sh`](../config/patroni/start.sh) starts a node, and [`config/patroni/post_bootstrap.sh`](../config/patroni/post_bootstrap.sh) creates the service's role and database on the first leader. [`scripts/setup.py`](../scripts/setup.py) generates the shared MongoDB keyfiles, and [`scripts/check_failover.py`](../scripts/check_failover.py) is the check.
- `ChillGuysStudio/message-broker-service`: `internal/runtime/nested.go` and `internal/runtime/discovery.go` count `STORAGE_UNAVAILABLE` as a storage outage, not as a replica failure.

Each service answers `STORAGE_UNAVAILABLE` from these files:

| Service | Repository | File |
| --- | --- | --- |
| Player | `Tirppy/student-id-player-service` | `app/storage.py` |
| Session | `Tirppy/student-id-session-service` | `app/storage.py` |
| Moderation | `andyp1xe1/pad-moderation-service` | `src/moderation/errors.py` |
| Discord DMs | `andyp1xe1/pad-discord-dms-service` | `src/discord_dms/errors.py` |
| Applicant | `mcittkmims/applicant-service` | `src/main/java/md/pad/applicant/exception/StorageFailure.java` |
| Credential | `mcittkmims/credential-service` | `src/main/java/md/pad/credential/exception/StorageFailure.java` |
| Server Rules | `MaxNoragami/server-rules-service` | `src/main/java/com/chillguysstudio/serverrules/common/storage/StorageFailures.java` |
| University Record | `MaxNoragami/university-record-service` | `src/main/java/com/chillguysstudio/universityrecord/common/config/StorageFailures.java` |

## Shard the cache

The services cache common reads and authentication data on three Redis nodes, `cache-1` to `cache-3`. The [cache contract](contracts/cache.md) lists each cached read and its time to live. A consistent-hash ring decides which node holds each key, as the [cache sharding contract](contracts/cache-sharding.md) defines, so losing a node costs only the keys it owns. The cache changes no status and no body.

1. Read one player three times. Player caches the account under `v1:player:account:<player_id>` for 30 seconds. Set `PLAYER_ID` to the seed player:

	```sh
	export PLAYER_ID="$(python3 -c 'import json; print(json.load(open(".local/stack/seed-admin.json"))["player_id"])')"
	for i in 1 2 3; do curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8080/api/v1/players/$PLAYER_ID; done
	```

	Each read returns `200`. After the next scrape, 5 seconds later, Prometheus shows one more `miss` and two more `hit` results for the Player account cache:

	```sh
	curl -s --get 'http://127.0.0.1:9090/api/v1/query' \
		--data-urlencode 'query=sum by (result) (student_id_cache_requests_total{service="player",cache="account"})'
	```

2. Ask the reference ring which node owns the key, then look for the key on each node. The ring prints the key's order, owner first. Only the owner holds the key, with a time to live of at most 30 seconds:

	```sh
	python3 -c 'import sys; sys.path.insert(0, "scripts"); from cache_ring import Ring; print(Ring(["cache-1:6379", "cache-2:6379", "cache-3:6379"]).nodes_for(sys.argv[1]))' "v1:player:account:$PLAYER_ID"
	for n in 1 2 3; do echo "cache-$n exists $(docker compose exec -T cache-$n redis-cli exists v1:player:account:$PLAYER_ID) ttl $(docker compose exec -T cache-$n redis-cli ttl v1:player:account:$PLAYER_ID)"; done
	```

	For example, the order `['cache-3:6379', 'cache-1:6379', 'cache-2:6379']` puts the key on `cache-3`, which prints `exists 1`. The other nodes print `exists 0 ttl -2`.

3. Count the keys on each node. Each node holds only the keys it owns, and `redis-cli --scan` on one node lists them:

	```sh
	for n in 1 2 3; do echo "cache-$n $(docker compose exec -T cache-$n redis-cli dbsize)"; done
	```

4. Stop the node that owns the key, read the player again, and look for the key on the other nodes:

	```sh
	docker compose stop cache-3
	for i in 1 2 3 4; do curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8080/api/v1/players/$PLAYER_ID; sleep 0.6; done
	for n in 1 2; do echo "cache-$n exists $(docker compose exec -T cache-$n redis-cli exists v1:player:account:$PLAYER_ID)"; done
	```

	Every read returns `200`. The key is now on the second node of its order, `cache-1` in the example, and the other node still has none. Keys that the other nodes own stay where they are. Grafana's Prometheus data source shows the change by node with `sum by (node, result) (rate(student_id_cache_requests_total[1m]))`.

5. Start the node again:

	```sh
	docker compose start cache-3
	```

	After one second, the services use it again. It starts empty, so its keys miss once, and the copies on the next node expire within their time to live.

`python3 scripts/cache_ring.py` is the reference ring. It prints `Wrote .../docs/contracts/cache-ring-v1/vectors.json`, and `git diff docs/contracts/cache-ring-v1/vectors.json` then shows no change, because every service tests its own ring against that file.

These files implement the cache:

- CPR: the `cache-1`, `cache-2`, and `cache-3` services and the `x-cache` settings, `CACHE_NODES` and `CACHE_PASSWORD`, in [`compose.yaml`](../compose.yaml). [`scripts/cache_ring.py`](../scripts/cache_ring.py) is the reference ring, and [`docs/contracts/cache-ring-v1/vectors.json`](contracts/cache-ring-v1/vectors.json) holds its test vectors.
- Each service reads, fills, and invalidates its values in its cache file, and picks the node in its ring file:

| Service | Repository | Cache | Ring |
| --- | --- | --- | --- |
| Player | `Tirppy/student-id-player-service` | `app/cache.py` | `app/ring.py` |
| Session | `Tirppy/student-id-session-service` | `app/cache.py` | `app/ring.py` |
| Moderation | `andyp1xe1/pad-moderation-service` | `src/moderation/cache.py` | `src/moderation/ring.py` |
| Discord DMs | `andyp1xe1/pad-discord-dms-service` | `src/discord_dms/cache.py` | `src/discord_dms/ring.py` |
| Applicant | `mcittkmims/applicant-service` | `src/main/java/md/pad/applicant/cache/ReadCache.java` | `src/main/java/md/pad/applicant/cache/CacheRing.java` |
| Credential | `mcittkmims/credential-service` | `src/main/java/md/pad/credential/cache/ReadCache.java` | `src/main/java/md/pad/credential/cache/CacheRing.java` |
| Server Rules | `MaxNoragami/server-rules-service` | `src/main/java/com/chillguysstudio/serverrules/common/cache/Cache.java` | `src/main/java/com/chillguysstudio/serverrules/common/cache/Ring.java` |
| University Record | `MaxNoragami/university-record-service` | `src/main/java/com/chillguysstudio/universityrecord/common/cache/Cache.java` | `src/main/java/com/chillguysstudio/universityrecord/common/cache/Ring.java` |

## Run the end-shift saga

Ending a shift runs as a [saga](contracts/transactions.md) that the Message Broker coordinates. Session sets the shift to `ending` in its own database (`hold-shift`), Player awards the XP in its database (`award-shift`), and Session sets the shift to `ended` (`finish-end`). When the award fails for good, the compensations `revoke-shift-award` and `reopen-shift` undo the earlier steps in reverse order. `POST /api/v1/sessions/{session_id}/end` returns `200` in `ended` when the saga completes within the request, `202` in `ending` while it still runs, and `409 PROGRESSION_REJECTED` after a compensation.

1. Run the check. It stops and starts Player and the Broker, so run nothing else that does at the same time. It takes about a minute:

	```sh
	python3 scripts/check_sagas.py
	```

	The check prints one `ok` line for each case, with the saga from the listing:

	```text
	ok    normal run (4.9 s)
	      200 ended, 3 award rows, retry returned the same 200. Listing: completed: hold-shift=done/1 award-shift=done/1 finish-end=done/1
	ok    Player outage delays the saga (14.2 s)
	      202 ending while Player was stopped, then completed with 3 award rows. Listing: completed: hold-shift=done/1 award-shift=done/3 finish-end=done/1
	ok    permanent failure compensates (5.3 s)
	      end 409, saga compensated, shift active again, no award rows; the retry returned 409 PROGRESSION_REJECTED. Listing: compensated: hold-shift=compensated/1+1c award-shift=compensated/1+1c finish-end=skipped/0 cause rejected:AWARD_CONFLICT
	ok    Broker restart mid-saga (12.9 s)
	      202 ending, the Broker restarted mid-saga, recovery completed it. Listing: completed: hold-shift=done/1 award-shift=done/2 finish-end=done/1
	ok    repeated step (13.8 s)
	      the award was sent 3 times and applied once: 3 award rows. Listing: completed: hold-shift=done/1 award-shift=done/3 finish-end=done/1
	```

	Each step reads `operation=state/attempts`, and `+1c` counts compensation attempts. Each case compares the saga state in `broker-db`, the session status in `session-db`, and the Player ledger in `player-db`. No credentials are printed. To run one case, name it: `normal`, `player-outage`, `compensation`, `broker-restart`, or `repeated-step`. The command exits with status 0 when every case is `ok`.

2. List the sagas as an administrator, with the token from [Get an administrator token](#get-an-administrator-token). Grant the access again first, because the check revoked it:

	```sh
	curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" 'http://127.0.0.1:8080/api/v1/admin/broker/sagas?limit=20&flow=end-shift'
	```

	Each item shows the saga's state, its `cause` after a compensation, and each step's state, attempts, and last error kind. It never shows a payload, a player ID, or a session ID. Filter with `state=running`, `compensating`, `completed`, or `compensated`. Grafana's Prometheus data source shows `student_id_broker_sagas_total` by outcome and `student_id_broker_sagas_unresolved` by state. The Broker log shows each saga's `saga_started` and `saga_completed` or `saga_compensated` records, and a `WARN` `saga_step` record for each failed call:

	```sh
	docker compose logs --no-log-prefix message-broker | grep '"event":"saga_'
	```

3. Watch a Player outage by hand. In Postman, send the guided demo requests 01 to 27 and 30 to 38. Requests 28 and 29 need the overload helper and can be skipped. Before request 39, stop Player:

	```sh
	docker compose stop player
	```

	Send 39. The end returns `202` with the shift `ending`. List the running sagas:

	```sh
	curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" 'http://127.0.0.1:8080/api/v1/admin/broker/sagas?flow=end-shift&state=running'
	```

	The saga is `running`. `hold-shift` is `done`, `award-shift` is `pending` with `last_error_kind` `no_healthy_instances` and an `attempts` count that grows on each list, and `finish-end` is `pending`. Start Player again:

	```sh
	docker compose start player
	```

	Send 40 until it passes. Within about 20 seconds the shift is `ended`, and the listing shows the saga `completed` with every step `done`.

These files implement the saga:

- CPR: the [distributed transactions contract](contracts/transactions.md), [`sagas.proto`](../proto/student_id/sagas/v1/sagas.proto) with the coordinator and participant RPCs, `ListSagas` in [`broker.proto`](../proto/student_id/broker/v1/broker.proto), and [`scripts/check_sagas.py`](../scripts/check_sagas.py).
- `ChillGuysStudio/message-broker-service`: `internal/runtime/sagas.go` starts sagas, runs the steps, retries, compensates, and recovers unfinished sagas. `internal/store/sagas.go` and `internal/store/migrations/004_sagas.sql` keep the saga state in `broker-db`. `internal/runtime/saga_listing.go` serves `ListSagas`.
- `Tirppy/student-id-session-service`: `app/ending.py` runs the end request with `hold-shift`, starts the saga, relays sagas that the Broker has not accepted, and serves `finish-end` and `reopen-shift`.
- `Tirppy/student-id-player-service`: `app/progression.py` serves `award-shift` and `revoke-shift-award` on the progression ledger.
- `ChillGuysStudio/gateway-service`: `internal/runtime/brokersagas.go` serves `GET /api/v1/admin/broker/sagas`.

## Check the repository

These checks cover the repository tools and links. They do not need a running stack:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
docker compose config --quiet
```

Pass `--quiet` to `docker compose config`. Without it, the command prints resolved credentials.

Read the contracts for the behavior behind each grade: [resilience](contracts/resilience.md) for Discovery, replicas, breakers, and alerts, and [HTTP conventions](contracts/http.md) for idempotency, retries, and task limits.
