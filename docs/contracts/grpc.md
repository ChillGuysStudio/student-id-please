# Service-to-service gRPC contract

This contract moves every service-to-service call to gRPC. It covers peer operations, topic publish and push delivery, Discovery control, status probes, log export, the Broker topic listing, and Gateway's own Session context reads. Client requests stay REST end to end: client, Gateway, Broker, owning service. The canonical definitions are the `.proto` files under [`proto/`](../../proto/student_id).

The other contracts keep their rules. The [Message Broker contract](broker.md) still defines authorization, selection, breakers, and attribution. The [queues and topics contract](queues.md) still defines targeted queues, topics, and delivery state. The [discovery and resilience contract](resilience.md) still defines leases, removal, and failure accounting. The [HTTP contract](http.md) still defines idempotency and error codes. This contract changes their transport. Where it names a REST endpoint, that endpoint is the one it replaces.

## Scope

These calls move to gRPC:

- The 21 internal routes of the Broker's `InternalRoutes()`. They become 18 RPC methods and 22 policy rows. The case start and case status methods have one row per owner, and the snapshot read splits into an actor-bound RPC and a retained RPC.
- Topic publish from producers to the Broker, and push delivery from the Broker to subscribers.
- Discovery registration and renewal with topics, lookup, removal, and reactivation.
- Discovery's status probes of every instance, and the bootstrap probe of Discovery itself.
- Gateway's log collection from every process, including Discovery and the Broker.
- Gateway's topic listing call to the Broker, and Gateway's own Session context reads.

These stay HTTP:

- Client REST through Gateway, Gateway dispatch to the Broker with `X-Broker-Target`, and the Broker's targeted-queue dispatch of that request to the owning service.
- `/healthz`, `/health`, and `/ready` for Docker healthchecks, and Gateway's public administrator routes.
- Direct Discord DMs WebSockets and database connections.

No RPC carries an HTTP request, path, or header set. Every RPC has typed request and response messages.

## Protos and generation

### Layout

Each area has one package, `student_id.<area>.v1`, in `proto/student_id/<area>/v1/<area>.proto`.

| Package | Service | Served by |
| --- | --- | --- |
| `student_id.common.v1` | None. `ErrorDetail` | All |
| `student_id.domain.v1` | None. Shared case evidence from [domain.md](domain.md) | All |
| `student_id.control.v1` | `ControlService` | Every process |
| `student_id.discovery.v1` | `DiscoveryService` | Discovery |
| `student_id.broker.v1` | `BrokerService` | Message Broker |
| `student_id.events.v1` | `EventConsumerService` and `EventEnvelope` | Applicant, Credential, University Record, Session, Player |
| `student_id.player.v1` | `PlayerService` | Player |
| `student_id.session.v1` | `SessionService` | Session |
| `student_id.cases.v1` | `CaseOwnerService` | Applicant, Credential, University Record |
| `student_id.applicant.v1` | `ApplicantService` | Applicant |
| `student_id.credential.v1` | `CredentialService` | Credential |
| `student_id.rules.v1` | `RulesService` | Server Rules |
| `student_id.university_record.v1` | `UniversityRecordService` | University Record |

Moderation, Discord DMs, and Gateway serve only `ControlService`.

### Message conventions

- Field names are the JSON field names, in `snake_case`.
- IDs are canonical lowercase UUID strings. Receivers validate them as they validate JSON IDs today.
- `Time` is `google.protobuf.Timestamp`. `Int` is `int32`. Epoch seconds are `int64`.
- A required field that can be `null` is `optional` for scalars and a message field for messages. Unset means `null`.
- Enumerated values are strings with the wire values of [domain.md](domain.md). Receivers reject unknown values. Proto enums would change the wire values and the JSON mapping.
- A union selected by `kind` is a `oneof` named after the JSON field, `data` or `condition`. The message keeps `kind`, and the set case must match it.
- Proto3 cannot tell an empty string from a missing one. A required string that is empty is invalid.
- Unknown fields carry no meaning. Receivers never read them.
- No message uses `map` fields, and no call uses gRPC compression.

### Toolchain

`proto/buf.yaml` defines the module, its lint rules, and its one dependency, `buf.build/googleapis/googleapis`, pinned in `proto/buf.lock`. No file imports it yet. It is there so that `google/api/annotations.proto` needs no tooling change later. `proto/buf.gen.yaml` is the reference template. It pins these plugins:

| Language | Plugins | Runtime dependencies |
| --- | --- | --- |
| Go | `buf.build/protocolbuffers/go:v1.36.5`, `buf.build/grpc/go:v1.5.1` | `google.golang.org/protobuf v1.36.5`, `google.golang.org/grpc v1.70.0` |
| Java | `buf.build/protocolbuffers/java:v29.3`, `buf.build/grpc/java:v1.70.0` with `@generated=omit` | `com.google.protobuf:protobuf-java:4.29.3`, `io.grpc:grpc-protobuf`, `grpc-stub`, and `grpc-netty-shaded` `1.70.0` |
| Python | `buf.build/protocolbuffers/python:v29.3`, `buf.build/protocolbuffers/pyi:v29.3`, `buf.build/grpc/python:v1.70.0` | `protobuf==5.29.3`, `grpcio==1.70.0`, `grpcio-status==1.70.0` |

Run buf from the `bufbuild/buf:1.50.0` image:

```sh
cd proto
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/workspace" -w /workspace bufbuild/buf:1.50.0 lint
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/workspace" -w /workspace bufbuild/buf:1.50.0 generate
```

`buf generate` writes `proto/gen/`, which CPR does not commit. The reference output compiles with `go build ./...` and `go vet ./...`, with `mvn compile` on JDK 21, and imports on Python 3.12 with the runtime versions above. The template does not generate googleapis files. Go, Java, and Python get `google.rpc.Status` from `google.golang.org/genproto`, `proto-google-common-protos`, and `googleapis-common-protos`, which the gRPC runtimes already depend on.

### Vendoring

Each implementing repository copies every `.proto` file, `buf.yaml`, and `buf.lock` from CPR's `proto/` into its own `proto/`, with the same paths and no changes. A repository never edits the copy. A contract change starts in CPR.

The repository records the source in `proto/SOURCE`:

```text
revision=<CPR commit SHA>
sha256=<tree digest>
```

The tree digest is the output of this command from the repository root:

```sh
find proto -type f \( -name '*.proto' -o -name 'buf.yaml' -o -name 'buf.lock' \) | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1
```

Each repository keeps its own `buf.gen.yaml` outside `proto/`, with the plugin lines for its language from the reference template and its own output directory. It commits the generated code:

- **Go.** Enable managed mode with `go_package_prefix` set to a package of the repository's own module, for example `github.com/ChillGuysStudio/message-broker-service/internal/gen`. Disable `go_package` for `buf.build/googleapis/googleapis`.
- **Java.** Generate into a directory that `build-helper-maven-plugin` adds as a source root, for example `src/main/generated`. The Java packages are `com.chillguysstudio.studentid.<area>.v1`.
- **Python.** Generate into a directory on the import path. The generated modules import each other as the top-level package `student_id`.

Each repository's CI runs three checks:

1. Recompute the tree digest and compare it with `proto/SOURCE`.
2. Run `buf lint` on `proto/`.
3. Run `buf generate` with the repository's template, then `git diff --exit-code` on the generated directory.

CPR's integration check reads `proto/SOURCE` in every service pointer that has one. It confirms that the revision is a CPR commit and that the digest matches the tree at that commit. At grade acceptance, every pointer records the same revision.

## Topology and ports

Every process serves one plaintext gRPC listener over HTTP/2. The listener does not use TLS, which matches the private HTTP listeners. It registers no reflection service and no gRPC health service.

| Setting | Owner and value |
| --- | --- |
| `GRPC_ADDRESS` | Every process. Listen address, default `:50051`. |
| `INSTANCE_GRPC_URL` | Every registrant. Optional. By default the process advertises `http://<its container address>:<its gRPC port>`. The Broker advertises `http://message-broker:50051`. |
| `BROKER_GRPC_URL` | Every Broker caller, including Gateway. `http://message-broker:50051`. |
| `DISCOVERY_GRPC_URL` | Every registrant and registry reader. `http://discovery:50051`. |

A gRPC URL is an origin with scheme `http`, a concrete host, and a port, under the [origin rules](resilience.md#configuration). A caller dials `<host>:<port>` without DNS load balancing. The `http` scheme means plaintext gRPC. `https` is reserved for TLS.

| Process | gRPC services | HTTP that stays |
| --- | --- | --- |
| Gateway | `ControlService` | Public listener `:8080`. Control listener `:8083` with `/healthz` only. |
| Message Broker | `BrokerService`, `ControlService`, and forwarding of every other method | `:8080` for Gateway dispatch and `/health` |
| Discovery | `DiscoveryService`, `ControlService` | `/healthz` |
| Player, Session | Their service, `EventConsumerService`, `ControlService` | Public routes, `/health`, `/ready` |
| Applicant, Credential | Their service, `CaseOwnerService`, `EventConsumerService`, `ControlService` | Public routes, `/health`, `/ready` |
| University Record | `UniversityRecordService`, `CaseOwnerService`, `EventConsumerService`, `ControlService` | Public routes, `/healthz` |
| Server Rules | `RulesService`, `ControlService` | Public routes, `/healthz` |
| Moderation, Discord DMs | `ControlService` | Public routes, `/healthz`, the DMs WebSocket |

The Moderation publisher has no listener. It publishes with `BrokerService.PublishEvent`, and Moderation exports its logs.

### Address discovery

`Registration` gains `grpc_url`, and `Instance` returns it. Discovery validates it like `http_url`. It must differ from the instance's `http_url`. A changed `grpc_url` within one boot returns `409 REGISTRATION_CONFLICT`, like a changed address. A live `grpc_url` that another instance ID already uses also returns `409`. Removal records store it with the other addresses.

The registry is the only source of replica gRPC addresses. The Broker dials the selected instance's `grpc_url` for RPC dispatch and delivery. It dials the `http_url` for Gateway dispatch. Discovery probes `grpc_url`. Gateway reads `grpc_url` for log collection. A caller finds the Broker generation for hop accounting under `message-broker` with a `grpc_url` equal to `BROKER_GRPC_URL`. Gateway uses the same generation for its REST hop, so it keeps one hop counter for the Broker.

## Metadata

Metadata keys are lowercase. Each key that a receiver reads appears at most once. A repeated key returns `INVALID_ARGUMENT` with code `INVALID_REQUEST`.

| Key | Sent by | Meaning |
| --- | --- | --- |
| `x-service-name`, `x-service-token` | A domain caller or Gateway to the Broker | Business caller credential: `BROKER_SERVICE_TOKEN`, or `GATEWAY_BROKER_TOKEN` for Gateway. |
| `x-service-name: message-broker`, `x-service-token` | The Broker to a receiver | Hop credential: the receiver's `BROKER_HOP_TOKEN`. |
| `x-broker-target` | A caller to the Broker | Owner registry name. Required on every forwarded RPC. Absent on `BrokerService`. |
| `x-gateway-assertion` | The Broker to a receiver. Gateway to the Broker on its own reads. | Receiver assertion, bound as [the binding](#assertion-binding) defines. |
| `x-gateway-delegation` or `x-gateway-chat-capability` | A caller to the Broker, and the Broker to a receiver | Actor grant, unchanged gateway-identity v1 tokens. |
| `x-request-id` | Every caller | Request UUID for correlation. Receivers keep a valid one. |
| `idempotency-key` | Every caller of an RPC that requires one | The business idempotency key, which the [RPC inventory](#rpc-inventory) lists per RPC. |
| `x-control-name`, `x-control-token` | Control callers | Control credential from `CONTROL_PLANE_TOKENS`. |

The keys `x-broker-target-instance-id` and `x-broker-target-registration-id` are reserved for a pinned Gateway RPC. Gateway's DMs ticket pin stays an HTTP header in this version. A caller that sends `authorization`, `x-gateway-assertion` (unless the caller is Gateway), or a reserved pin key to the Broker receives `UNAUTHENTICATED`. A receiver rejects `authorization` in the same way.

On every response to an authenticated caller, the Broker removes backend `x-broker-*` metadata and sets the [attribution values](broker.md#responses-and-hop-accounting) as trailers: `x-broker-instance-id`, `x-broker-registration-id`, `x-broker-failure-origin`, and for `backend` also `x-broker-backend-instance-id`, `x-broker-backend-registration-id`, and `x-broker-backend-attempt-id`. Missing or inconsistent trailers fail the call closed, as missing headers do today.

### One interceptor per language

Each repository puts the receiver checks in one server interceptor. Handlers never read credentials themselves. The interceptor runs these checks in order:

1. Reject repeated keys and `authorization`.
2. For a business RPC, require `x-service-name: message-broker` and the receiver's `BROKER_HOP_TOKEN`. For a control RPC, authenticate `x-control-name` and `x-control-token` and apply the RPC's caller list.
3. Verify `x-gateway-assertion` and any grant by the [receiver rules](broker.md#assertions) and the binding below. The audience is the receiver's own.
4. Adopt `x-request-id`, or generate one.
5. Expose the verified caller (`azp`), actor, and grant to the handler.

The same interceptor maps handler errors to the [status mapping](#status-mapping). Each caller uses one client interceptor that sets the caller credential, `x-request-id`, and the deadline, and reads the attribution trailers for hop accounting.

## Assertion binding

The token format stays gateway-identity v1. A gRPC call is an HTTP/2 `POST` to `/<package>.<Service>/<Method>`, so the request claims bind it like this:

| Claim | Value for an RPC |
| --- | --- |
| `method` | `POST` |
| `path` | The full method name, for example `/student_id.session.v1.SessionService/GetSessionContext` |
| `query_sha256` | SHA-256 of the empty string |
| `body_sha256` | SHA-256 of the serialized request message: the exact bytes of the gRPC message payload, without the 5-byte length prefix |
| `idempotency_sha256` | SHA-256 of the `idempotency-key` value, or of the empty string when it is absent |

The signer hashes the bytes it forwards, and the receiver hashes the bytes it received before it decodes them. Nothing re-serializes a message in between.

- The Broker forwards raw frames, so it hashes the frame that it received from the caller and sends that same frame.
- Gateway signs its own Session context reads. It marshals the request once and sends those bytes with a pass-through codec.
- Java receivers wrap each service definition with `ServerInterceptors.useMarshalledMessages` and a byte-array marshaller, so the interceptor sees the raw bytes before the stub parses them.
- Python receivers wrap each method handler. The wrapper's `request_deserializer` returns the raw bytes with the parsed message, and the wrapped behavior verifies the hash, then calls the original behavior.

### Resources for scopes

Delegation scopes keep their format, and Gateway's `DelegatedRoutes()` keeps its REST patterns. Each RPC has a resource: the method, path, and query of the REST route it replaces, with placeholders filled from request fields. The [RPC inventory](#rpc-inventory) lists every resource. The Broker evaluates scope containment, narrowing, and its delegated and workload policy against the resource instead of the HTTP request. Policy code that read a JSON body field reads the same field from the decoded request. A scope `body_sha256` constrains the request message bytes. A resource is a name for authorization, not a request that anything sends.

## Status mapping

Every non-OK status that a process returns carries a `google.rpc.Status` with exactly one detail, a `student_id.common.v1.ErrorDetail`. The detail holds the existing error `code`, `message`, `request_id`, field `details`, the HTTP status of the same failure in `http_status`, and `Retry-After` in `retry_after_seconds`. The gRPC status message equals the detail's `message`.

| HTTP status | gRPC code |
| --- | --- |
| `400` | `INVALID_ARGUMENT` |
| `401` | `UNAUTHENTICATED` |
| `403` | `PERMISSION_DENIED` |
| `404` | `NOT_FOUND` |
| `405` | `UNIMPLEMENTED` |
| `409` | `ABORTED` |
| `413`, `429` | `RESOURCE_EXHAUSTED` |
| `422` | `INVALID_ARGUMENT` |
| `425` and any other `4xx` | `FAILED_PRECONDITION` |
| `500` and any other `5xx` | `INTERNAL` |
| `502` | `UNKNOWN` |
| `503` | `UNAVAILABLE` |
| `504` | `DEADLINE_EXCEEDED` |

The detail keeps 400 apart from 422. Every rule that depended on an HTTP status reads `http_status`. For example, a consumer rejects a delivery with `http_status` 409 or 422, and a caller retries `503` after `retry_after_seconds`. A success that returned 200, 201, or 202 returns `OK`. Where the difference mattered, the response says it in a field: `RegisterInstanceResponse.created` and `PublishEventResponse.duplicate`.

A caller classifies each attempt for its breaker as [bounded calls](resilience.md#bounded-calls-and-failure-accounting) require:

- `UNAVAILABLE` without an `ErrorDetail` is `connection_error`.
- `DEADLINE_EXCEEDED` from the caller's own deadline is `timeout`.
- A status with an `ErrorDetail` and `http_status` from 500 to 599 is `http_5xx` with that `status_code`.
- `INTERNAL`, `UNKNOWN`, or `DATA_LOSS` without an `ErrorDetail` is `http_5xx` with `status_code` 500.
- Every other status does not qualify. This includes `CANCELLED`, `UNIMPLEMENTED`, and a `RESOURCE_EXHAUSTED` from a message size limit.

Breaker reports keep their `Failure` shape. For a gRPC attempt, `method` is `POST` and `endpoint` is the full method name.

## Deadlines and cancellation

Every RPC carries a gRPC deadline. A caller sets it to the minimum of `T`, its remaining parent task budget, and the signed authority expiry.

The Broker's task budget ends at the earlier of `T - 250 ms` after receipt and 250 ms before the caller's deadline. The budget covers policy reads, queue wait, and the one attempt. Each attempt's deadline is the minimum of the remaining budget and the assertion's `exp`. A request still queued when the budget ends leaves with `UNAVAILABLE QUEUE_TIMEOUT`.

A receiver's task deadline is the earlier of its own inbound task limit and the incoming gRPC deadline. It passes the remaining time to every outbound call and store query that accepts one: Go `context.Context`, Java `Context.current().getDeadline()`, Python `context.time_remaining()`. When the caller cancels or its deadline passes, gRPC cancels the call at every hop. A cancellation by the upstream caller is not a qualifying failure. Cancellation does not prove rollback. A caller recovers an uncertain write only by retrying with its original `idempotency-key`. No layer replays a write.

Admission does not change. An admitted RPC holds its gate slot and runs on its own locked operating-system thread, as [the Broker contract](broker.md#admission-and-time-budget) defines. The Broker must not set `grpc.NumStreamWorkers`, so each stream's handler runs on its own goroutine.

## Broker forwarding

The Broker's gRPC server registers `BrokerService` and `ControlService` and handles every other method with `grpc.UnknownServiceHandler`. A pass-through codec reads and writes forwarded messages as raw frames and uses protobuf only for the Broker's own services. The Broker has no hand-written forwarding for any RPC. Forwarded RPCs are unary. A second request message, or a client-streaming call, returns `INVALID_ARGUMENT INVALID_REQUEST`.

The Broker handles a forwarded RPC in this order:

1. Reject repeated keys, `authorization`, and reserved keys.
2. Authenticate `x-service-name` and `x-service-token`. `gateway` selects Gateway mode. Any other configured caller selects service ingress. Failure returns `UNAUTHENTICATED` without a slot.
3. Take a slot on that mode's admission gate.
4. Look up the policy row for the full method name and `x-broker-target`. A missing or unknown target returns `INVALID_ARGUMENT UNKNOWN_TARGET`. No row returns `UNIMPLEMENTED` with code `NOT_FOUND` and `http_status` 404.
5. Read one request frame of at most 1 MiB.
6. In service ingress, apply the row's caller list, then its policy. A `delegated` or `workload` row decodes the frame with the row's request type to build the resource and its pins, then runs the existing policy, exchange, and narrowing against the resource. An `unagreed` row returns `UNAVAILABLE POLICY_UNAVAILABLE`. In Gateway mode, the row must allow Gateway. The Broker verifies Gateway's assertion against the frame and applies no policy.
7. Check the row's `idempotency-key` rule.
8. Sign the receiver assertion over the frame, or keep Gateway's assertion. Add the receiver grant.
9. Enqueue the request on the target's targeted queue. Select an instance with a `grpc_url` by the [round-robin and breaker rules](broker.md#selection-and-breaker). Send one attempt with the hop credential, the assertion, the grant, `x-request-id`, and `idempotency-key`. The Broker never forwards caller credentials or `x-broker-target`.
10. Check the response. Refuse a response frame over 8 MiB, and any response frame or metadata value that contains a forwarded grant, a hop token, or a `gateway-*` token, with `UNKNOWN INVALID_DEPENDENCY_RESPONSE`. Otherwise return the backend's frame, status, and details unchanged, with the attribution trailers.

The Broker's own policy reads are `SessionService.GetSessionContext` RPCs that the Broker signs as `message-broker`. They pass through Session's targeted queue and count in its breakers, as before.

### Policy table

The table replaces `InternalRoutes()`. Each row has these fields, and the pair of `rpc` and `target` is its key:

| Field | Meaning |
| --- | --- |
| `rpc` | Full method name. |
| `target` | Owner registry name. One RPC that several owners serve has one row per owner. |
| `callers` | Service callers that service ingress accepts. Empty for a row that only Gateway sends. |
| `gateway` | Whether Gateway mode accepts the RPC. |
| `policy` | `delegated`, `workload`, `unagreed`, or `none`. `none` is only for rows that only Gateway sends. |
| `request` | Generated request type that the Broker decodes for the resource and policy pins. Empty when the policy needs no field. |
| `resource` | Method, path template, and query template. Placeholders name request fields. |
| `idempotency` | `forbidden`, `required`, or `equals <field>`. |

The row shape already accepts a public RPC. A Gateway-only row has `callers` empty, `gateway` true, and `policy` `none`. Its `resource` is the public REST route.

## RPC inventory

Every forwarded RPC passes through the Broker. A dash means the RPC forbids `idempotency-key`.

| RPC | Target | Policy | Callers | `idempotency-key` | Resource |
| --- | --- | --- | --- | --- | --- |
| `PlayerService/GetPlayer` | `player` | `delegated` | `session`, `moderation` | - | `GET /internal/v1/players/{player_id}` |
| `PlayerService/GetTeam` | `player` | `delegated` | `session` | - | `GET /internal/v1/teams/{team_id}` |
| `SessionService/GetSessionContext` | `session` | `delegated`, and Gateway | `applicant`, `credential`, `rules`, `university_record`, `moderation`, `discord-dms` | - | `GET /internal/v1/sessions/{session_id}/context?player_id={player_id}` |
| `SessionService/GetAcceptedAttempt` | `session` | `workload` | `university_record`, `applicant`, `credential` | - | `GET /internal/v1/sessions/{session_id}/accepted-attempts/{attempt_id}` |
| `SessionService/GetCaseStatus` | `session` | `delegated` | `moderation`, `rules` | - | `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` |
| `CaseOwnerService/StartCase` | `applicant`, `credential`, `university_record` | `workload` | `session` | Equals `attempt_id` | `POST /internal/v1/<owner path>/cases` |
| `CaseOwnerService/GetCaseState` | `applicant`, `credential`, `university_record` | `workload` | `session` | - | `GET /internal/v1/<owner path>/cases/{case_id}/status` |
| `ApplicantService/GetApplicant` | `applicant` | `delegated` | `moderation` | - | `GET /internal/v1/applicants/{case_id}?session_id={session_id}` |
| `CredentialService/GetCredentialResults` | `credential` | `delegated` | `moderation` | - | `GET /internal/v1/cases/{case_id}/credential-results?session_id={session_id}` |
| `RulesService/GetCurrentRuleSet` | `rules` | `delegated` | `session` | - | `GET /internal/v1/rule-versions/current` |
| `RulesService/EvaluatePolicy` | `rules` | `delegated` | `moderation` | - | `POST /internal/v1/policy/evaluations` |
| `UniversityRecordService/CreateSnapshot` | `university_record` | `delegated` | `session` | Required, the `snapshot_start` attempt ID | `POST /internal/v1/university-snapshots` |
| `UniversityRecordService/GetSnapshot` | `university_record` | `delegated` | `applicant`, `credential`, `university_record`, `session` | - | `GET /internal/v1/university-snapshots/{snapshot_id}` |
| `UniversityRecordService/GetRetainedSnapshot` | `university_record` | `workload` | `applicant`, `credential`, `university_record` | - | `GET /internal/v1/university-snapshots/{snapshot_id}?session_id={session_id}&attempt_id={attempt_id}` |
| `UniversityRecordService/ReserveIdentity` | `university_record` | `workload` | `applicant`, `credential`, `university_record` | Equals `case_id` | `POST /internal/v1/university-identities/reservations` |
| `UniversityRecordService/GetIdentity` | `university_record` | `workload` | `applicant`, `credential`, `university_record` | - | `GET /internal/v1/university-identities/{subject_id}?case_id={case_id}&session_id={session_id}&attempt_id={attempt_id}` |
| `UniversityRecordService/GetRecordPermission` | `university_record` | `delegated` | `discord-dms`, `session` | - | `GET /internal/v1/sessions/{session_id}/record-permissions/{player_id}` |
| `UniversityRecordService/GetCaseRecords` | `university_record` | `delegated` | `moderation` | - | `GET /internal/v1/cases/{case_id}/university-records?session_id={session_id}` |

Method names omit the package prefix of the [layout table](#layout). `StartCase` and `GetCaseState` have one row per owner. The owner path is `applicant`, `credential`, or `university-record`. The split snapshot read replaces the query-based mode choice. Mode now follows the method name, so the Broker never selects a policy by retrying after a failure. Moderation's `EvaluatePolicy` no longer sends the decision key, because evaluation stores nothing.

These RPCs do not go through the forwarding table:

| RPC | Caller and credential | Destination |
| --- | --- | --- |
| `BrokerService/PublishEvent` | A topic producer, service credential | The Broker |
| `BrokerService/ListTopics` | `gateway` or `operator`, control credential | The Broker |
| `EventConsumerService/DeliverEvent` | The Broker, hop credential and workload assertion | The selected subscriber replica |
| `DiscoveryService/*` | Registrants, registry readers, `operator`, control credential | Discovery |
| `ControlService/GetStatus` | `discovery` or `operator`, control credential | Each instance directly |
| `ControlService/ExportLogs` | `gateway` or `operator`, control credential | Each instance directly |

## Events

### Publish

A relay calls `BrokerService.PublishEvent` with `topic` and the envelope. `EventEnvelope` has the fields of `Event<T>` in [events.md](events.md). Its payload is `payload_json`, the UTF-8 JSON object of the payload schema for that event type and schema version. Consumers own that schema, as before. The Broker reads only the envelope fields. Keeping the payload as JSON keeps stored rows, duplicate comparison, and each consumer's normalized payload unchanged across the rollout.

The Broker runs the [publish checks](queues.md#publish) in their order. Step 4 now requires UUID `event_id` and `correlation_id`, a set `occurred_at`, `payload_json` that parses as a JSON object, `event_type` equal to `topic`, the topic's `schema_version`, and `producer` equal to the caller's registry name. The request limit stays 1 MiB.

| Result | Meaning | Relay action |
| --- | --- | --- |
| `OK`, `duplicate` false | Committed now | Mark the outbox row confirmed |
| `OK`, `duplicate` true | Already committed with an equal envelope | Mark the outbox row confirmed |
| `INVALID_ARGUMENT INVALID_REQUEST` (400) | Repeated metadata | Keep the row, back off |
| `UNAUTHENTICATED UNAUTHORIZED` (401) | Caller authentication failed | Keep the row, back off |
| `PERMISSION_DENIED TOPIC_FORBIDDEN` (403) | The caller may not publish this topic | Keep the row, back off |
| `NOT_FOUND UNKNOWN_TOPIC` (404) | `topic` is not in the catalogue | Keep the row, back off |
| `ABORTED EVENT_ID_CONFLICT` (409) | This `event_id` exists with a different envelope | Keep the row, back off, log `ERROR` |
| `INVALID_ARGUMENT INVALID_EVENT` (422) | The envelope fails step 4 | Keep the row, back off |
| `UNAVAILABLE STORE_UNAVAILABLE` or `TASK_LIMIT_EXCEEDED` (503) | Commit uncertain, or the gate is full | Keep the row, back off |

The Broker stores `events.envelope` as the [events.md](events.md) JSON object. It holds the envelope fields, `occurred_at` as RFC 3339 UTC, and `payload` set to the parsed `payload_json`. The schema does not change. A republished envelope is equal when `occurred_at` is the same instant and every other field, including `payload`, is equal as a `jsonb` value. Rows stored over REST therefore compare and deliver unchanged. The relay backoff, the attribution, and the rule that relays keep no Broker hop counter stay as [publish](queues.md#publish) defines.

### Push delivery

The Broker calls `EventConsumerService.DeliverEvent` on one ready, leased, non-excluded replica whose registration declares the topic. The request holds the stored envelope and `attempt`. `payload_json` is the stored `payload` text, so every attempt sends the same bytes. The metadata is the hop credential, a Broker workload assertion with `azp` set to the producer's caller name, `idempotency-key` equal to `event_id`, and `x-request-id` equal to `event_id`. The `X-Event-*` and `X-Delivery-Attempt` headers have no replacement, because the signed message already carries their values.

A consumer accepts the delivery when the hop and assertion verify, `azp` maps to `event.producer` in the topic's producer allowlist, `event.event_type` is a topic that the consumer declares, and `idempotency-key` and `x-request-id` equal `event.event_id`. It commits its domain update and inbox record before it responds, and it deduplicates as before.

| Consumer response | Broker action |
| --- | --- |
| `OK` | The delivery is done. `applied` is false for a duplicate. |
| A status whose detail has `http_status` 409 or 422 | The delivery is dead-lettered and not retried. |
| Any other status, a connection error, or a timeout | The delivery is retried on the existing schedule, up to the [attempt limit](dead-letters.md#retry-policy). |

Each attempt keeps its deadline `T`, its breaker accounting, and its delivery slot. Storage, claims, subscriptions, and ordering stay as the [queues and topics contract](queues.md#push-delivery) defines.

## Discovery

`DiscoveryService` replaces the registry REST API with the same semantics. Leases, renewal intervals, conflicts, epochs, revisions, removal records, re-entry conditions, and topic validation do not change.

| REST endpoint | RPC | Result |
| --- | --- | --- |
| `PUT /internal/v1/discovery/instances/{instance_id}` | `RegisterInstance` | `Instance`, with `created` true where REST returned 201 |
| `GET /internal/v1/discovery/instances` | `ListInstances` | `Snapshot`. `include_unavailable` defaults to false. |
| `GET /internal/v1/discovery/instances/{instance_id}` | `GetInstance` | `Instance` |
| `POST /internal/v1/discovery/instances/{instance_id}/remove` | `RemoveInstance` | `Instance` in `removed` state |
| `POST /internal/v1/discovery/instances/{instance_id}/reactivate` | `ReactivateInstance` | `Instance` with a fresh registration ID |

The control credential is `x-control-name` and `x-control-token`. The caller rules do not change. A service registers and renews only its own name. Authenticated callers look up instances. A registered caller reports its own breaker trips, and a service removes its own instance on shutdown. Only `operator` reactivates. Errors map by the [status mapping](#status-mapping): `409 STALE_REGISTRATION`, `REGISTRATION_CONFLICT`, and `REENTRY_NOT_READY` are `ABORTED`, `403 TOPIC_FORBIDDEN` is `PERMISSION_DENIED`, and a failed state write is `UNAVAILABLE`.

Discovery probes each leased instance with `ControlService.GetStatus` on its `grpc_url`, every health interval, with one probe in flight per instance and deadline `T`. The probe's identity checks, readiness, load and critical-load rules, and alerts do not change. A failed probe makes the instance unavailable and never removes it. A caller's bootstrap half-open probe is `ControlService.GetStatus` on `DISCOVERY_GRPC_URL`. The Discovery bootstrap breaker classifies gRPC failures as [the status mapping](#status-mapping) does.

## Log export

`ControlService.ExportLogs` replaces `GET /internal/v1/logs`. The request has `since`, `until`, `max_bytes`, and Moderation's `process`, with the [instance export](logging.md#instance-export) defaults and limits. Invalid values return `INVALID_ARGUMENT INVALID_LOG_QUERY`.

The server streams `records` messages, then one `summary`. Each `records` message holds whole NDJSON records, oldest first, and at most 256 KiB unless one record is larger. The summary replaces the `X-Log-Truncated`, `X-Log-Records`, and `X-Log-Skipped` headers. The process stops at `max_bytes` without splitting a record, or after 2 seconds, and sets `truncated`. A stream that ends without a summary is an incomplete export.

Gateway's [administrator download](logging.md#administrator-download) calls `ExportLogs` on its targets' `grpc_url`. Those are Discovery at `DISCOVERY_GRPC_URL`, every registered instance that is ready or unavailable but not removed, and the publisher through one ready Moderation instance. Gateway reads its own file locally. The limits stay: 4 targets at once, a 3-second deadline per target, 15 seconds in total, and 16 MiB of uncompressed records. A stream that is cancelled at a limit is recorded in the manifest as `truncated`, `unavailable`, or `error`, as today.

Gateway's topic listing calls `BrokerService.ListTopics` with its control credential, a 3-second deadline, and a 64 KiB response limit. Any other result returns `503 DEPENDENCY_UNAVAILABLE` to the administrator, as today.

## Gateway routes

Gateway's public listener keeps every route in `PublicRoutes()`. The audit found no route without a client:

| Routes | Client |
| --- | --- |
| `/api/v1/players`, `/api/v1/auth/*`, `/.well-known/jwks.json` | Anonymous players. The public key route is in the guided Postman collection. |
| Player, friendship, team, session, case-status, applicant, credential, record-permission, decision, channel, message, and chat-ticket routes | Players acting in their own sessions |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/university-records` | Junior Moderators. University Record `4.0.6` serves it to an active Junior Moderator assigned the requested `kind`. A request without the required `kind` query returns `400 MALFORMED_REQUEST`. |
| `/api/v1/admin/*`, `/api/v1/rule-versions*`, `/api/v1/bans`, `/api/v1/disciplinary-actions` | Global administrators |

Gateway removes these routes:

| Route | Listener | Reason |
| --- | --- | --- |
| `GET /internal/v1/status` | `:8083` | Discovery and the operator call `ControlService.GetStatus`. |
| `GET /internal/v1/logs` | `:8083` | The operator calls `ControlService.ExportLogs`. Gateway collects its own records locally. |

After grade 8, `:8083` serves only `GET /healthz` and returns `404 NOT_FOUND` for every other request. The public listener still returns `404 NOT_FOUND` for `/internal/v1/*` and `401 UNAUTHORIZED` for service credentials. Gateway exposes no gRPC route, generic forwarding, or reflection to clients. `DelegatedRoutes()` stays as data. Gateway uses it only to bound the delegations it signs, and its patterns are the [resources](#resources-for-scopes) of the delegated RPCs.

## Extending to client requests

A later move to gRPC behind Gateway for every client request needs only additive steps:

1. Add RPCs for the public operations to the same per-service protos, annotated with `google.api.http` for `grpc-gateway`. `buf.yaml` already declares the googleapis dependency.
2. Add rows to the Broker policy table with `gateway` true, `callers` empty, `policy` `none`, and the public route as `resource`.
3. Add one gRPC handler per public operation in each owning service.
4. Generate Gateway's transcoding from the annotations.

The Broker forwarding, the metadata convention, the interceptors, the targeted queues, and the vendoring and generation pipeline need no rework. The pin keys are already reserved. The Postman collections verify that public responses stay identical.

## Logging

A process logs each RPC it serves as `event: "rpc_request"` with `rpc` (the full method name), `code` (the gRPC code name), `status` (the detail's `http_status`, or 200 for `OK`), `outcome`, and `duration_ms`. An outbound RPC is a `dependency_call` that adds `rpc` and `code`. The Broker's `dispatch` record for an RPC has `method: "POST"`, `route` set to the full method name, `status`, and `code`. Successful `GetStatus` calls log at `DEBUG`. The [logging contract](logging.md) applies otherwise.

## Rollout

The stack is always deployed as one pinned CPR release, so old and new versions never run together. Each repository therefore releases once, with gRPC and without its internal REST, and one CPR integration switches the whole stack. No caller falls back to REST after a gRPC failure.

1. CPR merges this contract and the protos. No runtime changes.
2. Every repository releases one version:
   - **Discovery** serves `DiscoveryService` and `ControlService`, probes instances by gRPC, and deletes its REST registry API and HTTP probes.
   - **The Broker** serves gRPC forwarding and `BrokerService`, dispatches RPCs and delivers events by gRPC, sends its own policy reads by gRPC, and registers by gRPC. It deletes REST service ingress, REST publish, REST delivery, REST policy reads, and its REST status, log, and topic endpoints. It keeps REST only for Gateway's client requests.
   - **Gateway and each domain service** add the gRPC listener, their services, `grpc_url`, and the gRPC Discovery client. They send every peer call, publish, log collection, and topic listing by gRPC, and delete their internal REST endpoints and clients.
3. One CPR integration pins all of these releases together. It is tested from a clean checkout before release.
4. Grade acceptance runs on that released stack.

Releases may publish in any order, because nothing runs them until the CPR integration pins them.

## Repository changes

| Repository | Step 2 to 4 | Step 5 |
| --- | --- | --- |
| Message Broker | gRPC server, pass-through codec, policy table with all 22 rows, resource-based policy, gRPC dispatch and delivery, `BrokerService`, `ControlService`, gRPC Discovery client, `INSTANCE_GRPC_URL` | Delete REST service ingress, publish, delivery, policy reads, status, logs, and topics. Keep Gateway dispatch on `:8080`. |
| Discovery | `DiscoveryService`, `ControlService`, `grpc_url` in both APIs, gRPC probes | Delete the REST registry API and HTTP probes. Keep `/healthz`. |
| Gateway | `ControlService`, gRPC Discovery client, `grpc_url` | gRPC log collection, `ListTopics`, and Session context reads. `:8083` serves only `/healthz`. |
| Player | `PlayerService`, `EventConsumerService`, `ControlService`, interceptor | Delete `/internal/v1/*` REST. |
| Session | `SessionService`, `EventConsumerService`, `ControlService`, interceptor | gRPC clients for Player, Rules, University, and the case owners. gRPC `ShiftEnded` relay. Delete `/internal/v1/*` REST. The public case-status route accepts only `azp=gateway`. |
| Applicant | `ApplicantService`, `CaseOwnerService`, `EventConsumerService`, `ControlService`, interceptor | gRPC clients for Session and University. gRPC `CaseInitialized` relay. Delete `/internal/v1/*` REST. |
| Credential | Same as Applicant, with `CredentialService` | Same as Applicant |
| University Record | `UniversityRecordService`, `CaseOwnerService`, `EventConsumerService`, `ControlService`, interceptor | gRPC client for Session. gRPC `CaseInitialized` relay. Delete `/internal/v1/*` REST. |
| Server Rules | `RulesService`, `ControlService`, interceptor | gRPC client for Session context and case status. Delete `/internal/v1/*` REST. |
| Moderation | `ControlService` with `process=publisher` | gRPC clients for Session, Applicant, Credential, University, Rules, and Player. The publisher publishes by gRPC. Delete `/internal/v1/*` REST. |
| Discord DMs | `ControlService` | gRPC clients for Session and University. Delete `/internal/v1/*` REST. |
| CPR | This contract. Set `GRPC_ADDRESS`, `BROKER_GRPC_URL`, and `DISCOVERY_GRPC_URL`. Add the vendored-proto integration check. | Remove `DISCOVERY_URL`, the domain services' `BROKER_URL`, and the stale Applicant and Credential `SESSION_URL` and `UNIVERSITY_URL` values. Record the released images. Add the gRPC checks to the demonstration. |

Every repository with a gRPC listener vendors `proto/`, commits its generated code, and adds the [three CI checks](#vendoring).

## Verification

Each repository tests its own side:

- The interceptor rejects repeated metadata, a missing or wrong hop token, `authorization`, and an assertion for another method, another message, another key, another audience, or a key whose issuer does not match.
- Handlers map errors to the code and detail in the [status mapping](#status-mapping). Callers classify each breaker outcome from that mapping.
- Deadlines reach outbound calls, and a cancelled call stops its outbound work.
- The Broker tests every policy row, an unknown method and target, both modes, raw-frame forwarding with an unchanged body hash, response refusal, and attribution trailers.

The released stack passes these checks with real services and no mocks. Run `grpcurl` on the Compose network with the checked-in protos, never with reflection:

```sh
docker run --rm --network student-id-please_default -v "$PWD/proto:/proto:ro" fullstorydev/grpcurl:v1.9.1 \
  -plaintext -import-path /proto -proto student_id/discovery/v1/discovery.proto \
  -H "x-control-name: operator" -H "x-control-token: $OPERATOR_CONTROL_TOKEN" \
  -d '{"include_unavailable": true}' discovery:50051 student_id.discovery.v1.DiscoveryService/ListInstances
```

- Every instance in `ListInstances` has a `grpc_url`. `ControlService/GetStatus` on each `grpc_url` returns its status, and `BrokerService/ListTopics` returns the listing.
- `grpcurl ... list` against any listener fails, because no listener serves reflection.
- A business RPC sent directly to a replica without the Broker hop returns `UNAUTHENTICATED`. A forwarded RPC with an operator control credential returns `UNAUTHENTICATED`. A caller outside a row's `callers` receives `PERMISSION_DENIED`.
- From inside the network, every `/internal/v1/*` path on a domain service, on Discovery, and on the Broker's `:8080` returns `404`. On Gateway, `:8083/internal/v1/status` and `:8083/internal/v1/logs` return `404`, and `:8083/healthz` returns `200`. The public listener returns `404` for `/internal/v1/*`.
- After both Postman collections run, `docker compose logs --no-log-prefix | grep -E '"route": ?"/internal/v1'` prints nothing. Every Broker `dispatch` record from a service caller has a `route` that starts with `/student_id.`.
- The Postman collections pass unchanged. A `curl` to the University record route with `kind` returns `200` for an assigned Junior Moderator and `403` for the Moderator.
- The [queues and topics](queues.md#verification) and [Broker dispatch](broker.md#verification) stack checks pass, including round-robin across replicas, breaker removal, queue limits, three `CaseInitialized` deliveries, and a Broker restart without event loss.
