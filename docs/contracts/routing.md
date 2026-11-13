# Load routing and rerouting contract

This contract changes how the Message Broker chooses a replica and what it does after a failed attempt. It replaces plain round-robin with least-load selection, and it lets an eligible request make at most one reroute to a second replica within its original budget. The [Message Broker contract](broker.md) keeps authorization, breakers, and attribution. The [queues and topics contract](queues.md) keeps targeted queues and delivery. The [gRPC contract](grpc.md) keeps the policy table and the status mapping. The [metrics contract](metrics.md) defines the counters that make these decisions visible.

## Load

The Broker computes one load value for each eligible replica generation at the moment it selects an instance. The value is the higher of two measurements:

```text
load = max(in_flight / capacity, reported_active_tasks / reported_max_concurrent_tasks)
capacity = min(reported_max_concurrent_tasks, BROKER_REPLICA_MAX_IN_FLIGHT)
```

| Term | Source |
| --- | --- |
| `in_flight` | The Broker's unfinished targeted attempts to this generation, the count that `BROKER_REPLICA_MAX_IN_FLIGHT` already bounds. It changes at once when an attempt starts or ends. |
| `reported_active_tasks`, `reported_max_concurrent_tasks` | `Instance.status.load.active_tasks` and `max_concurrent_tasks` from the Broker's current Discovery snapshot. Discovery copies them from its last `ControlService.GetStatus` probe of that replica. |
| `capacity` | The replica's own admission limit, capped by the Broker's per-replica slot limit. The Broker never sends more than `capacity` concurrent targeted attempts to one generation. |

The Broker term changes as soon as an attempt starts or ends. The reported term covers work the Broker cannot see, such as event deliveries and tasks still running after their caller left. The two terms count much of the same work, so the Broker takes the higher one and never adds them.

`active_tasks` counts admitted, unfinished business tasks over both HTTP and gRPC, including event deliveries, as the [status contract](resilience.md#status-and-load) defines. A service that counts only HTTP tasks reports too little load.

### Eligible entries

A replica generation is eligible only when all of these hold at selection time:

- Discovery lists it as `ready`, its lease has not expired, and its status matches its service name, instance ID, and boot ID. These rules do not change.
- The Broker's breaker has not excluded it.

Removed, unhealthy, pending, and expired entries are never eligible. Discovery's readiness and lease rules already remove a replica that stopped answering. The load sample does not decide eligibility.

### Stale samples

The reported term is used only when the sample is valid and fresh:

- The load has `max_concurrent_tasks` of at least 1 and `active_tasks` of at least 0.
- `last_checked_at` is set and no more than `BROKER_LOAD_MAX_AGE_SECONDS` before the Broker's current time.

Otherwise the Broker ignores the reported term and uses only `in_flight / capacity`. `capacity` then comes from the last valid `max_concurrent_tasks` that the Broker saw for this generation, capped by `BROKER_REPLICA_MAX_IN_FLIGHT`, or from `BROKER_REPLICA_MAX_IN_FLIGHT` alone when it saw none. The Broker keeps that last valid value per generation and drops it when the generation leaves its snapshot. The Broker compares `last_checked_at` with its own clock, as it already does for `lease_expires_at`. Both processes run on one host.

The default age of 4 seconds covers one Discovery health interval (1 second), one probe deadline `T` (2 seconds), and one registry refresh interval (1 second).

## Selection

The Broker selects from the eligible generations of the owner that have a free slot, `in_flight < capacity`:

1. Compute each candidate's load.
2. Keep only the candidates with the lowest load. Loads compare exactly, each computed with one division.
3. Among those candidates, take the first instance ID greater than the owner's cursor in lexical order, with wraparound. Set the cursor to that ID.

The cursor is the existing per-owner round-robin cursor from [selection and breaker](broker.md#selection-and-breaker). It now resolves ties only. With two idle replicas A and B, loads stay equal and selections are A, B, A, B, as before. When A carries more load than B, B receives requests until their loads meet, then the two alternate.

Selection skips a replica only while another candidate has strictly lower load. Each candidate at the lowest load is selected within as many selections as there are candidates at that load, while the set of tied candidates does not change. No healthy replica is starved.

If no generation is eligible, the Broker returns `503 NO_HEALTHY_INSTANCES` as before. If every eligible generation is at `capacity`, the request waits in its [targeted queue](queues.md#targeted-queues). A pinned Gateway dispatch ignores load and uses only its pinned generation.

Push delivery uses the same ordering among the subscriber replicas that have a free delivery slot under `BROKER_DELIVERY_REPLICA_IN_FLIGHT`. Delivery attempts do not count in `in_flight`, but they appear in the replica's reported load.

## Rerouting

After an attempt fails with a qualifying failure, the Broker can send the same request to another eligible replica. Qualifying failures are `connection_error`, `timeout`, and `http_5xx`, as [bounded calls and failure accounting](resilience.md#bounded-calls-and-failure-accounting) and the [gRPC status mapping](grpc.md#status-mapping) classify them. Every other result returns to the caller unchanged. A reroute does not wait for the breaker to trip. The third failure still trips it, and the excluded generation receives no reroute.

### Rules

A failed attempt leads to another attempt only when all of these hold:

1. The request may reroute by its class in the table below.
2. Only the original attempt was sent for this request. The limit is fixed at two attempts: the original and at most one reroute.
3. At least 250 ms of the request's budget remain.
4. An eligible generation that this request has not tried exists.

Each attempt has its own `attempt_id`, slot, breaker outcome, and `dispatch` record. Every attempt sends the same request frame or HTTP body, `x-request-id`, `idempotency-key` or `Idempotency-Key`, receiver assertion, and actor grant. The assertion is bound to the owner's audience, not to one replica, so it stays valid while it is unexpired. No attempt mints a new key, request ID, or assertion.

The reroute re-enters the owner's targeted queue at its original arrival position, ahead of every request that arrived after it, and it takes the next free slot on an untried eligible generation. It does not count against `BROKER_QUEUE_CAPACITY`. If its budget ends first, or if no untried generation is eligible, the Broker returns the last failed attempt's result.

### Budget

The [time budget](broker.md#admission-and-time-budget) does not change. It is `T - 250 ms` from receipt, 1.75 seconds by default, or less when the caller's deadline is earlier. Every attempt, the queue wait, and the reroute fit inside it. The caller's deadline never grows.

A request that may reroute splits its remaining budget when its first attempt starts and another eligible generation exists. The first attempt gets at most half of the remaining budget, about 875 ms, and the reroute gets the rest. Both attempts are still capped by the assertion's `exp`. Without this split, a timeout would use the whole budget and no reroute could start. A request that may not reroute, or that has only one eligible generation, gives its one attempt the whole remaining budget. The split is a cutoff inside the Broker: every attempt's gRPC deadline, and the deadline a backend sees, is the full remaining limit, so a backend's own calls through the Broker keep their real budget. When the first attempt's share ends, the Broker cancels that attempt and treats it as a `timeout`. A call whose task budget has already expired when it reaches the Broker fails with `DEADLINE_EXCEEDED` before admission.

A read on a healthy replica that takes longer than its share fails as a `timeout` and counts in that replica's breaker. With `T = 2` seconds, internal reads finish in far less than 875 ms.

### Request classes

| Class | Requests | May reroute after a qualifying failure |
| --- | --- | --- |
| Read | The 17 read rows below, the Broker's own policy reads, and Gateway dispatch with `GET` or `HEAD` | Yes |
| Keyed write | The 5 write rows below | Yes, with the same `idempotency-key` |
| Other write | Gateway dispatch with any other method | Only when the failed attempt was not sent |
| Pinned | Gateway dispatch with `X-Broker-Target-Instance-Id` | Never |
| Push delivery | `EventConsumerService/DeliverEvent` | Never within one claim. The [retry schedule](dead-letters.md#retry-policy) sends the next attempt. |

A keyed write may reroute after an uncertain failure, such as a timeout, because each owner stores its result under the key in data that all of its replicas share. The [removal, re-entry, and writes](resilience.md#removal-re-entry-and-writes) rules already allow a retry with the original key to reach another replica in that case. The second replica returns the stored result or applies the write once. If the first replica commits the same key later, the owner's unique key makes that commit return the stored result or fail with no second effect. Each owner verifies this under concurrent attempts.

Only HTTP Gateway dispatch uses the not-sent rule, because every gRPC write row is keyed. An attempt was not sent only when its TCP dial failed or its DNS lookup failed. Every other failure, including a reset or a timeout, is uncertain. The Broker never reroutes an uncertain failure of the other-write class. It returns the failure as it does today. Service ingress returns `503`, and Gateway dispatch keeps its public `502 DEPENDENCY_UNAVAILABLE` or `504 DEPENDENCY_TIMEOUT`. The client retries with its original `Idempotency-Key`.

### Policy table classes

Each row of the [RPC inventory](grpc.md#rpc-inventory) has a class. Method names omit the package prefix.

| RPC | Target | Class | Key |
| --- | --- | --- | --- |
| `PlayerService/GetPlayer` | `player` | Read | - |
| `PlayerService/GetTeam` | `player` | Read | - |
| `SessionService/GetSessionContext` | `session` | Read | - |
| `SessionService/GetAcceptedAttempt` | `session` | Read | - |
| `SessionService/GetCaseStatus` | `session` | Read | - |
| `CaseOwnerService/StartCase` | `applicant` | Keyed write | `attempt_id` |
| `CaseOwnerService/StartCase` | `credential` | Keyed write | `attempt_id` |
| `CaseOwnerService/StartCase` | `university_record` | Keyed write | `attempt_id` |
| `CaseOwnerService/GetCaseState` | `applicant` | Read | - |
| `CaseOwnerService/GetCaseState` | `credential` | Read | - |
| `CaseOwnerService/GetCaseState` | `university_record` | Read | - |
| `ApplicantService/GetApplicant` | `applicant` | Read | - |
| `CredentialService/GetCredentialResults` | `credential` | Read | - |
| `RulesService/GetCurrentRuleSet` | `rules` | Read | - |
| `RulesService/EvaluatePolicy` | `rules` | Read | - |
| `UniversityRecordService/CreateSnapshot` | `university_record` | Keyed write | The `snapshot_start` attempt ID |
| `UniversityRecordService/GetSnapshot` | `university_record` | Read | - |
| `UniversityRecordService/GetRetainedSnapshot` | `university_record` | Read | - |
| `UniversityRecordService/ReserveIdentity` | `university_record` | Keyed write | `case_id` |
| `UniversityRecordService/GetIdentity` | `university_record` | Read | - |
| `UniversityRecordService/GetRecordPermission` | `university_record` | Read | - |
| `UniversityRecordService/GetCaseRecords` | `university_record` | Read | - |

`EvaluatePolicy` is a read, because evaluation stores nothing. The class is a field of the policy row. A new row states its class. A new write row must have a required key. Public writes keep the other-write class, because the Broker has no table of which public routes their owners deduplicate.

## Attribution

The [attribution values](broker.md#responses-and-hop-accounting) describe the response that the caller receives:

- After a reroute that succeeds, `failure-origin` is `none`. The earlier failed attempt appears in the Broker's logs and metrics, and its breaker outcome stays recorded.
- After a final failure, `failure-origin` is `backend`, and the backend instance, registration, and attempt ID name the last failed attempt.

The attribution values and headers do not change, and callers keep their hop accounting. The `attempt` field of each `dispatch` record and the `attempt` label of `student_id_broker_dispatch_total` show whether a reroute happened.

## Logging

The `dispatch` record of each attempt adds these fields:

| Field | Meaning |
| --- | --- |
| `attempt` | The attempt number for this request, starting at 1 |
| `load` | The selected generation's load at selection, rounded to three decimals |
| `load_source` | `reported` when the reported term was used and was higher, `broker` otherwise, including a stale or invalid sample |

After each qualifying failure, the Broker writes one `WARN` record with `event: "reroute"`. It has `request_id`, `caller`, `target_service`, `route`, `failed_instance_id`, `failed_attempt_id`, `error_kind`, `remaining_ms`, and `decision`:

| `decision` | Meaning |
| --- | --- |
| `sent` | Another attempt starts. The next `dispatch` record has the same `request_id` and `attempt` one higher. |
| `not_allowed` | The request class forbids a reroute after this failure. |
| `attempt_limit` | The reroute already failed. The limit is two attempts. |
| `no_budget` | Less than 250 ms of the budget remained, or the budget ended while the reroute waited. |
| `no_alternate` | No untried eligible generation existed. |

The records of one request share its `request_id`: the first `dispatch` with its failure, `circuit_open` when that failure trips the breaker, `reroute`, the second `dispatch` with the other instance and its outcome, and the receiver's own `rpc_request` or `http_request` record. A keyed write shows the receiver's stored result on the second attempt, not a second business effect.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `BROKER_LOAD_MAX_AGE_SECONDS` | `4` | The oldest `last_checked_at` whose reported load the Broker uses, in seconds. Positive. An older sample leaves only the Broker term. |
| `BROKER_REPLICA_MAX_IN_FLIGHT` | `32` | Unchanged. It also caps `capacity`. |

The limit of two attempts and the 250 ms reroute floor are fixed. The floor equals the Broker's existing reply margin.

## Repository changes

| Repository | Change |
| --- | --- |
| Message Broker | Read `status.load` and `last_checked_at` from the snapshot. Add the stale-sample rule, least-load selection with the cursor as the tie-break, the capacity cap, the request classes in the policy table, rerouting with the budget split, and the logging fields. Use the same ordering for push delivery. Test a slow but healthy replica, because the 875 ms first-attempt share can count it as a timeout. |
| Discovery | None. `Instance.status.load` and `last_checked_at` already carry the samples. Verify that a failed probe keeps the old `last_checked_at`. |
| Every domain service and Gateway | Verify that `active_tasks` counts admitted gRPC business RPCs and event deliveries as well as HTTP tasks. Change only what fails. |
| Applicant, Credential, University Record | Verify that `StartCase`, `CreateSnapshot`, and `ReserveIdentity` store one result per key under two concurrent attempts on different replicas. Change only what fails. |
| CPR | This contract and the demonstration steps. |

## Verification

The Broker tests these cases with a deterministic clock:

- Load uses the higher term and the capacity cap. A sample exactly `BROKER_LOAD_MAX_AGE_SECONDS` old is used. A sample a millisecond older, or an invalid one, leaves the replica eligible with only the Broker term, with capacity from the last valid report or `BROKER_REPLICA_MAX_IN_FLIGHT`, and `load_source: "broker"`.
- Equal loads alternate A, B, A, B. Unequal loads prefer the lower load until the loads meet. A membership change keeps the cursor rule.
- Every request class, the attempt limit, the 250 ms floor, the budget split, the untried-generation rule, and the not-sent rule for a failed TCP dial and a DNS failure on Gateway dispatch.
- Attribution after a reroute success, a final failure, and a rejection before dispatch.

The released stack passes these checks with real replicas and no mocks:

- **Fair ties.** With two Player replicas and sequential `GET /api/v1/players/me` requests, the `dispatch` records alternate between the two instance IDs.
- **Unequal load.** Start a third Player replica with a smaller admission limit, `docker compose run -d --no-deps -e MAX_CONCURRENT_TASKS=4 player`. Send 64 concurrent `GET /api/v1/players/me` requests through Gateway. The small replica receives a smaller share of the dispatches, and `student_id_broker_backend_load` shows the three loads converge. Every request succeeds. Stop the extra container afterwards.
- **Stale samples.** Pause Discovery with `docker pause` and send requests. Between `BROKER_LOAD_MAX_AGE_SECONDS` after the last probe and the 5-second snapshot limit, `dispatch` records still reach ready replicas, with `load_source: "broker"`. After the snapshot limit, requests return `503 NO_HEALTHY_INSTANCES` as before. Unpause Discovery, and routing resumes after the next refresh.
- **Read reroute.** Pause one of two Player replicas with `docker pause`, then send 10 concurrent `GET /api/v1/players/me` requests. All of them return `200`. Each request that selected the paused replica has a `timeout` `dispatch`, a `reroute` with `decision: "sent"`, and a successful second `dispatch` on the other replica, with one `request_id`. Three timeouts within `W` log `circuit_open`, and Discovery records the removal. Unpause the replica and reactivate it afterwards by the [re-entry rules](resilience.md#removal-re-entry-and-writes).
- **Keyed write reroute.** Pause one of two University Record replicas and start a shift. Every rerouted `CreateSnapshot` or `ReserveIdentity` attempt carries its original key, and the University Record database holds one snapshot and one reservation for each key.
- **Other write.** Pause one Player replica and send `PATCH /api/v1/players/me` until one selects it. The client receives `504 DEPENDENCY_TIMEOUT`, and the log shows `decision: "not_allowed"`. Unpause the replica. A retry with the same `Idempotency-Key` returns the original result, and the display name changed once.
- The [Broker dispatch](broker.md#verification) and [queues and topics](queues.md#verification) stack checks still pass.
