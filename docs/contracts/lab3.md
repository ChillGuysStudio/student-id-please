# Lab 3 discovery and resilience contract

This reference defines the implementation target for [CPR #125](https://github.com/ChillGuysStudio/student-id-please/issues/125). It does not describe a delivered runtime or establish a completed grade. Gateway and Discovery use Go, the accepted shared-service banned-language baseline. Discovery is one private control-plane service. The deployment runs at least two replicas of each domain service.

## Request paths and identity

Business REST retains the [HTTP contract](http.md) and [Gateway authorization](../architecture.md#gateway-authorization). Clients use the public Gateway. Domain services use the internal Gateway, including authorization callbacks, case readiness reads, and chat permission reads. Discovery changes destinations, not route ownership, caller allowlists, receiver audiences, signed assertions, delegation, or business authorization. Disabled routes remain disabled. Discovery never supplies credentials or identity policy.

Registration, registry lookup, removal, reactivation, and status probes use direct private HTTP. This is a control-plane exception to the business REST rule. Requiring Gateway to discover Discovery through Gateway would create a startup cycle. `DISCOVERY_URL` is a fixed deployment address, not a discovered business route. Discovery probes the advertised instance directly, without Gateway, so it measures that instance. Neither Gateway listener exposes registry operations to public clients.

Control-plane requests use `X-Control-Name` and `X-Control-Token`, separate from business service credentials and Gateway receiver-hop tokens. Receivers authenticate these headers against `CONTROL_PLANE_TOKENS`. Names are the service names below, plus `operator`. A service can register or renew only its own service name. Authenticated callers can look up instances. Registered callers can report their own breaker trips. Only Discovery and `operator` can probe a registered service's private status endpoint. Discovery's own status endpoint also accepts authenticated control callers for bootstrap recovery. `operator` can remove and reactivate instances. A service can remove its own instance for shutdown. No Player bearer, Gateway assertion, or player authority enters this API.

The canonical registry names are `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation`, `discord-dms`, and `gateway`. These are route-owner names, not aliases for authenticated business callers or JWT targets. In particular, University's existing identity target remains `university-record`. Discovery itself uses `discovery` in status and logs but does not discover or register itself through HTTP.

## Configuration

The following names are the Lab 3 target settings. Existing services adapt their current configuration to these values. This document does not change Compose, `.env`, images, or submodule pins.

| Setting | Owner and value |
| --- | --- |
| `SERVICE_NAME` | Every process. One canonical name above, or `discovery`. |
| `INSTANCE_ID` | Every process. Required canonical UUID, unique per deployment replica slot and stable across process restarts. |
| `INSTANCE_HTTP_URL` | Every registered process. Required private root HTTP origin that reaches this replica, not a service-wide DNS load balancer. Gateway advertises its internal listener. |
| `INSTANCE_WS_URL` | DMs only. Required client-reachable WebSocket origin for this replica. Other services advertise `null`. |
| `DISCOVERY_URL` | All callers. Required private Discovery root origin, for example `http://discovery:8084`. |
| `DISCOVERY_ADDR` | Discovery. Default `:8084`, never published as public ingress. |
| `CONTROL_PLANE_NAME` | Every caller. Its canonical service name, or `operator` for the operator client. |
| `CONTROL_PLANE_TOKEN` | Every caller. Its private outgoing control-plane credential. |
| `CONTROL_PLANE_TOKENS` | Every receiver. JSON map of allowed control-plane names to credentials. No default credentials. |
| `OUTBOUND_TASK_TIMEOUT_SECONDS` | All HTTP callers. Default `2`, finite and positive. This is `T`, the outbound task timeout used by the breaker. All lab processes use the same value. |
| `CONTROL_MAX_CONCURRENT_CALLS` | All processes. Default `8`, positive integer. Bounds outgoing control calls and, separately, incoming control tasks. No unbounded worker queue. |
| `DISCOVERY_REGISTER_INTERVAL_SECONDS` | Registrants. Default `5`, positive and at most one third of the lease. |
| `DISCOVERY_LEASE_SECONDS` | Discovery. Default `15`, positive. |
| `DISCOVERY_REFRESH_INTERVAL_SECONDS` | Registry readers. Default `1`, positive. |
| `DISCOVERY_CACHE_MAX_AGE_SECONDS` | Registry readers. Default `5`, positive and less than the lease. |
| `DISCOVERY_HEALTH_INTERVAL_SECONDS` | Discovery. Default `1`, positive. |
| `DISCOVERY_CRITICAL_LOAD_RATIO` | Discovery and status producers. Default `0.90`, greater than zero and at most one. |
| `DISCOVERY_STATE_FILE` | Discovery. Required writable path on a persistent volume for removal records, for example `/data/removals.json`. |
| `DISCOVERY_ALERT_COOLDOWN_SECONDS` | Discovery. Default `60`, positive. |

`boot_id` is a fresh UUID generated once per process start. It is not `INSTANCE_ID`. A restart must not evade a removal by choosing a new instance ID. Adding a replica requires a new deployment-owned instance ID and an independently reachable HTTP origin. Reusing an ID in two live replicas is a configuration error.

HTTP origins have scheme `http` or `https`, a concrete host and port, and no path except `/`. They contain no credentials, query, or fragment. They must resolve to the intended replica from Gateway and Discovery. Wildcard, loopback, multicast, and link-local destinations are invalid. Private container IPs and replica-specific DNS names are valid. Bind addresses such as `0.0.0.0` are not advertised addresses. Control-plane credentials and addresses come from trusted deployment configuration, never client input.

DMs WebSocket origins use `wss`. Existing `GATEWAY_ALLOW_INSECURE_WS` and `GATEWAY_ALLOW_LOCAL_WS` flags retain their separate meanings for local demonstrations. Both flags are required for `ws://localhost:18009`. No flag permits wildcard or link-local addresses. A remote demonstration uses the laptop's reachable host name or address, not the client's own `localhost`.

Existing inbound task limits remain in force. Gateway and current Python adapters use `HTTP_TASK_TIMEOUT_SECONDS` and `HTTP_MAX_CONCURRENT_TASKS`. Current University source uses `TASK_TIMEOUT` and `MAX_CONCURRENT_TASKS`. Other adapters retain their documented equivalents. The default inbound task budget is 30 seconds with 100 admitted business tasks. It is not the breaker's `T`. Gateway's existing `GATEWAY_PEER_TIMEOUT` maps to `T`, default `2s`. No adapter silently derives a 105-second breaker window from the 30-second inbound limit.

## Status and load

Every domain service, Gateway, and Discovery exposes authenticated `GET /internal/v1/status` on its private listener. It returns `200 Status` when the process can produce a status snapshot, even when `ready` is false. Existing liveness paths and response bodies remain unchanged, including Player and Session `/health` and Gateway, Moderation, and DMs `/healthz`. Liveness does not depend on Discovery or remote business peers.

The schemas use the [HTTP type notation](http.md#paths-and-data-types). `Number` is a finite JSON number. All fields are required unless marked optional.

```text
Status = {
	service_name: string,
	instance_id: Id,
	boot_id: Id,
	live: Bool,
	ready: Bool,
	reason: string | null,
	load: {
		active_tasks: Int,
		max_concurrent_tasks: Int,
		utilization: Number,
		critical: Bool
	}
}
```

`live` is true in a successful snapshot. `ready` means local configuration, required storage, and the listener can serve business requests. It does not recursively require every business peer to be ready. Gateway also needs a current registry snapshot before it can route. Discovery needs its removal state loaded and writable before it accepts mutations. An unregistered service can be locally ready, but Discovery does not route it until registration and a successful probe complete.

`active_tasks` counts admitted, unfinished business HTTP tasks, including tasks still executing after cancellation. It excludes health probes, control-plane work, and idle WebSocket connections. `max_concurrent_tasks` is the actual positive admission limit, not a second capacity setting. `utilization` equals `active_tasks / max_concurrent_tasks`. `critical` equals `utilization >= DISCOVERY_CRITICAL_LOAD_RATIO`. At a capacity of 100, 89 active tasks are not critical and 90 are critical. A dead process or failed database check is not evidence of critical load.

Status and existing liveness probes stay outside the business admission gate. Status reads local counters and cached dependency state, finishes within `T`, and never makes recursive business calls. Its JSON response is at most 16 KiB. Control operations have their own finite admission bound from `CONTROL_MAX_CONCURRENT_CALLS` and deadline `T`. Saturated business traffic must not prevent health observations. Existing `503 TASK_LIMIT_EXCEEDED`, `504 TASK_TIMEOUT`, and `Retry-After: 1` behavior for business tasks stays unchanged.

Discovery probes each leased instance every health interval, with at most one probe in flight per instance. A probe must match the registered service name, instance ID, and boot ID. A mismatched or invalid snapshot makes the instance unavailable and produces a diagnostic log. `ready: false` also makes it unavailable. Neither is a qualifying breaker error unless the HTTP attempt itself has a qualifying failure. Discovery retries these observations at the next interval. A later valid, ready snapshot restores an unhealthy instance, but never a removed instance.

## Registry HTTP API

Registry endpoints are private Discovery endpoints. Requests and non-empty responses use JSON. Errors use the existing `Error` envelope. Malformed JSON returns `400`, invalid fields return `422`, missing or invalid control credentials return `401`, denied operations return `403`, and unknown instance IDs return `404`.

Control-plane mutations below use instance identity, registration generation, and `operation_id` for idempotent effects. They do not use the domain `Idempotency-Key` result cache. This is a narrow exception to [business idempotency](http.md#idempotency). A repeated renewal can return a newer lease time. A repeated removal cannot create a second removal, and a stale mutation cannot affect a new registration generation.

```text
Registration = {
	service_name: string,
	boot_id: Id,
	http_url: string,
	ws_url: string | null
}
Instance = {
	service_name: string,
	instance_id: Id,
	boot_id: Id,
	registration_id: Id,
	http_url: string,
	ws_url: string | null,
	state: "pending" | "ready" | "unhealthy" | "expired" | "removed",
	lease_expires_at: Time,
	last_checked_at: Time | null,
	status: Status | null,
	removed_at: Time | null,
	removal_reason: "circuit_open" | "operator" | "shutdown" | null
}
Snapshot = {discovery_epoch: Id, revision: Int, instances: Instance[]}
Failure = {
	attempt_id: Id,
	finished_at: Time,
	method: string,
	endpoint: string,
	kind: "connection_error" | "timeout" | "http_5xx",
	status_code: Int | null
}
Removal = {
	registration_id: Id,
	operation_id: Id,
	caller_instance_id: Id,
	reason: "circuit_open" | "operator" | "shutdown",
	task_timeout_ms: Int,
	failures: Failure[]
}
Reactivation = {registration_id: Id, operation_id: Id}
```

`registration_id` is a Discovery-assigned UUID for one admitted generation of an instance. It changes after an accepted new boot, reactivation, or reconstruction of a non-removed registration after Discovery restarts. A removed record keeps its generation across Discovery restarts. Late reports for another generation return `409 STALE_REGISTRATION` without changing the current record. Status observations and breaker counters never cross generations.

| Endpoint | Request | Success and behavior |
| --- | --- | --- |
| `PUT /internal/v1/discovery/instances/{instance_id}` | `Registration` | `201 Instance` for a new ID, `200 Instance` for a renewal. The path supplies the instance ID. A new record starts `pending`. |
| `GET /internal/v1/discovery/instances` | Optional `service_name`, optional `include_unavailable` boolean, default false | `200 Snapshot`. By default, only ready, leased, non-removed instances appear. `include_unavailable=true` also includes pending, unhealthy, expired, and removed records. |
| `GET /internal/v1/discovery/instances/{instance_id}` | No body | `200 Instance`, including unavailable state. |
| `POST /internal/v1/discovery/instances/{instance_id}/remove` | `Removal` | `200 Instance` in `removed` state. Discovery durably records removal before acknowledging it. |
| `POST /internal/v1/discovery/instances/{instance_id}/reactivate` | `Reactivation`, operator only | `200 Instance` with a fresh registration ID after the re-entry conditions below pass. Otherwise `409 REENTRY_NOT_READY`. |

`revision` is nonnegative, increases when membership or routing eligibility changes, and is meaningful only within `discovery_epoch`. Discovery generates a fresh epoch on every start. Lookup results sort by service name, then canonical instance ID. Empty lookup returns `200` with `instances: []`, not `404`. Unknown service names return `422`. There is no watch protocol or additional balancing service.

### Startup, duplicates, and restart recovery

Each registrant binds its listeners and starts liveness before its registration loop. It sends its first PUT without waiting for Gateway or other domain services. A failed attempt does not exit the process or hang startup. The registration loop has one in-flight call, uses the bounded caller policy below, and renews every 5 seconds by default. HTTP failures use backoff of 1, 2, then 5 seconds, capped at 5 seconds, subject to the breaker cooldown. A `401`, `403`, or configuration conflict logs a configuration error and retries no faster than every 5 seconds.

A PUT with the same service, boot ID, and addresses renews the lease to Discovery's current time plus 15 seconds. It creates no duplicate and does not reset health, counters, or removal state. Changed addresses within one boot return `409 REGISTRATION_CONFLICT`. A duplicate live HTTP origin under another ID also returns `409`. A different boot for the same instance ID returns `409` while the previous boot has an unexpired lease. After expiry, Discovery accepts the new boot as pending with a fresh generation. Removed IDs remain removed even after expiry or a new boot. Discovery can update their candidate boot and addresses only after the previous lease expires.

A ready instance requires both an unexpired lease and a valid ready status probe. Lease expiry immediately excludes it, without waiting for three failures. Renewal after expiry requires a new successful probe before routing resumes. Startup registration and lease expiry do not clear removal records.

Discovery keeps active registrations in memory and removal records in `DISCOVERY_STATE_FILE`. Each durable removal contains the instance identity, registration generation, advertised addresses, removal reason, removal time, and operation ID. An atomic file replacement is sufficient for this single-process lab service. A failed state-file write returns `503` and does not acknowledge a removal or reactivation. A corrupt or unreadable file makes Discovery unready. It must not start with an empty removal list after a load error.

After Discovery restarts, active registrations start empty, removed IDs remain denied, and the epoch changes. Periodic PUTs reconstruct non-removed records without a process restart. Every reconstructed record needs a fresh status probe. Removed instances can renew their candidate lease, but PUT returns `state: "removed"` and cannot restore routing. Fresh snapshots replace old membership rather than merge with it. No service retries a business command as part of registry recovery.

### Lookup, refresh, and round-robin

Gateway refreshes one complete snapshot every second. A refresh runs in the background, never once per business request. An atomic replacement prevents partially updated route sets. The last successful snapshot remains usable for at most 5 seconds after receipt. An empty successful snapshot clears old destinations immediately. An epoch change also clears old membership and counters for obsolete generations. Failed refreshes cannot extend cache age. There is no fallback to the Lab 2 static domain URLs in discovery mode.

Other service callers refresh the same registry to identify Gateway and to report a Gateway-hop failure against the correct generation. Their business destination remains the configured internal `GATEWAY_URL`, not a direct domain URL. It must match exactly one registered Gateway origin. Unknown, removed, stale, or ambiguous Gateway identity prevents a new business dispatch with `503 DEPENDENCY_UNAVAILABLE`. Registration and lookup still use the fixed Discovery address, so this does not block bootstrap.

Gateway selects only ready, leased instances from a current snapshot, minus its local breaker exclusions. Each owner has one thread-safe round-robin cursor shared by proxy, authorization, and realtime clients. Selection uses instance IDs in lexical order. Starting with IDs A and B, selections are A, B, A, B. When membership changes, the next selection is the first surviving ID greater than the last selected ID, with wraparound. An added C therefore enters without starving A or B. Cursors advance only for a dispatch, not for an authorization rejection before dispatch. An authorization dependency dispatch counts as its own selection.

Gateway selects an instance once for each physical backend attempt and keeps that instance's identity through signing, sending, body consumption, logging, and failure reporting. No request header chooses a backend. No instance is selected for an unagreed route. When no eligible instance remains, Gateway returns `503 NO_HEALTHY_INSTANCES` with `Retry-After: 1` and does not dial a stale address. Already dispatched calls can finish within their original bounds. Removal does not cancel committed effects or replay in-flight requests.

Local breaker exclusion is immediate. After Discovery acknowledges removal, every registry reader stops new dispatches to that generation within one refresh interval plus the refresh call budget, at most 3 seconds with defaults. If refresh fails, cache expiry stops dispatch within 5 seconds of the last successful snapshot. Lease expiry is also checked at selection time, not only at refresh.

## Bounded calls and failure accounting

Every HTTP caller applies one deadline across connect, request send, response headers, and consumed response body. The deadline is the minimum of `T`, the remaining parent task budget, and signed authority expiry. A shorter endpoint budget can reduce an attempt deadline but never changes the counter's configured window. Existing internal reads and realtime negotiation remain capped at 2 seconds. Redirects are not followed with credentials. Request and response size limits remain finite. No transport may perform hidden retries.

Each caller process owns a counter keyed by destination `instance_id` and `registration_id`, across all methods and endpoints of that destination. The counter is not per URL, route, or endpoint, and replicas have separate counters. Failures from different callers are not summed into one undocumented distributed threshold. Any caller that reaches the threshold can remove that destination generation globally.

The failure window is `W = 3.5 * T`, or 7 seconds with the default `T = 2 seconds`. At attempt completion, the caller records its monotonic completion time and discards failures older than `now - W`. Three distinct qualifying attempts within that inclusive window trip the breaker. Successes do not reset the rolling window. Two failures do not trip it. Three failures at 0, 2, and 7 seconds trip it. Failures at 0, 2, and 7.001 seconds do not. Logs and reports use corresponding UTC timestamps, but local counting does not depend on wall-clock adjustments.

Qualifying failures are connection errors, connection resets during consumed response bodies, caller attempt timeouts, and HTTP status 500 through 599. HTTP `503 TASK_LIMIT_EXCEEDED` and `504 TASK_TIMEOUT` count. Expected `4xx`, including `409` and `429`, do not count. Local validation, a pre-dispatch rejection, an open-breaker rejection, no eligible destination, and cancellation by the upstream caller do not count as backend attempts. Invalid or oversized successful responses produce diagnostics and fail the operation, but do not become an invented HTTP `5xx` from that destination.

One physical attempt has one caller-generated UUID `attempt_id` and at most one outcome. A `5xx` followed by a body timeout counts once, as `http_5xx`. A transport timeout with no status counts once, as `timeout`, not also as a connection error. Retry attempts receive new attempt IDs. Outer middleware must not record the same attempt again. Counters shared by proxy and specialized clients use the same outcome recorder. A returned `5xx` from a service that failed on its own dependency is a separate HTTP attempt, not the dependency attempt itself.

At the third failure, the caller excludes that generation locally, logs `circuit_open`, and submits one removal operation. `failures` contains exactly three distinct attempt IDs from that caller and generation within `W`. `task_timeout_ms` equals configured `T` in milliseconds. `endpoint` is a method-independent route template without query values, player IDs, tickets, or tokens. `status_code` is 500 through 599 only for `http_5xx`, otherwise `null`. Discovery validates the reporter's service and instance, generation, configured timeout, evidence count, and timestamp span before accepting `reason: "circuit_open"`. It does not need to receive every error in real time.

If Discovery cannot accept the report, the caller keeps the local exclusion and retains one pending removal per destination generation. It retries the same `operation_id` under the bounded control-call policy. A duplicate removal for an already removed generation returns its removed record without another transition or notification. `409 STALE_REGISTRATION` discards the old report. For operator or shutdown removal, `failures` is empty and `task_timeout_ms` still declares `T`. Operator uses its authenticated role rather than a registered caller instance. No local exclusion is cleared merely because a refresh still shows an old ready record.

### Attribution through Gateway

Gateway owns the physical backend attempts for both client REST and service REST. It records and reports failures for the exact selected backend, including failures from authorization reads and realtime ticket issuance. An upstream domain service must not report that backend attempt again or count its resulting `5xx` against Gateway.

On authenticated internal responses, Gateway constructs these private headers locally after it removes any backend-supplied copies:

| Header | Meaning |
| --- | --- |
| `X-Gateway-Instance-Id` | The Gateway process's stable instance ID. |
| `X-Gateway-Registration-Id` | Its current registered generation. |
| `X-Gateway-Failure-Origin` | `backend`, `gateway`, or `none`. |
| `X-Gateway-Backend-Instance-Id` | Required only for `backend`, the instance responsible for the failed backend attempt. |
| `X-Gateway-Backend-Registration-Id` | Required only for `backend`, that attempt's generation. |
| `X-Gateway-Backend-Attempt-Id` | Required only for `backend`, the already recorded attempt ID. |

`backend` means a qualifying backend failure caused this response. It can identify an authorization dependency even when the requested business endpoint was never sent. `gateway` means Gateway itself failed, such as its own admission rejection or task expiry without a previously recorded backend failure. `none` covers success, expected `4xx`, policy rejection before a backend attempt, and lack of healthy instances. A lack of backend capacity must not evict a healthy Gateway process. These headers grant no authority, reach only the authenticated private hop, and never appear on public responses. Public bodies keep their existing safe error shape and contain no internal addresses.

A domain caller records only connection errors and timeouts of its physical Gateway hop, or qualifying responses with verified `gateway` origin. It uses the configured Gateway origin and its current registry generation, not a destination claimed by client input. For `backend`, Gateway already owns reporting. For `none`, no breaker failure is added. Missing or inconsistent internal metadata fails closed with a diagnostic and no guessed backend report. A hop with no response can be counted against Gateway even if Gateway independently observed a backend timeout. Those are two different physical attempts, not duplicate reports of one backend attempt.

### Caller coverage and bootstrap exception

| Caller | Outbound paths that require the policy | Failure owner |
| --- | --- | --- |
| Gateway | Public and internal proxy dispatch, Session context and other authorization reads, DMs ticket client | Gateway records the selected backend generation through one shared recorder. |
| Session, Applicant, Credential, Rules, University Record, Moderation, and DMs | All business peer operations through internal Gateway, including permission and readiness callbacks | The service records its Gateway hop. Gateway records backend attempts. |
| Player | Registration, renewal, lookup, removal reporting, and any future business HTTP | Player already needs a control-plane breaker even without a current business peer caller. |
| All registrants, including Gateway | Direct registration, registry refresh, removal reports, and operator reactivation clients | The direct caller records Discovery failures across all these endpoints. |
| Discovery | Direct status probes for every registered instance, including Gateway | Discovery records each probed generation and applies removal locally without calling itself over HTTP. |
| Discovery notification adapter | Outbound Discord delivery | The adapter bounds calls and records failures for its configured external destination. It never evicts a domain instance for a Discord outage. |

Discovery is a fixed bootstrap destination, not a member of its own registry. Its counter uses the configured normalized origin instead of a registry generation. Three control-plane failures exclude that address from normal control calls for `W` and log a trip. After `W`, one half-open `GET /internal/v1/status` is allowed. A successful live and ready response closes the local bootstrap breaker and clears its old failures. Failure opens it for another `W`. Other calls cannot become parallel probes. There is no recursive report of a Discovery failure to Discovery. Pending registrations and removals resume only after the bounded probe succeeds. Cached business routing still obeys its 5-second age limit.

This bootstrap exception also explains removal semantics for non-registry destinations such as the Discord webhook. Their counter uses the configured normalized origin. Their caller excludes the failed address locally, not through a fictitious registry record. The notification adapter permits one new notification attempt after `W`. Success closes its local breaker and clears its old failures. It does not probe Discord with a duplicate notification. Every actual failed HTTP attempt still enters its destination counter.

## Removal, re-entry, and writes

Grade 10 removal means removing the failed instance generation from the routable set, not removing its healthy replicas or deleting its domain data. Removal creates a durable record. Discovery continues to probe a removed instance only while it has a current candidate lease, so the operator can observe recovery. Healthy status or a repeated PUT never clears removal.

Re-entry is explicit, not automatic. The operator can reactivate only after all these conditions hold:

- At least `W` has elapsed since removal.
- The instance has a current registration lease.
- Discovery has observed two consecutive valid, ready, non-critical status responses after removal for the current candidate boot. A failed probe or candidate boot change resets this count.

Reactivation checks the removed generation, durably clears the removal record, and assigns a fresh registration ID. A repeated reactivation for the old generation returns `409 STALE_REGISTRATION` without another effect. Registry readers clear the local exclusion only on a fresh generation from Discovery. Other replicas remain routable throughout. Lease-only expiry and ordinary unhealthy status can recover through renewal and a successful probe without operator action because they are not breaker removals.

No layer automatically replays business writes after a timeout, connection failure, removal, or membership change. This includes authentication mutations, case creation, decisions, and chat-ticket issuance. An explicit caller retry retains the original method, endpoint, body, caller identity, and `Idempotency-Key`. A timeout does not prove rollback. Retries can reach another replica only when that logical service shares durable idempotency results. Otherwise the operation remains unavailable until its result can be recovered safely. A new key must not hide an uncertain write.

Safe reads can retry at most twice with backoff within the original parent deadline. Every actual retry is a separate attempt and round-robin selection. The default is no automatic retry. The idempotent control operations above can retry under their stated registration or reporting loop. There is no generic write-retry middleware.

Replicas of one logical owner share that owner's durable data and idempotency results. Existing once-only scoring, progression, snapshot, reservation, ticket, and case constraints remain requirements. Replicas use the same agreed signing and ticket encryption keys where verification crosses replicas. Process-local caches or locks must not decide durable ownership. This is a replica acceptance condition, not authorization to replace service storage.

## Direct DMs WebSockets

`POST /api/v1/sessions/{session_id}/realtime-negotiation` remains public Gateway REST with body `{}` and a UUID `Idempotency-Key`. Success remains `200 {url: string, expires_at: Time}`. Gateway checks participation, selects one ready DMs instance, issues the ticket through that selected HTTP origin, and builds `url` from that same record's `ws_url` plus `/api/v1/sessions/{session_id}/ws?ticket=...`. It does not use another replica's WebSocket address or a client-supplied Host header. Ticket format, single use, expiry, actor authority, and recurring permission checks remain DMs responsibilities.

For example, two DMs records can advertise `http://dms-a:8009` with `ws://localhost:18009`, and `http://dms-b:8009` with `ws://localhost:28009` for a local client with both development flags enabled. A shared DNS name that randomly routes a connection is not a replica-specific advertised origin. Gateway's former single `GATEWAY_EXTERNAL_WS_URL` is not the discovery-mode source of this address. The existing public chat-ticket response `{ticket, expires_at}` does not change. The negotiation route supplies the instance-correct connection URL.

The client connects directly to the advertised DMs address. Gateway never relays upgrades or frames. Removing an instance prevents new negotiations to it but does not forcibly close an already authorized socket. A failed connection does not cause Gateway to replay ticket issuance or silently move the socket. The client obtains a new ticket through a new explicit negotiation and recovers messages through Gateway REST history. An uncertain retry of the original negotiation retains its original key and must not remint a consumed or expired ticket. DMs replicas share the required ticket state and Redis delivery so peers on different replicas can exchange frames.

## Logs and notification interface

All processes log startup identity, registration results, dependency failures, task-limit rejection, task timeout, and state transitions. Caller logs include service name, caller instance ID, destination instance ID, registration ID, attempt ID, route template, elapsed milliseconds, and failure kind when those fields apply. Breaker logs include `T`, `W`, the three attempt IDs, and the removal outcome. No log includes credentials, assertions, raw query strings, chat tickets, or private player evidence.

Discovery logs readiness transitions, lease expiry, removals, re-entry, and critical-load alerts with instance identity. A first critical snapshot emits `critical_load`. A first non-critical snapshot after it emits `load_recovered`. Repeated critical samples do not emit another alert within the 60-second cooldown. Readiness alerts and their recovery use the same per-instance transition rule. Discovery measures its own cached status locally on the health interval and logs and notifies for its own critical load without a self-HTTP call.

The Discord adapter accepts this notification interface:

```text
Alert = {
	event_id: Id,
	event: "critical_load" | "load_recovered" | "unready" | "ready" | "removed" | "reactivated",
	service_name: string,
	instance_id: Id,
	observed_at: Time,
	utilization: Number | null,
	reason: string
}
```

Delivery uses a private `DISCORD_WEBHOOK_URL` supplied when notification implementation is ready. No webhook value is required to implement or test this interface. A bounded in-memory queue holds at most one pending alert per instance and event type. Delivery obeys `T`, the concurrency limit, and the external-destination breaker. A failed delivery logs a redacted error and is not automatically replayed as a write. Later independent alerts can still be delivered. Notification failure never blocks health polling, registration, or routing removal. A fake sender proves the interface only. Grade 9 evidence needs receipt in the configured Discord destination.

## Contract verification matrix

These are implementation and integrated-runtime acceptance cases. The CPR documentation checks do not substitute for them.

| Component | Required contract checks |
| --- | --- |
| Every domain service and Gateway | Preserve liveness under saturation. Check identity and readiness status. Observe utilization at 89 and 90 of 100 admitted tasks. Register two distinct replica IDs and reject collisions. Bound all new control calls. |
| Discovery registration | Exercise first PUT, duplicate PUT, delayed startup, lease expiry, boot conflict, address conflict, empty lookup, restart reconstruction, corrupt removal state, and removed-instance renewal. |
| Discovery monitoring | Probe each replica directly. Separate `ready: false` from critical load. Check bounded slow probes, transitions, alert cooldown, and healthy recovery without resetting a removal. |
| Gateway routing | With stable IDs A and B, observe A, B, A, B across actual dispatches. Add C, remove B, and continue without stale B dispatches or static fallback. Cover proxy, authorization reads, and realtime clients. |
| Every HTTP caller | Use a deterministic clock for two failures, a third inside `3.5 * T`, the inclusive boundary, and a failure outside it. Mix endpoints on one destination. Separate replicas and generations. Cover connection errors, timeouts, `5xx`, expected `4xx`, body failure, and cancellation. |
| Gateway attribution | Fail a Session authorization read and a DMs ticket call. Verify the actual backend tuple, one recorded outcome per attempt, no public metadata leak, no service re-report, and no Gateway eviction for `NO_HEALTHY_INSTANCES`. Separately fail the Gateway connection and count its hop. |
| Removal and re-entry | Trip on three real failures, exclude locally, persist and propagate removal, keep a healthy replica serving, reject immediate PUT-based recovery, restart Discovery with the tombstone intact, and require cooldown, two probes, and explicit reactivation. Reject delayed old-generation reports. |
| Bootstrap and reports | Hold Discovery offline during startup and during removal reporting. Verify finite calls, local exclusions, one half-open probe, registry cache expiry, and eventual registration or removal without circular dependencies. Include Player's new control-plane calls. |
| Writes and shared state | Lose a response after commit. Confirm no hidden replay or new key, recover the original result through another replica, and preserve once-only domain effects. |
| DMs replicas | Negotiate each advertised address, exchange direct frames between peers on different replicas, remove one from new negotiations, and recover history after reconnect without weakening actor or ticket checks. |
| Discord notifications | Assert the `Alert` interface with a fake sender. Separately observe a real critical-load alert and recovery in Discord without exposing the webhook. |

Integrated evidence records published image references, distinct instance IDs, request and attempt IDs, effective `T`, timing, and observed routing changes. It must distinguish a real multi-replica deployment from mocked client tests.
