# Message Broker dispatch contract

This contract moves service-to-service REST, service-call authorization, replica selection, and backend breakers from Gateway to the Message Broker. Gateway keeps client-facing work only. The Broker dispatches over REST. The [queues and topics contract](queues.md) adds the per-service targeted queue that every dispatch passes through, and the topic queues that carry domain events in the Broker's own PostgreSQL.

The [discovery and resilience contract](resilience.md) still defines registration, status, the bounded-call rules, and failure accounting for every caller. The [HTTP contract](http.md) defines error bodies and idempotency. The [gateway identity module](https://github.com/ChillGuysStudio/gateway-service/blob/dev/docs/contracts/gateway-identity.md) defines the token profiles. This contract changes who issues and verifies those tokens, not their format.

The [service-to-service gRPC contract](grpc.md) moves service ingress, publish, push delivery, the Broker's policy reads, status, log export, and the topic listing to gRPC. Its policy table replaces the internal route table, assertions bind the full method name and the request message bytes, and attribution moves to trailers. Gateway dispatch of client requests stays REST as this contract defines it.

## Topology

- Clients call Gateway's public listener on `:8080`. Gateway authenticates the client, applies ingress limits, signs the receiver assertion, and sends the request to the Broker with an explicit target owner.
- Domain services send every peer call to the Broker. The Broker authenticates the caller, applies the internal route table and policy, signs the receiver assertion, selects one instance, and owns that instance's breaker.
- The Broker reads the registry from Discovery and reports breaker trips to Discovery. Registration, lookup, removal, and status probes stay direct control-plane HTTP.
- Producers publish domain events to the Broker, and the Broker pushes them to subscribers as the [queues and topics contract](queues.md) defines.
- Direct Discord DMs WebSockets and database connections do not pass through the Broker.

The Broker registers as `message-broker`. Compose runs one Broker replica as service `message-broker`, listening on `:8080` with no host port. It advertises `INSTANCE_HTTP_URL=http://message-broker:8080`, Domain callers set `BROKER_URL` and Gateway sets `GATEWAY_BROKER_URL` to that same origin. Discovery rejects two live instances with one `http_url`, so this version does not scale the Broker.

## Endpoints

The Broker serves one listener. It keeps the request path byte for byte. The signed `path` claim therefore matches the path that the receiver sees.

| Request | Caller | Behavior |
| --- | --- | --- |
| `POST /internal/v1/topics/{topic}/events` | A producer with `X-Service-Name` and `X-Service-Token` | [Publish](queues.md#publish). The Broker serves it before the route table. |
| Any path matching an internal route | A domain service with `X-Service-Name` and `X-Service-Token` | Service ingress. The Broker matches the route table, authenticates and authorizes the caller, signs a receiver assertion, and dispatches. |
| Any path | Gateway with `X-Service-Name: gateway`, `X-Service-Token`, and `X-Broker-Target` | Gateway dispatch. Gateway already authorized the request. The Broker verifies Gateway's assertion and dispatches. |
| `GET /internal/v1/status` | `discovery` or `operator` control credentials | The [status snapshot](resilience.md#status-and-load). |
| `GET /internal/v1/logs` | `gateway` or `operator` control credentials | The [instance export](logging.md#instance-export). |
| `GET /health` | Anyone on the container network | Liveness, `200 {"status":"ok"}`. |

The authenticated `X-Service-Name` selects the mode. `gateway` selects Gateway dispatch. Any other configured caller selects service ingress. Status, logs, and health run outside both business admission gates.

The internal route table moves unchanged from Gateway's `InternalRoutes()`. Its paths are mostly `/internal/v1/*`. One internal route is `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` for Moderation and Server Rules. The Broker serves it on service ingress by its existing caller allowlist. Unagreed routes still return `503 POLICY_UNAVAILABLE`.

## Credentials

| Hop | Headers | Configuration |
| --- | --- | --- |
| Domain service to Broker | `X-Service-Name: <caller>`, `X-Service-Token`, and `X-Gateway-Delegation` or `X-Gateway-Chat-Capability` when the route needs actor authority | Caller: `BROKER_GRPC_URL`, `BROKER_SERVICE_TOKEN`. Broker: `BROKER_SERVICE_TOKENS` |
| Gateway to Broker | `X-Service-Name: gateway`, `X-Service-Token`, `X-Gateway-Assertion`, optional `X-Gateway-Delegation` or `X-Gateway-Chat-Capability`, `X-Broker-Target`, optional pin headers | Gateway: `GATEWAY_BROKER_URL`, `GATEWAY_BROKER_TOKEN`. Broker: `BROKER_GATEWAY_TOKEN` |
| Broker to receiver | `X-Service-Name: message-broker`, `X-Service-Token: <receiver hop token>`, `X-Gateway-Assertion`, and the optional grant header | Broker: `BROKER_RECEIVERS`. Receiver: `BROKER_HOP_TOKEN` |

The Broker reads this configuration:

| Setting | Value |
| --- | --- |
| `BROKER_ADDRESS` | Listen address, default `:8080`. |
| `BROKER_SIGNING_KEY_FILE` | RSA private key, at least 2048 bits. Compose mounts `.local/stack/broker-private.pem` at `/keys/broker-private.pem`. |
| `BROKER_KEY_ID` | `kid` of the Broker key, `broker-v1`. |
| `BROKER_GATEWAY_PUBLIC_KEY_FILE` | Gateway's public key, `/keys/gateway-public.pem`. It verifies Gateway assertions on dispatch and Gateway-issued delegation and chat grants on exchange. |
| `BROKER_GATEWAY_KEY_ID` | `gateway-v1`. |
| `BROKER_SERVICE_TOKENS` | JSON map of caller name to inbound token. It replaces `GATEWAY_SERVICE_TOKENS` with the same names and values. |
| `BROKER_CALLER_NAMES` | JSON map of owner to its caller name. It replaces `GATEWAY_CALLER_NAMES`. |
| `BROKER_RECEIVERS` | JSON map of owner to `{Target, Audience, HopToken}`. It replaces `GATEWAY_RECEIVERS`. Setup generates new hop tokens. |
| `BROKER_GATEWAY_TOKEN` | Inbound token for Gateway, at least 32 bytes, distinct from every other token. |
| `BROKER_SERVICE_MAX_CONCURRENT_TASKS` | Service ingress capacity, default `100`. |
| `BROKER_GATEWAY_MAX_CONCURRENT_TASKS` | Gateway dispatch capacity, default `100`. |

The Broker also reads the [registration and control-plane settings](resilience.md#configuration), with `SERVICE_NAME=message-broker` and `CONTROL_PLANE_NAME=message-broker`. Its `CONTROL_PLANE_TOKENS` contains `discovery`, `operator`, and `gateway`. `OUTBOUND_TASK_TIMEOUT_SECONDS` sets `T`. The Broker does not verify Player bearer tokens and needs no Player key.

`scripts/setup.py` generates `.local/stack/broker-private.pem` and `.local/stack/broker-public.pem` beside the Gateway and Player pairs. Every token is a separate random value of at least 32 bytes. No token is reused across hops.

## Assertions

The token format stays gateway-identity v1. The header names, the `typ` values, the claims, the bound request fields (`method`, `path`, `query_sha256`, `body_sha256`, `idempotency_sha256`), and the 30-second lifetime do not change. Delegation and chat grants keep `aud=student-id-gateway`. Only the issuer and the key change for tokens that the Broker signs.

| Issuer | Key | Signs | `azp` |
| --- | --- | --- | --- |
| Gateway, `iss=student-id-gateway` | `gateway-v1` | Public request assertions, anonymous assertions, the delegations that public delivery attaches, chat capabilities, and Gateway's own Session context reads | `gateway` on assertions. The receiving caller on delegations and chat grants. |
| Broker, `iss=student-id-broker` | `broker-v1` | Exchanged request assertions, workload assertions, narrowed delegations, receiver delegations, and the Broker's own policy reads | The authenticated caller on assertions. `message-broker` on the Broker's own reads. The receiving caller on delegations. |

Receivers apply these rules:

1. Accept the hop only with `X-Service-Name: message-broker` and the receiver's `BROKER_HOP_TOKEN`. Reject `X-Service-Name: gateway`. Gateway no longer reaches receivers.
2. Pin both public keys by `kid`. A token verifies only when its `iss` matches its key: `gateway-v1` with `student-id-gateway`, and `broker-v1` with `student-id-broker`.
3. An assertion with `azp=gateway` must come from Gateway. An assertion with any other `azp`, and every workload assertion, must come from the Broker. Public routes therefore verify with Gateway's key, and internal routes verify with the Broker's key.
4. A delegation that arrives with an assertion has the same issuer as that assertion.
5. Session's context route `GET /internal/v1/sessions/{session_id}/context` accepts `azp=message-broker` in addition to its current callers and `gateway`.

Receivers keep their caller allowlists, actor checks, and business authorization.

The Broker verifies two issuers. It verifies Gateway assertions on dispatch. On exchange, it verifies delegations from both issuers and chat capabilities from Gateway. It signs only as `student-id-broker`.

## Service ingress

The Broker runs the checks that Gateway's internal listener ran, in the same order:

1. Reject an ambiguous path or duplicated private header with `400 INVALID_REQUEST`. Reject `Upgrade` with `400 UPGRADE_NOT_SUPPORTED`.
2. Match the route. Return `404 NOT_FOUND`, or `405 METHOD_NOT_ALLOWED` with `Allow`.
3. Reject `Authorization`, `X-Gateway-Assertion`, `X-Broker-Target`, and the pin headers with `401 UNAUTHORIZED`.
4. Authenticate the caller and apply the route's caller allowlist.
5. Apply the route policy. `Delegated` exchanges the presented grant after scope containment and the delegated policy, including its Session context reads. `Workload` applies the exact-request workload policy and rejects actor headers. The snapshot read selects workload policy from its query, never by retrying after an actor failure.
6. Add the receiver grant. Permission-context and snapshot dispatches receive an exact receiver delegation. Other delegated routes receive a narrowed delegation.
7. Select an instance, strip private headers, set the hop credential and `X-Request-ID`, and send one attempt.
8. Check the response. Refuse redirects other than `304`, `Content-Encoding`, `text/event-stream`, `101`, bodies over 8 MiB, and any response body or header that contains a forwarded grant, a hop token, or a `gateway-*` token. Refusal returns `502 INVALID_DEPENDENCY_RESPONSE`.

Request bodies are limited to 1 MiB. The Broker forwards the exact body and `Idempotency-Key` it signed.

## Gateway dispatch

Gateway sends the request path, query, body, and `Idempotency-Key` unchanged with these headers:

| Header | Meaning |
| --- | --- |
| `X-Broker-Target` | Required owner registry name: `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation`, or `discord-dms`. |
| `X-Broker-Target-Instance-Id` | Optional pin, the selected instance. Gateway sends it only for DMs ticket issuance. |
| `X-Broker-Target-Registration-Id` | Required with the pin, that instance's generation. |

The Broker checks the target and verifies `X-Gateway-Assertion` with Gateway's key, `azp=gateway`, and the target's configured audience against the exact request. It caps the attempt at the assertion's `exp`. It forwards the assertion and any delegation or chat grant unchanged, sets its own hop credential, and applies the response checks above. It forwards `Cookie` only to `player`. It applies no route table and no policy to this traffic.

A Gateway dispatch error keeps the public status mapping: `504 DEPENDENCY_TIMEOUT` for a timeout and `502 DEPENDENCY_UNAVAILABLE` for a connection failure. Service ingress returns `503` for both. Public responses therefore do not change.

## Selection and breaker

The Broker owns the rules that Gateway applied to backend attempts:

- The Broker selects only ready, leased instances from a current snapshot, minus its local breaker exclusions. Each owner has one round-robin cursor over instance IDs in lexical order. With IDs A and B, selections are A, B, A, B. After a membership change, the next selection is the first surviving ID greater than the last selected ID, with wraparound. The cursor advances for each dispatch and for each policy read, not for a rejection before dispatch.
- The Broker selects once for each physical attempt and keeps that instance's identity through signing, sending, body consumption, logging, and failure reporting. No request header chooses an instance on service ingress. A pin applies only to Gateway dispatch.
- Each backend generation has a counter in the Broker. Three distinct qualifying attempts within `W = 3.5 * T`, 7 seconds by default, trip the breaker. Qualifying failures are those in [bounded calls and failure accounting](resilience.md#bounded-calls-and-failure-accounting).
- At the third failure, the Broker excludes that generation locally, logs `circuit_open`, and reports `reason: "circuit_open"` with the three attempt IDs to Discovery. It keeps the exclusion and retries the same `operation_id` until Discovery accepts or rejects the report as stale.
- The Broker never removes a caller. A backend failure never counts against the Broker or against Gateway.

When no eligible instance exists, the Broker returns `503 NO_HEALTHY_INSTANCES` with `Retry-After: 1` and dials nothing. Dispatched calls finish within their original bounds. Removal does not cancel committed effects or replay in-flight requests. It never falls back from a pinned instance to another instance, because the ticket and its WebSocket address must name one replica.

| Status and code | Cause | Attempt counted |
| --- | --- | --- |
| `400 UNKNOWN_TARGET` | `X-Broker-Target` is missing or not an owner name | No |
| `400 INVALID_REQUEST` | Only one pin header is present | No |
| `401 UNAUTHORIZED` | The caller or Gateway assertion failed verification | No |
| `503 NO_HEALTHY_INSTANCES` | The owner has no eligible instance | No |
| `503 PINNED_INSTANCE_UNAVAILABLE` | The pinned generation is unknown, not ready, removed, or excluded by the breaker | No |
| `503 QUEUE_FULL` | The owner's [targeted queue](queues.md#targeted-queues) is full | No |
| `503 QUEUE_TIMEOUT` | The budget ran out while the request waited in the queue | No |

All `503` responses carry `Retry-After: 1`.

## Responses and hop accounting

On every response to an authenticated caller, including Gateway, the Broker removes backend-supplied `X-Broker-*` headers and sets these headers:

| Header | Meaning |
| --- | --- |
| `X-Broker-Instance-Id` | The Broker's instance ID. |
| `X-Broker-Registration-Id` | Its current registration generation. |
| `X-Broker-Failure-Origin` | `backend`, `broker`, or `none`. |
| `X-Broker-Backend-Instance-Id` | Only for `backend`, the instance of the failed attempt. |
| `X-Broker-Backend-Registration-Id` | Only for `backend`, that attempt's generation. |
| `X-Broker-Backend-Attempt-Id` | Only for `backend`, the attempt ID that the Broker recorded. |

`backend` means that a qualifying backend failure caused this response, including a failed policy read. `broker` means that the Broker failed itself, through admission rejection, task expiry after dispatch without a recorded backend failure, or an internal error. `none` covers success, `4xx`, policy rejection, `NO_HEALTHY_INSTANCES`, `PINNED_INSTANCE_UNAVAILABLE`, `QUEUE_FULL`, and `QUEUE_TIMEOUT`. These headers replace the `X-Gateway-*` attribution headers. They grant no authority, reach only authenticated callers, and never appear on public responses. Public error bodies keep their safe shape and contain no internal addresses.

Each caller, including Gateway, keeps one hop counter for the Broker generation. The caller finds that generation in the registry under `message-broker` with an `http_url` equal to its configured Broker URL. An unknown, removed, stale, or ambiguous generation blocks new dispatch with `503 DEPENDENCY_UNAVAILABLE`. The caller counts only a connection error or timeout of its Broker hop, or a qualifying status with `X-Broker-Failure-Origin: broker`. It does not count `backend` or `none`. Missing or inconsistent attribution fails the call closed, logs a diagnostic, and adds no failure. A Broker hop with no response counts against the Broker even if the Broker also recorded a backend timeout. Those are two physical attempts, not one attempt reported twice.

## Admission and time budget

The Broker authenticates the caller from headers before admission. An unauthenticated request receives `401` without a slot. Service ingress and Gateway dispatch then use separate gates. Each gate rejects immediately with `503 TASK_LIMIT_EXCEEDED` and `Retry-After: 1` when it is full. Neither gate queues. An admitted request then waits in its destination's [targeted queue](queues.md#targeted-queues).

The two gates prevent self-deadlock. A public request holds Gateway capacity while its Broker dispatch reaches a receiver. That receiver's own peer calls enter service ingress, so saturated public traffic cannot reject them. Gateway's policy reads are separate, sequential Gateway dispatches. The Broker's own policy reads run inside the admitted task. They never call the Broker's HTTP listener and take no slot.

The Broker finishes each task within `T - 250 ms` of receipt, 1.75 seconds by default. This budget covers policy reads, queue wait, and the one dispatch attempt. Each attempt's deadline is the minimum of the remaining budget and the signed authority expiry. The margin lets an attributed response reach a caller whose hop deadline is `T` before that caller times out. A Broker-side attempt timeout is a backend `timeout`. The configured counter window stays `3.5 * T`.

Status reports `active_tasks` and `max_concurrent_tasks` as the sums over both gates. No layer replays a write.

Each admitted business request, whether service ingress, Gateway dispatch, or a topic publish, runs on its own operating-system thread for its whole lifetime. The gate's worker goroutine calls `runtime.LockOSThread()` before any other work and never unlocks it. When the request finishes by success, error, timeout, cancellation, or a recovered panic, that goroutine exits while locked, and the Go runtime terminates the thread instead of reusing it. A request keeps its gate slot until its thread ends, so concurrent request threads never exceed the sum of both gate capacities, 200 by default. A full gate answers `503 TASK_LIMIT_EXCEEDED` without starting a thread. Authentication, rejections, status, health, logs, the topic listing, delivery workers, and subscription derivation run on ordinary goroutines. Each `dispatch` record and the `http_request` record of an admitted request carry `thread_id`, the operating-system thread ID.

## Logging

The Broker writes the [logging contract](logging.md) records. It writes one `dispatch` record at `INFO` for each business attempt. The record has `request_id`, `caller`, `target_service`, `target_instance_id`, `registration_id`, `attempt_id`, `method`, `route`, `status`, `outcome`, and `duration_ms`, plus `error_kind` on failure. `caller` is the authenticated name, or `gateway`. On service ingress, `route` is the matched internal template. On Gateway dispatch, `route` is the path with every UUID segment replaced by `{id}`.

Policy reads are `dependency_call` records. A failed read is `WARN`, and a successful read is `DEBUG`. Breaker trips are `circuit_open` at `INFO` with `T`, `W`, the three attempt IDs, and the removal outcome. Gateway no longer writes `dispatch` records. It logs its Broker hop as `dependency_call` with `target_service: message-broker`.

## Gateway after the move

Gateway keeps these responsibilities:

- The public listener, the public route table, Player bearer verification, the public policy and its Session participation checks, and ingress limits.
- Public signing: request and anonymous assertions, delivery delegations, and chat capabilities, signed with `gateway-v1`.
- Realtime negotiation. Gateway selects a ready DMs instance from its own registry snapshot, then sends ticket issuance to the Broker with that instance pinned. It builds the WebSocket URL from that instance's `ws_url`. If the Broker returns `PINNED_INSTANCE_UNAVAILABLE`, Gateway returns `503 NO_HEALTHY_INSTANCES` and does not try another instance.
- Its own Session context reads, sent as Gateway dispatch to target `session`.
- Registration as `gateway`, status, the log export, and the administrator log download, which adds `message-broker` to its allowed services.
- A hop counter toward the Broker generation, with the Discovery bootstrap breaker.

Gateway strips every client-supplied `X-Broker-*` header with the other private headers. It removes `X-Broker-*` from every public response.

Gateway keeps one data table from the internal routes: the method, path pattern, target, and callers of each `Delegated` route. It uses that table only to bound the delegations it signs for public delivery, and it changes in the same release as the Broker's route table. It keeps no internal policy logic.

Gateway deletes the rest of the internal route table, service caller authentication, the delegated and workload policy, exchange and narrowing, per-backend round-robin and breakers for domain owners, and the backend response checks that the Broker now runs. It also deletes the `GATEWAY_<SERVICE>_URL` targets, `GATEWAY_SERVICE_TOKENS`, and the hop tokens in `GATEWAY_RECEIVERS`. `GATEWAY_RECEIVERS` keeps each owner's `Target` and `Audience`. Gateway needs them to bind public assertions.

The `:8083` listener serves only `/healthz`, `/internal/v1/status`, and `/internal/v1/logs`. After the [gRPC rollout](grpc.md#gateway-routes), it serves only `/healthz`. Every other request returns `404 NOT_FOUND` before admission, with no attribution headers and no forwarding. A caller still configured for Gateway receives that `404`, so its call fails without a breaker failure. The public listener still rejects service credentials with `401 UNAUTHORIZED` and `/internal/v1/*` with `404 NOT_FOUND`.

## Repository changes

Each repository changes only its own code and tests. A change is "config only" when no source changes.

| Repository | Change | Work |
| --- | --- | --- |
| Message Broker | Code | Take the moved Gateway code. Add the two modes, two gates, two issuers, attribution, the `dispatch` log, and registration as `message-broker`. |
| Gateway | Code | Delete the moved code. Add Gateway dispatch, the DMs pin, Broker hop accounting, the `X-Broker-*` stripping, and the control-only `:8083` listener. |
| Discovery | Code | Add `message-broker` to the registry names in `cmd/discovery/server.go`. Probes and removals need no other change. |
| Player | Code | Receiver rules 1 to 4. Player has no business caller. |
| Session | Code | Receiver rules 1 to 5. Its caller uses `BROKER_GRPC_URL` and `BROKER_SERVICE_TOKEN`, looks up `message-broker` in `app/breaker.py` and `app/discovery.py`, and reads `X-Broker-*`. |
| Applicant | Code | Receiver rules 1 to 4 in `GatewayProofVerifier`, with `BROKER_JWKS_JSON` beside `GATEWAY_JWKS_JSON`. The `GatewayHopBreaker` caller moves to the Broker hop. |
| Credential | Code | Receiver rules 1 to 4 in `GatewayProofVerifier`, with `BROKER_JWKS_JSON`. The `PeerHttpClient` and `GatewayHopBreaker` caller moves to the Broker hop. |
| Server Rules | Code | Receiver rules 1 to 4 in `GatewayAccess`. The caller in `GatewayDirectory`, `DiscoveryRegistration`, and `HttpSessionGateway` moves to the Broker hop. |
| University Record | Code | Receiver rules 1 to 4 in `GatewayAuthorizationFilter`. The caller in `GatewayHopBreaker` and `HttpSessionContextTransport` moves to the Broker hop. |
| Moderation | Code | Receiver rules 1 to 4 in `gateway_identity.py`. The caller in `gateway_breaker.py` and `discovery.py` moves to the Broker hop. |
| Discord DMs | Code | Receiver rules 1 to 4 in `gateway_identity.py`. The caller in `gateway_breaker.py` moves to the Broker hop. Chat capabilities stay Gateway-issued and are exchanged at the Broker. |

Receivers that load a PEM key read `BROKER_PUBLIC_KEY_FILE=/keys/broker-public.pem`. Every receiver reads `BROKER_KEY_ID=broker-v1` and `BROKER_ASSERTION_ISSUER=student-id-broker`, and keeps its Gateway key settings. Each removes its Gateway hop token setting. Every caller replaces its Gateway URL and caller token settings with `BROKER_URL=http://message-broker:8080` and `BROKER_SERVICE_TOKEN`. CPR adds the key pair and tokens to `scripts/setup.py`, the `message-broker` service to `compose.yaml`, and the Broker image to the release record.

## Verification

Each repository tests its own side. Receivers test both issuers, a token whose `iss` does not match its key, the hop name, and a rejected Gateway hop. Callers test attribution for `backend`, `broker`, and `none`, and missing headers. The Broker reuses Gateway's routing, identity, policy, and breaker tests, and adds tests for both modes, both gates, the pin errors, and attribution.

The released stack passes these checks with real services and no mocks:

- At least two services communicate through the Broker, and every call path in the internal route table goes through it. Gateway's `:8083` listener answers business paths with `404`.
- Public flows, including realtime negotiation and direct chat, still work.
- `docker compose up --scale applicant=4` registers distinct instances, and Broker `dispatch` records show round-robin across them.
- Three failures from one instance within `W` exclude it, and Discovery records `circuit_open`. A healthy instance serves the next requests, and no caller or Broker is removed.
