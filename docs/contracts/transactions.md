# Distributed transactions

Ending a shift changes two databases: Session marks the shift ended, and Player awards XP to every participant. Until now Session committed its change with a `ShiftEnded` outbox entry, and Player applied the event later. The two changes were eventually consistent: for a while, a shift could be ended without its XP.

This contract makes that flow atomic with two-phase commit. The Message Broker coordinates. Session and Player are the participants, and each holds its change in a PostgreSQL prepared transaction until the Broker's decision arrives. Both databases commit, or neither does.

## Flow catalogue

The Broker knows each flow by name, like a topic. A flow names its initiator and its participants in a fixed order.

| Flow | Initiator | Participants, in order |
| --- | --- | --- |
| `end-shift` | `session` | `session` with operation `end-shift`, `player` with operation `award-shift` |

The initiator can also be a participant. Session starts the transaction from its end-shift request, and the Broker then prepares Session like any other participant.

### Payloads

Each payload is a UTF-8 JSON object of at most 64 KiB. The participant validates its own payload. An invalid payload is a rejection with `422 INVALID_TRANSACTION`.

```text
EndShiftPayload = {session_id: Id, actor_id: Id, revision: Int,
  idempotency_identity: string, request_sha256: string}

AwardShiftPayload = {session_id: Id, participant_ids: Id[], score: Int}
```

- `revision` is the session revision that the initiator read. Session rejects the prepare if the session changed after that.
- `idempotency_identity` and `request_sha256` let Session store the end-shift response in the prepared transaction, so a retry with the same `Idempotency-Key` returns it.
- `participant_ids` and `score` come from the same session read. Player awards `max(0, score)` XP to each participant once per shift, as before.

## Roles and calls

[`transactions.proto`](../../proto/student_id/transactions/v1/transactions.proto) defines two services.

| RPC | Caller and credential | Served by |
| --- | --- | --- |
| `TransactionCoordinatorService/RunTransaction` | The flow's initiator, service credential | The Message Broker |
| `TransactionParticipantService/Prepare`, `Commit`, `Abort` | The Broker, hop credential and workload assertion | One ready replica of the participant |

`RunTransaction` takes the same authentication as `BrokerService/PublishEvent`: `x-service-name` and `x-service-token`, checked against `BROKER_SERVICE_TOKENS`. Gateway is refused. The Broker checks, in order:

| Check | Error |
| --- | --- |
| The caller authenticates | `UNAUTHENTICATED UNAUTHORIZED` (401) |
| `transaction_id` is a UUID, and `participants` matches the flow's services and operations in order, with payloads that parse as JSON objects | `INVALID_ARGUMENT INVALID_TRANSACTION` (422) |
| The flow is in the catalogue | `NOT_FOUND UNKNOWN_FLOW` (404) |
| The caller is the flow's initiator | `PERMISSION_DENIED FLOW_FORBIDDEN` (403) |
| A transaction with this ID either does not exist or has an equal request | `ABORTED TRANSACTION_ID_CONFLICT` (409) |
| `broker-db` accepts the write | `UNAVAILABLE STORE_UNAVAILABLE` (503) |

Two requests are equal when their flow and every participant's service, operation, and payload are equal, with payloads compared as `jsonb` values.

The Broker calls a participant as it [pushes an event](grpc.md#push-delivery). The metadata is the receiver's hop credential, a Broker workload assertion with `azp` set to the initiator, and `idempotency-key` set to the `transaction_id`. `x-request-id` is the request ID of the `RunTransaction` call, or the `transaction_id` for calls that recovery makes. The participant accepts the call when the hop and assertion verify, `azp` is the flow's initiator, and it serves the flow and operation. Each call goes to one ready replica that the [load rule](routing.md#load) selects. It counts toward that replica's breaker like a dispatch, and it is never rerouted.

## Protocol

### Transaction ID

The initiator chooses the `transaction_id` and keeps it until the transaction ends. Session stores one ID per end-shift idempotency identity, in its own short transaction, before it calls the Broker. A retry of the same request, for example after the Broker cut off the first forwarded attempt, joins the same transaction. After an abort, the next retry stores a new ID and starts a new transaction. Session holds no database lock while it waits for the Broker, because the Broker prepares Session on its own connection.

### Phase one

1. The Broker inserts the transaction with state `preparing` and its participants into `broker-db`. Its prepare deadline is the earlier of 1 second after the insert and 250 ms before the caller's gRPC deadline. When the transaction already exists with an equal request, the call joins it and waits for its decision instead.
2. The Broker sends `Prepare` to every participant at once, with that deadline. It sends each `Prepare` once. A failed prepare is not retried.
3. A participant applies the operation in one database transaction, as if it would commit. It sets `lock_timeout` to the time that remains before the deadline. Instead of committing, it inserts its `transaction_log` row and runs `PREPARE TRANSACTION 'student-id:<transaction_id>:<service>'`. It answers `prepared` once `PREPARE TRANSACTION` returns. With synchronous replication, the prepared transaction is then on two nodes.
4. If the operation had already been applied, the participant rolls back and answers `read_only`. Nothing waits for phase two on that participant.
5. If the operation fails a business rule, the participant rolls back and returns the error with its `ErrorDetail` and a `4xx` `http_status`. That is a no vote.

### Decision

The decision is the commit point. The Broker writes it to `broker-db` before it sends any phase-two call:

- When every participant answered `prepared` or `read_only` before the deadline, the state becomes `committing`.
- When any participant rejected the operation, failed, timed out, or had no eligible replica, the state becomes `aborting` with the cause. The Broker does not wait for the remaining votes.

The write changes the state only while it is still `preparing`, so a concurrent decision by [recovery](#recovery) cannot be overwritten. If `broker-db` refuses the write, no decision exists, and `RunTransaction` returns `STORE_UNAVAILABLE`. Recovery then aborts the transaction.

### Phase two

The Broker sends `Commit` or `Abort` to every participant that did not answer `read_only`. That includes a participant whose `Prepare` timed out, because it may have prepared. A participant that rejected the operation prepared nothing, and `Abort` returns OK for it.

The Broker retries a phase-two call until the participant answers `OK`: first within the request, then from recovery after 1, 5, and 30 seconds, then every 30 seconds without limit. When every participant has answered, the state becomes `committed` or `aborted`.

`RunTransaction` returns when phase two has finished or the caller's deadline is near. `outcome` is the decision. `completed` is true when every participant acknowledged phase two. `cause` names the participant and `kind` of an abort: `rejected` with the participant's `code` and `http_status`, `busy` for `PARTICIPANT_BUSY`, `timeout`, `unavailable`, or `deadline` when the prepare deadline passed first.

### Participant rules

Each participant keeps one table in its own database:

```text
transaction_log(transaction_id uuid primary key, state text, created_at timestamptz)
```

`Prepare` inserts the row with state `prepared` inside the prepared transaction, so the row commits with the operation. `Abort` inserts it with state `aborted` when nothing is prepared. The primary key turns every race into a defined result.

| Call | Prepared transaction exists | Row `prepared` (already committed) | Row `aborted` | No row |
| --- | --- | --- | --- | --- |
| `Prepare` | Waits for the key, then rejects | `read_only` | Rejects with `409 TRANSACTION_CLOSED` | Prepares |
| `Commit` | `COMMIT PREPARED`, then `OK` | `OK` | `FAILED_PRECONDITION TRANSACTION_NOT_PREPARED` (412) | `FAILED_PRECONDITION TRANSACTION_NOT_PREPARED` (412) |
| `Abort` | `ROLLBACK PREPARED`, then `OK` | `FAILED_PRECONDITION TRANSACTION_COMMITTED` (412) | `OK` | Inserts `aborted`, then `OK` |

A `Prepare` that arrives after its `Abort` therefore finds the `aborted` row and prepares nothing. An `Abort` that arrives while a `Prepare` is still running waits on the key, up to its `lock_timeout`, and returns `UNAVAILABLE` if the wait runs out. The Broker retries it and then finds the prepared transaction. A participant refuses to start a `Prepare` after its deadline, and rejects it with `409 TRANSACTION_CLOSED`. When its `lock_timeout` runs out, for example behind another prepared transaction, it rejects with `409 PARTICIPANT_BUSY`. Contention is expected, so it counts toward no breaker.

`Commit` and `Abort` work on any connection to the primary, because a prepared transaction belongs to the database, not to the connection that prepared it. `Commit` and `Abort` also run after a participant restart or a PostgreSQL failover.

The two `FAILED_PRECONDITION` results mean that the coordinator and a participant disagree. That is an operational fault, not a business result. The Broker logs it at `ERROR`, keeps the transaction unresolved, and keeps retrying, so it stays visible until an operator acts.

### End-shift operations

`end-shift` in Session runs the checks of the current end operation under the same `request:` and `session:` advisory locks. It then sets `status` to `ended`, sets `ended_at`, increments `revision`, and stores the `200` response under the idempotency identity. It no longer writes a `ShiftEnded` outbox entry.

| Condition | Session's answer |
| --- | --- |
| The session is already ended, or the idempotency identity already has a stored response | `read_only` |
| The session is missing or the actor is not its owner | `404 SESSION_NOT_FOUND` or `403 SESSION_FORBIDDEN` |
| A case or scoring event is unfinished | `409 CASE_UNFINISHED` |
| The session is not active | `409 INVALID_SESSION_STATE` |
| `revision` differs from the session's revision | `409 SESSION_CHANGED` |

`award-shift` in Player uses the existing progression ledger and the business receipt `shift:<session_id>` under the same advisory locks. It inserts one `progression_ledger` row of kind `shift` with `delta = max(0, score)` for each participant and recomputes each player's XP.

| Condition | Player's answer |
| --- | --- |
| A receipt for the shift exists with the same participants and score, from either this flow or an earlier `ShiftEnded` | `read_only` |
| A receipt exists with other values | `409 AWARD_CONFLICT` |
| A participant does not exist | `404 PLAYER_NOT_FOUND` |
| An XP total would exceed 2^31 - 1 | `422 XP_OVERFLOW` |

## End-shift response

`POST /api/v1/sessions/{session_id}/end` keeps its route, its owner rule, its `Idempotency-Key` rule, and its existing errors. When the session is already ended, it returns `200` without a transaction, as before. Otherwise Session reads the session, stores the transaction ID, and calls `RunTransaction`.

| Result of `RunTransaction` | Response |
| --- | --- |
| `committed` | Session commits its own prepared part if that is still pending, then returns the stored `200` response. |
| `aborted`, Session rejected | Session's own error from the table above. The shift stays as it was. |
| `aborted`, Player rejected | `409 PROGRESSION_REJECTED`, with Player's `code` in `details`. The shift stays active. |
| `aborted` for `busy`, `timeout`, `unavailable`, or `deadline` | `503 TRANSACTION_ABORTED` with `Retry-After: 1`. The shift stays active. |
| `STORE_UNAVAILABLE`, or the Broker cannot be reached | `503 COORDINATOR_UNAVAILABLE` with `Retry-After: 1`. A retry with the same key joins the transaction. |

A committed transaction never returns an error to the caller, even if Player's phase two is still retrying. Player's XP becomes visible when its `Commit` succeeds.

The Broker records every phase-one failure as a [nested outage](resilience.md#storage-outages) of the `RunTransaction` request ID. Session's resulting `503` therefore has the kind `dependency_unavailable` and does not count toward Session's breaker. The `409` results do not count toward any breaker.

The synchronous end still does not enter `ending`. A shift whose transaction is undecided stays `active` to every reader, because the prepared change is not visible.

## Recovery

A Broker task resolves transactions that their requests did not finish. It runs when the Broker starts and then every second. It claims rows with `FOR UPDATE SKIP LOCKED`, so two Broker instances never resolve the same transaction at once.

- A `preparing` transaction whose prepare deadline passed more than 1 second ago gets the decision `aborting`. Its votes are lost if the Broker restarted, so the transaction is presumed aborted. No participant prepares after that deadline.
- A `committing` or `aborting` transaction gets its pending phase-two calls on the retry schedule.

A participant never decides alone. After a participant restart or a PostgreSQL failover, the prepared transaction is still in the database, and the next `Commit` or `Abort` finds it.

## Blocking

Two-phase commit blocks by design. Between `PREPARE TRANSACTION` and the decision, a participant holds every lock of its prepared transaction: the session row, each participant's player row, and their advisory locks.

- Other writes to that session or those players wait. Each request waits only within its own deadline and then fails as it does today for a slow store. Reads are not blocked.
- When the Broker or `broker-db` is down after a prepare, the locks stay held until the Broker resolves the transaction. Nothing else can release them safely, because only the Broker knows whether it decided to commit.
- `broker-db` is a single PostgreSQL instance, not a replicated cluster. A lost `broker-db` loses the decisions of unfinished transactions. Recovery then needs an operator, who reads the prepared transactions with `SELECT gid FROM pg_prepared_xacts` in each participant database and ends them with `COMMIT PREPARED` or `ROLLBACK PREPARED`.

## Configuration

PostgreSQL refuses `PREPARE TRANSACTION` while `max_prepared_transactions` is 0, its default. The Session and Player clusters set it to 16. That is more than the end-shift transactions that can be prepared at once in this stack. Patroni keeps the setting in its cluster configuration, so the standbys get the same value, which PostgreSQL requires. A new cluster takes it from `config/patroni/patroni.yml` at bootstrap. An existing cluster needs `patronictl edit-config --set postgresql.parameters.max_prepared_transactions=16` and a restart.

## Broker storage

Migration `003_transactions.sql` adds two tables to `broker-db`.

```text
transactions(transaction_id uuid primary key, flow text, initiator text, state text,
  prepare_deadline timestamptz, cause jsonb, created_at timestamptz,
  decided_at timestamptz, completed_at timestamptz, next_attempt_at timestamptz)

transaction_participants(transaction_id uuid, position int, service text, operation text,
  payload jsonb, vote text, completed boolean, attempts int, last_error_kind text,
  primary key (transaction_id, service))
```

`state` is one of `preparing`, `committing`, `aborting`, `committed`, and `aborted`. Finished transactions stay for inspection.

## Logs and metrics

The Broker writes `transaction_decided` at `INFO` with `transaction_id`, `flow`, `outcome`, `duration_ms`, and for an abort `cause_service`, `cause_kind`, and `cause_code`. It writes `transaction_completed` at `INFO` when phase two finishes. Each participant call writes `transaction_call` with `transaction_id`, `phase` (`prepare`, `commit`, or `abort`), `target_service`, `target_instance_id`, `attempt`, `outcome`, `duration_ms`, and `error_kind` on failure: `DEBUG` on success and `WARN` on failure. A disagreement writes `transaction_conflict` at `ERROR`. Records never contain payloads.

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `student_id_broker_transactions_total` | Counter | `flow`, `outcome` | Decisions: `committed` or `aborted` |
| `student_id_broker_transaction_duration_seconds` | Histogram | `flow`, `outcome` | Time from the insert to the decision |
| `student_id_broker_transactions_unresolved` | Gauge | `flow`, `state` | Transactions in `preparing`, `committing`, or `aborting`, read from `broker-db` every 5 seconds |

## Failure cases

| Case | Result |
| --- | --- |
| Normal end | Both commit. The shift is ended, and every participant has the XP. |
| Player has no ready replica, or its database is down, at prepare | Abort. The shift stays active, and the end returns `503 TRANSACTION_ABORTED`. |
| Player rejects the award | Abort. The shift stays active, and the end returns `409 PROGRESSION_REJECTED`. |
| A prepare is slower than the deadline | Abort. A late prepare finds the `aborted` row, or is rolled back by the retried `Abort`. |
| The Broker restarts before the decision | Recovery aborts after the deadline. The shift stays active, and a retry with the same key starts a new transaction. |
| The Broker restarts after the decision | Recovery sends the remaining phase-two calls. Both databases reach the decided state. |
| A participant replica restarts after prepare | Another replica, or the same one after its restart, commits or aborts the prepared transaction. |
| A participant's PostgreSQL primary fails over after prepare | The new primary has the prepared transaction, and the retried call ends it. |
| `Commit` or `Abort` is repeated | `OK`, with no second change. |
| The same end request is retried | It joins the transaction and returns the same result. |
| Two end requests with different keys run together | The second waits for the first one's locks. It then answers `read_only` and returns `200`, or its `lock_timeout` runs out and it returns `503 TRANSACTION_ABORTED`. |

## What changes

- Session no longer writes `ShiftEnded` when it ends a shift. The topic stays in the catalogue, and Player keeps its consumer, so events stored before the change still apply. The shared receipt `shift:<session_id>` prevents a second award.
- The end-shift response adds `409 PROGRESSION_REJECTED`, `409 SESSION_CHANGED`, `503 TRANSACTION_ABORTED`, and `503 COORDINATOR_UNAVAILABLE`.
- XP is visible when the end returns, unless Player's phase two is still retrying.
