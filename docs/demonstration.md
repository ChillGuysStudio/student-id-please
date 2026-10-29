# Architecture and demonstration guide

This guide covers the multi-replica architecture, safe demonstration steps for a prepared operator laptop, the requirements checklist for grades 3 through 10, and verified runtime facts.

## Architecture

The deployment scales each of the eight domain services to two replicas and adds the Discovery service for instance registration, health monitoring, and circuit breaker removals. Gateway and Discovery use Go, the accepted shared banned language. Domain services continue to use Java with Spring Boot or Python with FastAPI according to the team ownership mapping:

- Adrian (`mcittkmims`): Applicant and Credential (Java, Spring Boot)
- Alexei (`MaxNoragami`): Server Rules and University Record (Java, Spring Boot)
- Andrei (`andyp1xe1`): Moderation and Discord DMs (Python, FastAPI)
- Alexandru (`Tirppy`): Player and Session (Python, FastAPI)
- Shared infrastructure: Gateway and Discovery (Go)

The [architecture diagram](diagrams/architecture.mmd) shows the replicated topology. GitHub renders the Mermaid source as a diagram.

### Request paths and network boundaries

1. Public client REST connects to the Gateway public listener on `127.0.0.1:8080`. Gateway validates client bearer tokens, checks route policy, and selects an active backend replica.
2. Internal service REST connects to the Gateway internal listener on `http://gateway:8083`. This listener is on the private container network and exposes no public host port.
3. Gateway reads the private Discovery service at `http://discovery-slot-1:8081` on this prepared laptop deployment. The shared contract in [docs/contracts/resilience.md](contracts/resilience.md) defines a default port of `:8084`, but deployment configurations can specify a different private port and container name. Gateway refreshes registry snapshots in the background and balances requests across live replicas using lexical round-robin selection.
4. Every replica registers directly with Discovery through private HTTP PUT requests. Every replica also exposes a private health probe endpoint at `GET /internal/v1/status`. Control-plane requests use separate control credentials (`X-Control-Name` and `X-Control-Token`) authenticated against `CONTROL_PLANE_TOKENS`. These credentials stay completely separate from business credentials and Gateway receiver tokens.
5. The stack runs two replicas for each of the eight domain services. Each domain service is the sole owner of its datastore. Replicas of the same service share that service's store; no cross-domain store sharing is permitted. Five dedicated PostgreSQL instances store relational state for Player, Session, Server Rules, Moderation, and Discord DMs. Two MongoDB instances store documents for Applicant, Credential, and University Record.
6. The RabbitMQ broker handles asynchronous domain events. A dedicated publisher process (`moderation-publisher`) drains outbox records from Moderation's PostgreSQL store and publishes them to RabbitMQ. Three domain event paths are implemented and verified historically: `CaseInitialized` by one initializer, `DecisionScored` applied once to Session, and `ShiftEnded` applied once to Player. A fourth event, `DisciplinaryActionApplied`, is defined by contract but remains unverified in runtime evidence.
7. Clients establish direct WebSocket connections to the selected Discord DMs replica on port 8009 or port 18009. The client obtains the replica connection URL through Gateway REST negotiation (`POST /api/v1/sessions/{session_id}/realtime-negotiation`). Gateway does not relay WebSocket upgrade handshakes or chat frames. Redis relays live messages between Discord DMs replicas through Pub/Sub and stores single-use chat tickets.
8. Discovery sends health and critical-load alerts to an external Discord webhook. The notification adapter logs only external receipt IDs and timestamps, never credentials or webhook URLs.
9. Discovery stores durable removal records on a persistent private volume at the location configured by `DISCOVERY_STATE_FILE` (for example, `/data/removals.json`). This endpoint and its file are internal only, never published to ingress.

## Prepared laptop setup

To bootstrap a clean clone, run `python3 scripts/setup.py`, `docker compose up -d --wait`, and `python3 scripts/seed_university_catalog.py`. The seeder imports the 69-entry University Record catalog. Without it, `POST /api/v1/sessions/{sid}/start` returns `409 DEPENDENCY_REJECTED`. The demonstration relies on the following:

1. Every service image defaults to `latest` in `compose.yaml`. To pin a version, set the matching key (`GATEWAY_IMAGE`, `DISCOVERY_IMAGE`, `PLAYER_IMAGE`, …) in `.env` to `owner/repo:version`. [releases/services.json](releases/services.json) records the released versions.
2. Stable UUID slot identifiers (`INSTANCE_ID`) and replica network origins are already configured.
   `compose.yaml` runs Discovery, the Gateway, and replica 1 of each domain service. `REPLICAS` in `.env`, default `2`, or a per-service `<SERVICE>_REPLICAS`, sets the count. `scripts/replicas.py` writes the ignored `compose.replicas.yaml` with replicas 2 to N, which `.env` loads through `COMPOSE_FILE`. Replica 1 keeps the service name, such as `applicant`, with the alias `applicant-slot-1`. Replica `n` is the service `applicant-slot-<n>`. Each replica registers `INSTANCE_HTTP_URL` as `http://<service>-slot-<n>:<port>`. To change the count, edit `.env`, run `python3 scripts/replicas.py`, then `docker compose up -d --remove-orphans`.

   `.env` supplies the identities. `scripts/setup.py` generates them, and `.env.example` lists the names.

   - `<SERVICE>_SLOT1_INSTANCE_ID`: the UUID of replica 1. Replicas 2 to N derive stable UUIDs from `REPLICA_SEED`. `GATEWAY_INSTANCE_ID` and `DISCOVERY_INSTANCE_ID` cover the other two registrants.
   - `<SERVICE>_CONTROL_TOKEN`: the outgoing control-plane credential of a service. Both slots share it. Gateway, Discovery, and `OPERATOR` have one each.
   - `DISCOVERY_URL`: optional. It defaults to the Compose Discovery at `http://discovery-slot-1:8081`.
   - `DISCOVERY_DISCORD_WEBHOOK_URL`: optional. Leave it empty to send no alerts.
   - `DMS_PORT` and `DMS_REPLICA_PORT_BASE`: host WebSocket ports. Replica 1 uses `DMS_PORT` (`8009`), and replica `n` uses `DMS_REPLICA_PORT_BASE + n - 2` (`18009`, `18010`, …).

   Compose builds each receiver's `CONTROL_PLANE_TOKENS` map from the Discovery and operator tokens. Discord DMs uses `http://gateway-slot-1:8083` for `SESSION_URL` and `UNIVERSITY_URL`, so the breaker sees Gateway's registered origin.
3. Secrets and control tokens are already generated and trusted locally in ignored environment and Compose override files, specifically `.env` and `.local/stack/`. These ignored local files are not distributed.
4. Database, broker, and Redis volumes are preserved. Do not run `docker compose down --volumes`.
5. WebSocket flags distinguish local and remote connections. Setting `GATEWAY_ALLOW_INSECURE_WS` and `GATEWAY_ALLOW_LOCAL_WS` permits unencrypted local testing against `ws://localhost:18009`. A remote demonstration requires the laptop's reachable address and secure `wss`. A remote client pointing to its own localhost is invalid.
6. Whole-stack restarts, data mutations, and failure injections are not an automatic startup routine upon presentation. Use existing verified historical proofs rather than re-executing business writes. Do not mutate real accounts, emails, or moderation decisions during the demonstration.
7. Existing local proof scripts are internal tools, not portable public runners. Do not invent new runners or claim that local verifiers are portable across machines.

## Verification commands

Run these public commands to inspect the repository and verify the deployment without printing secrets or mutating data.

### Run repository tests

To verify unit tests, link integrity, and collection schemas, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
```

### Validate local Compose configuration safely

To validate the operator Compose setup without exposing secrets, pass the `--quiet` flag. Never run `docker compose config` without `--quiet` because doing so prints resolved credentials to standard output:

```sh
docker compose config --quiet
```

### Inspect running containers

To check running containers without revealing environment variables:

```sh
docker ps
```

The prepared deployment runs 28 containers: 16 domain service replicas (two per domain), one Gateway container, one Discovery container, nine backing containers (five PostgreSQL, two MongoDB, one RabbitMQ, and one Redis), and one Moderation outbox publisher container.

### Check public Gateway health

To verify anonymous Gateway liveness on public ingress:

```sh
curl -fsS http://127.0.0.1:8080/healthz
```

### Run safe public Newman smoke tests

To run the safe read-only HTTP checks through the documented Newman runner:

```sh
./scripts/run_newman.sh --http
```

This runner executes four anonymous GET requests against the public Gateway at `http://127.0.0.1:8080`. It confirms public liveness, verifies denial of private status and registry endpoints, checks that unauthenticated player requests return 401, and confirms that Gateway private attribution headers remain hidden.

Never print environment variables, control headers, passwords, web tokens, or query tickets in commands or terminal output.

## Requirements checklist

The table below maps each course grade from 3 through 10 to CPR issues and contracts, splitting the delivery claim across source, publication, runtime, and cumulative status. [releases/services.json](releases/services.json) records the current released version, source commit, and image digest of each service.

| Grade and requirement | Linked issues and contracts | Source status | Publication status | Runtime status | Cumulative claim |
| --- | --- | --- | --- | --- | --- |
| Inherited Grades 1 and 2: Baseline architecture, contracts, and flows | [#124](https://github.com/ChillGuysStudio/student-id-please/issues/124), [#126](https://github.com/ChillGuysStudio/student-id-please/issues/126), [docs/contracts/resilience.md](contracts/resilience.md) | Merged in CPR and domain services | Official public images available | Normal 3 initializer flows, 69 snapshot and reservation bindings, original decision with real Server Rules, score 10 via broker once, Player 3 ledger rows and XP 10 verified historically | Reported complete in prior work; access confirmation required before presentation |
| Grade 3: Status endpoint and structured logs for every service | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#129](https://github.com/ChillGuysStudio/student-id-please/issues/129)-[#138](https://github.com/ChillGuysStudio/student-id-please/issues/138), [#222](https://github.com/ChillGuysStudio/student-id-please/issues/222), [docs/contracts/resilience.md#status-and-load](contracts/resilience.md#status-and-load) | Implemented across all 8 domain services, Gateway, and Discovery | Official packages for all ten services, listed in [releases/services.json](releases/services.json) | 18 status processes return private 200 and reject wrong tokens with 401; all 8 Python domain replicas emit current-boot startup identities via read-only Uvicorn `--log-config` mount with ticket and bearer redaction verified | Unclaimed and open (startup visibility verified; not every runtime logging event class is proven) |
| Grade 4: Go Discovery registration, background renewal, and container image | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#139](https://github.com/ChillGuysStudio/student-id-please/issues/139), [#141](https://github.com/ChillGuysStudio/student-id-please/issues/141), [#147](https://github.com/ChillGuysStudio/student-id-please/issues/147)-[#154](https://github.com/ChillGuysStudio/student-id-please/issues/154), [docs/contracts/resilience.md#registry-http-api](contracts/resilience.md#registry-http-api) | Discovery registration engine and domain startup registration loops implemented | Discovery and domain service public images published | Startup PUT requests succeed, background lease renewal runs every 5 seconds with 15-second lease window | Unclaimed and open |
| Grade 5: Two replicas per domain service with dynamic registration and removal | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#139](https://github.com/ChillGuysStudio/student-id-please/issues/139), [#140](https://github.com/ChillGuysStudio/student-id-please/issues/140), [#145](https://github.com/ChillGuysStudio/student-id-please/issues/145), [#172](https://github.com/ChillGuysStudio/student-id-please/issues/172), [#174](https://github.com/ChillGuysStudio/student-id-please/issues/174), [docs/contracts/resilience.md#lookup-refresh-and-round-robin](contracts/resilience.md#lookup-refresh-and-round-robin) | Gateway routes through Discovery; Compose runs slot 1 and slot 2 containers | Published images run in both replica slots | 17 total registrants active; dynamic removal verified on Credential replica | Unclaimed and open |
| Grade 6: Round-robin balancing and correct business and direct chat behavior | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#146](https://github.com/ChillGuysStudio/student-id-please/issues/146), [#155](https://github.com/ChillGuysStudio/student-id-please/issues/155)-[#163](https://github.com/ChillGuysStudio/student-id-please/issues/163), [#174](https://github.com/ChillGuysStudio/student-id-please/issues/174), [#177](https://github.com/ChillGuysStudio/student-id-please/issues/177), [docs/contracts/resilience.md#direct-dms-websockets](contracts/resilience.md#direct-dms-websockets) | Gateway round-robin and instance-bound negotiation fixes merged; all 8 domain replica-state audits completed | Official Gateway, Server Rules, and Discord DMs packages deployed | Twelve Player reads and twelve completed Moderation replays each split six per receiver. Two direct DMs messages crossed the actual replicas, with once-only acknowledgement, consumed-ticket denial, reconnect, and history preserved after both DMs replicas restarted | Unclaimed and open. Simultaneous uncommitted first-write races and live membership changes remain separate |
| Grade 7: Circuit breaker accounting across outbound callers | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#164](https://github.com/ChillGuysStudio/student-id-please/issues/164)-[#171](https://github.com/ChillGuysStudio/student-id-please/issues/171), [#175](https://github.com/ChillGuysStudio/student-id-please/issues/175), [#218](https://github.com/ChillGuysStudio/student-id-please/issues/218), [#224](https://github.com/ChillGuysStudio/student-id-please/issues/224), [#225](https://github.com/ChillGuysStudio/student-id-please/issues/225), [docs/contracts/resilience.md#bounded-calls-and-failure-accounting](contracts/resilience.md#bounded-calls-and-failure-accounting) | Physical-completion breaker logic merged in Gateway, Server Rules, Session, Moderation, Applicant, Credential, and University Record; DMs [#169](https://github.com/ChillGuysStudio/student-id-please/issues/169) included in the official release | Official packages for all ten services published; live breaker runs are limited to the Credential path | Credential failure path verified with 3 errors in 0.121s under T=2s and W=7s; live failure injection across every domain caller and exact boundary cases remain separate checks | Unclaimed and open (all-caller live failure injection and DMs runtime breaker unproven) |
| Grade 8: Periodic status polling and critical load detection | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#142](https://github.com/ChillGuysStudio/student-id-please/issues/142), [#143](https://github.com/ChillGuysStudio/student-id-please/issues/143), [#176](https://github.com/ChillGuysStudio/student-id-please/issues/176), [docs/contracts/resilience.md#status-and-load](contracts/resilience.md#status-and-load) | Discovery periodic polling and critical load ratio logic implemented | Discovery public image published | 17 registrants polled; load test reached 100/100 admitted tasks, returned 503 TASK_LIMIT_EXCEEDED for excess tasks, and recovered to zero | Unclaimed and open (cumulative scaling and resilience unproven) |
| Grade 9: Discord webhook notifications for health and load | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#144](https://github.com/ChillGuysStudio/student-id-please/issues/144), [#176](https://github.com/ChillGuysStudio/student-id-please/issues/176), [docs/contracts/resilience.md#logs-and-notification-interface](contracts/resilience.md#logs-and-notification-interface) | Discovery Discord notification adapter implemented | Discovery public image published | Real Discord critical alert (1564905024876970017) and recovery alert (1564905047026831437) returned GET 200 on readback | Unclaimed and open (cumulative scaling and resilience unproven) |
| Grade 10: Failed-instance removal, healthy replica continuity, and explicit re-entry | [#125](https://github.com/ChillGuysStudio/student-id-please/issues/125), [#140](https://github.com/ChillGuysStudio/student-id-please/issues/140), [#175](https://github.com/ChillGuysStudio/student-id-please/issues/175), [docs/contracts/resilience.md#removal-re-entry-and-writes](contracts/resilience.md#removal-re-entry-and-writes) | Discovery durable removal and re-entry endpoints implemented | Discovery and service packages published | Credential replica removed after 3 failures; healthy peer continued serving; Discovery restart preserved tombstone; operator re-entry succeeded after 2 healthy probes | Unclaimed and open (only Credential failure subpath verified; overall grade not claimed) |

## Current runtime evidence

The facts below were verified on the demonstration deployment:

1. **Active deployment**: All 17 registrants across 8 domain services (two replicas each) and Gateway are ready and renewing leases. The host runs 28 containers including backing stores and the Moderation publisher.
2. **Historical baseline**: Three initializer flows, 69 snapshot and reservation bindings, the original decision with real Server Rules, score 10 via the RabbitMQ broker once, and Player 3 ledger rows with XP 10 were verified during earlier baseline runs before the controlled shutdown and restart. Do not reissue business writes to avoid corrupting this historical state.
3. **Round-robin routing**: Gateway round-robin routing was verified with twelve total requests (six requests to each replica) for Player and twelve completed decision replays (six to each replica) for Moderation, without concurrency claims.
4. **Circuit breaker removal and recovery**: A Gateway-to-Credential test produced three connection errors in 0.121 seconds under `T = 2` seconds and `W = 7` seconds. Gateway tripped and removed the failed replica generation. The healthy replica continued serving requests with status 200. A Discovery restart retained the removal tombstone in the configured `DISCOVERY_STATE_FILE`. Restarting the failed replica kept it in the removed state until an operator issued a reactivation command after the required cooldown and two healthy status probes. The fresh generation renewed and returned to service.
5. **Load limit and alerts**: Gateway admitted 100 concurrent tasks, rejected excess requests with `503 TASK_LIMIT_EXCEEDED`, and returned to zero active tasks upon completion. Discovery logged critical load and sent alerts to Discord. Real messages `1564905024876970017` and `1564905047026831437` returned 200 on readback.
6. **Package status**: [releases/services.json](releases/services.json) is the source of truth for released versions. Moderation and Discord DMs images lack repository source labels. The record states this instead of claiming them.
7. **Startup logging and replica audits**:
   - Under issue 222, all eight Python domain replicas now emit current-boot startup identities via a read-only Uvicorn `--log-config` mount without changing images, environment maps, ports, or original mounts. An auth-only direct socket probe verified that chat tickets and bearer tokens are absent from both DMs replica logs.
   - All eight domain replica-state audits (#155 through #162) are recorded. DMs history survived sequential restarts of both replicas with the original two messages retained once.
8. **Known open items**:
   - The initial direct-chat probe returned static port 8009 twice and stopped before either socket connected. Its successful ticket operations and failed verifier remain preserved. Gateway 3.0.6 (`89ccbb0106db31ddf4011d29842dd49f3db064eb`) repaired selected-instance negotiation, and Gateway 3.0.7 (`4acf7de01bdec682be7d5a7519781428ca380ece`) plus Server Rules 3.0.5 (`e65644e91a546e91d177757c064f2b9ea8361cb7`) added physical-completion capture and pending-outcome retention across temporary absent snapshots.
   - After the negotiation repair, negotiation returned ports 8009 and 18009 for two existing participants. Direct frames crossed the two actual replicas in both directions, including after the scheduled authorization recheck. A duplicate frame returned the same acknowledgement without another message. Reusing a consumed ticket returned 401. A fresh ticket reconnected, and REST history returned exactly the two messages. The verifier retained the original unused message IDs and requested new handshake tickets only after the prior successful tickets had expired. It created no account, session, case, decision, external Discord message, or direct database write.
   - Simultaneous uncommitted first-write races, live membership changes during an active socket, and live failure injection across every domain caller remain separate open checks.
   - Cumulative grades remain unproven pending the completion of these open items.

## Presentation readiness

Keep these facts in mind when preparing for the laboratory demonstration:

1. Professor repository access confirmation is an external prerequisite before presentation.
2. The assignment presentation deadline and demonstration slot booking are unknown and cannot be scheduled from this environment. The operator must confirm booking details separately.
3. The demonstration requires a single working prepared laptop. Each team member must understand their two owned domain services and the shared Gateway and Discovery services.
4. Peer reviews on CPR pull requests must be substantive. Do not approve pull requests solely to satisfy an account checklist.
5. Do not check empty boxes or claim completed grades without running the corresponding runtime verification.
