# Demonstrate the stack

This guide starts the stack on a laptop, scales a domain service with Compose, and follows the logs while replicas join and leave. Every step uses plain `docker` and `docker compose` commands.

The diagram in [architecture](architecture.md) shows the replicated topology.

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

	The command returns when every container is running and every container with a health check reports healthy. Each domain service starts two replicas.

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

The same commands work for every domain service listed above. Gateway, the Message Broker, `broker-db`, Discovery, and the Moderation outbox publisher run as one instance each.

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

Apply a disciplinary action as the global administrator with `POST /api/v1/disciplinary-actions`. After five attempts, about a minute, the `DisciplinaryActionApplied` delivery to Player appears in the listing with reason `exhausted`. Restore the permission:

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

1. Make sure Player has two replicas, then send sequential requests as a player. `TOKEN` holds a player access token:

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

The ETL service copies analytics data from the eight domain services into `warehouse-db`, as the [warehouse contract](contracts/warehouse.md) defines. It runs every `ETL_INTERVAL`, five minutes by default.

1. Play a shift, for example with the guided demo in [Run the HTTP checks](#run-the-http-checks). Then run one load:

	```sh
	docker compose run --rm etl --once
	```

	Each `etl_source` record reports one service. The command exits with status 0 when all eight load, and with status 3 when the interval run holds the lock. Run it again to see `rows_written` at 0 for every source.

2. Query the facts:

	```sh
	docker compose exec warehouse-db psql -U warehouse -c "
		SELECT s.session_id, s.duration_seconds, f.processed_count, f.score, count(d.decision_id) AS decisions,
			count(*) FILTER (WHERE d.correct) AS correct
		FROM warehouse.fact_shift_score f JOIN warehouse.dim_shift s USING (session_id)
		LEFT JOIN warehouse.fact_decision d USING (session_id) GROUP BY 1, 2, 3, 4"
	```

3. Read the history of runs:

	```sh
	docker compose exec warehouse-db psql -U warehouse -c "
		SELECT source, outcome, rows_read, rows_written, error_kind, finished_at
		FROM warehouse.etl_runs ORDER BY finished_at DESC LIMIT 8"
	```

4. Stop one source and run a load. That source reports `failed` with `unavailable`, and the other seven load:

	```sh
	docker compose stop dms-db-1 dms-db-2 dms-db-3
	docker compose run --rm etl --once
	docker compose start dms-db-1 dms-db-2 dms-db-3
	```

5. Show that the reader role cannot read a hidden column. The command fails with `permission denied for table players`:

	```sh
	docker compose exec player-db-1 psql -h /tmp -U postgres -d player_db -c 'SET ROLE warehouse_reader' -c 'SELECT password_hash FROM players'
	```

## Fail over a database

Player, Session, Moderation, Discord DMs, and Server Rules each have three PostgreSQL nodes, as the [replication contract](contracts/replication.md) defines.

1. Show the nodes. One is the leader, one is the synchronous standby, and one is a replica:

	```sh
	docker compose exec player-db-1 patronictl -c /config/patroni.yml list
	```

2. Kill the leader that the list names, for example `player-db-2`:

	```sh
	docker compose kill player-db-2
	docker compose exec player-db-1 patronictl -c /config/patroni.yml list
	```

	Requests that need Player answer `503` with `STORAGE_UNAVAILABLE` or `NO_HEALTHY_INSTANCES` for up to 25 seconds. Then another node leads, and requests succeed. Discovery removes no replica.

3. Start the node again. It rejoins as a replica:

	```sh
	docker compose start player-db-2
	```

4. Stop etcd. Every database keeps accepting writes:

	```sh
	docker compose stop etcd
	docker compose start etcd
	```

To check every database, run the failover check. It writes a marker, kills the primary, waits until another member accepts a second marker, starts the killed member, and reads both markers from it. It takes about four minutes:

```sh
python3 scripts/check_failover.py
python3 scripts/check_failover.py player-db
```

Applicant and Credential share a MongoDB replica set with three members, and University Record has its own. List the members of the first one:

```sh
docker compose exec mongodb-2 sh -c 'mongosh --quiet -u "$MONGO_ADMIN_USERNAME" -p "$MONGO_ADMIN_PASSWORD" --authenticationDatabase admin --eval "rs.status().members.forEach(m => print(m.name, m.stateStr))"'
```

Kill the member that the list shows as `PRIMARY`, for example `mongodb-1`. List the members again on one that still runs. Within about 15 seconds another member is `PRIMARY`. Then start the killed member:

```sh
docker compose kill mongodb-1
docker compose start mongodb-1
```

## Shard the cache

The services spread cached values over three Redis nodes with a consistent-hash ring, as the [cache sharding contract](contracts/cache-sharding.md) defines. Losing a node costs only the keys it owns.

1. Play a shift, for example with the guided demo in [Run the HTTP checks](#run-the-http-checks). Then count the keys on each node:

	```sh
	for n in 1 2 3; do echo "cache-$n $(docker compose exec -T cache-$n redis-cli dbsize)"; done
	```

	Each node holds a share of the keys. `redis-cli --scan` on one node lists only the keys it owns.

2. Stop one node, and play again:

	```sh
	docker compose stop cache-2
	```

	Requests keep their status and body. Keys that `cache-2` owned are loaded from the datastore once and stored on the next node. The other nodes keep serving their own keys. Grafana's Prometheus data source shows the change with `sum by (node, result) (rate(student_id_cache_requests_total[1m]))`.

3. Start the node again:

	```sh
	docker compose start cache-2
	```

	After one second, the services use it again. Its old values expire within their time to live.

## Run a saga across two databases

Ending a shift runs as a [saga](contracts/transactions.md) that the Message Broker coordinates. Session sets the shift to `ending`, Player awards the XP, and Session sets the shift to `ended`. Each step commits in its own database. When a step fails for good, compensations undo the earlier steps in reverse order.

1. Run the check. It stops and starts Player and the Broker, so run nothing else that does at the same time:

	```sh
	python3 scripts/check_sagas.py
	```

	It prints one line per case: a normal run, a Player outage that delays the saga, a permanent failure that compensates, a Broker restart mid-saga, and a repeated step. Each case compares the saga state, the session status, and the Player ledger, and prints the saga from the listing. No credentials are printed. To run one case, name it: `normal`, `player-outage`, `compensation`, `broker-restart`, or `repeated-step`.

2. List the sagas as an administrator, with the token from [List topics](#list-topics):

	```sh
	curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" 'http://127.0.0.1:8080/api/v1/admin/broker/sagas?limit=20&flow=end-shift'
	```

	Each item shows the saga's state, its cause after a compensation, and each step's state and attempts. It never shows a payload. Filter with `state=running`, `compensating`, `completed`, or `compensated`. Grafana's Prometheus data source shows `student_id_broker_sagas_total` by outcome and `student_id_broker_sagas_unresolved` by state.

3. Watch a Player outage. Stop Player and end a shift: the end returns `202` with the shift `ending`, and the listing shows the saga `running` with a growing `attempts` count on `award-shift`. Start Player again, and the saga completes:

	```sh
	docker compose stop player
	docker compose start player
	```

## Run the HTTP checks

The Postman collections run through the public Gateway. The [guided demo](../postman/GUIDED-DEMO.md) walks through registration, a shift, overload, and the log download, in Postman or with Newman:

```sh
./scripts/run_newman.sh
./scripts/run_newman.sh --with-overload
```

[HTTP checks](../postman/HTTP-CHECKS.md) describes the read-only public folder and the private Discovery health folder.

Each service has its own collection in `postman/`: `applicant`, `credential`, `discord-dms`, `moderation`, `server-rules`, and `university-record`. The runner creates what a collection needs through the public Gateway, then runs it with the same redaction and report:

```sh
./scripts/run_newman.sh --service applicant
```

The runner registers disposable players, builds a team and a Session with an assigned Moderator, starts the shift and opens a case where the collection needs one, and grants a disposable player administrator access for the run. It revokes that access when the run ends, as the [catalog seed](../scripts/seed_university_catalog.py) does. The grant runs `docker compose exec player` in the repository root. Pass `--compose-dir DIR` when the stack runs from another directory. `server-rules` needs a published rule version, and `moderation` opens a second case for its ban folder. The report goes to `.local/postman/<service>/newman-htmlextra.html`. To see which services handle a request, follow its `X-Request-ID` in the Broker log as [the guided demo](../postman/GUIDED-DEMO.md#follow-a-request-through-the-services) describes.

## Check the repository

These checks cover the repository tools and links. They do not need a running stack:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
docker compose config --quiet
```

Pass `--quiet` to `docker compose config`. Without it, the command prints resolved credentials.

Read the contracts for the behavior behind each grade: [resilience](contracts/resilience.md) for Discovery, replicas, breakers, and alerts, and [HTTP conventions](contracts/http.md) for idempotency, retries, and task limits.
