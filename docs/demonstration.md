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

Gateway sends each public request to the Message Broker over REST with its target service. Client requests stay REST end to end. Domain services send every peer call to the Broker as a typed gRPC call on port `50051`. The Broker selects one ready replica with round-robin and writes one `INFO` `dispatch` record for each attempt. After a shift has started, list the dispatch records:

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

Make one consumer fail on every attempt while it stays ready. Player's readiness check only reads, so a read-only database makes each delivery fail with a retryable 500:

```sh
docker compose exec player-db psql -U player -d player_db -c 'ALTER SYSTEM SET default_transaction_read_only = on' -c 'SELECT pg_reload_conf()'
```

End a shift. After five attempts, about a minute, the `ShiftEnded` delivery to Player appears in the listing with reason `exhausted`. Restore the database:

```sh
docker compose exec player-db psql -U player -d player_db -c 'ALTER SYSTEM RESET default_transaction_read_only' -c 'SELECT pg_reload_conf()'
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

## Run the HTTP checks

The Postman collections run through the public Gateway. The [guided demo](../postman/GUIDED-DEMO.md) walks through registration, a shift, overload, and the log download, in Postman or with Newman:

```sh
./scripts/run_newman.sh
./scripts/run_newman.sh --with-overload
```

[HTTP checks](../postman/HTTP-CHECKS.md) describes the read-only public folder and the private Discovery health folder.

## Check the repository

These checks cover the repository tools and links. They do not need a running stack:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
docker compose config --quiet
```

Pass `--quiet` to `docker compose config`. Without it, the command prints resolved credentials.

Read the contracts for the behavior behind each grade: [resilience](contracts/resilience.md) for Discovery, replicas, breakers, and alerts, and [HTTP conventions](contracts/http.md) for idempotency, retries, and task limits.
