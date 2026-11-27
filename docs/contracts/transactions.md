# Distributed transactions

Ending a shift changes two databases: Session ends the shift, and Player awards XP to every participant. This contract runs that change as a long-running saga that the Message Broker coordinates. Each step commits in one service's own database. When a step fails for good, compensations undo the steps that already committed, in reverse order. No service holds a lock while another service works.

Two-phase commit ran this flow up to release v5.0.5. The saga replaces it. Its coordinator, participant calls, tables, and the `max_prepared_transactions` setting are removed.

## Flow catalogue

The Broker knows each flow by name, like a topic. A flow names its initiator and its steps in a fixed order. Each step names the service that runs it and the compensation that undoes it.

| Flow | Initiator | Steps, in order | Kind | Compensation |
| --- | --- | --- | --- | --- |
| `end-shift` | `session` | 1. `session` `hold-shift`: the shift becomes `ending` | Compensable | `reopen-shift`: the shift becomes `active` again |
|  |  | 2. `player` `award-shift`: XP for each participant | Pivot | `revoke-shift-award`: a reversing ledger entry |
|  |  | 3. `session` `finish-end`: the shift becomes `ended` | Retriable | None |

A compensable step can be undone. The pivot is the last step that can still be undone. A retriable step runs only after the pivot is done, and it is retried until it succeeds. Once the pivot is done, the saga only moves forward.

Session applies `hold-shift` itself, in the same local transaction as its end request, before it starts the saga. The Broker records that step as done when the saga starts. Every other step and every compensation runs through the Broker.

### Payloads

Each step and its compensation receive the same payload: a UTF-8 JSON object of at most 64 KiB. The participant validates it, and an invalid payload is a rejection with `422 INVALID_STEP`. The Broker stores payloads as `jsonb`, so a participant compares parsed values, never bytes.

```text
HoldShiftPayload = {session_id: Id, actor_id: Id, idempotency_identity: string, request_sha256: string}
AwardShiftPayload = {session_id: Id, participant_ids: Id[], score: Int}
FinishEndPayload = {session_id: Id, idempotency_identity: string, request_sha256: string}
```

`participant_ids` and `score` come from the session as `hold-shift` froze it. Player awards `max(0, score)` XP to each participant once per shift, as before.

## Roles and calls

[`sagas.proto`](../../proto/student_id/sagas/v1/sagas.proto) defines two services. `BrokerService/ListSagas` in [`broker.proto`](../../proto/student_id/broker/v1/broker.proto) serves the [listing](#saga-listing).

| RPC | Caller and credential | Served by |
| --- | --- | --- |
| `SagaCoordinatorService/StartSaga` | The flow's initiator, service credential | The Message Broker |
| `SagaParticipantService/RunStep`, `Compensate` | The Broker, hop credential and workload assertion | One ready replica of the step's service |
| `BrokerService/ListSagas` | `gateway` or `operator`, control credential | The Message Broker |

`StartSaga` takes the same authentication as `BrokerService/PublishEvent`. Gateway is refused. The Broker checks, in order:

| Check | Error |
| --- | --- |
| The caller authenticates | `UNAUTHENTICATED UNAUTHORIZED` (401) |
| `saga_id` is a UUID, and `steps` matches the flow's services and operations in order, with payloads that parse as JSON objects of at most 64 KiB | `INVALID_ARGUMENT INVALID_SAGA` (422) |
| The flow is in the catalogue | `NOT_FOUND UNKNOWN_FLOW` (404) |
| The caller is the flow's initiator | `PERMISSION_DENIED FLOW_FORBIDDEN` (403) |
| A saga with this ID either does not exist or has an equal request | `ABORTED SAGA_ID_CONFLICT` (409) |
| `broker-db` accepts the write | `UNAVAILABLE STORE_UNAVAILABLE` (503) |

Two requests are equal when their flow and every step's service, operation, and payload are equal, with payloads compared as `jsonb` values.

The Broker calls a participant as it [pushes an event](grpc.md#push-delivery). The metadata is the receiver's hop credential, a Broker workload assertion with `azp` set to the initiator, and `idempotency-key` set to `<saga_id>:<operation>`. `x-request-id` is the `StartSaga` request ID for calls within that request, and the `saga_id` for calls that recovery makes. The participant accepts the call when the hop and assertion verify, `azp` is the flow's initiator, and it serves the flow and operation. Each call goes to one ready replica that the [load rule](routing.md#load) selects, and it is never rerouted. A connection error, a timeout, and a `5xx` count toward that replica's breaker, as [bounded calls](resilience.md#bounded-calls-and-failure-accounting) define. `STORAGE_UNAVAILABLE`, `PARTICIPANT_BUSY`, every other `4xx` including `SAGA_COMPENSATED`, and a call that the Broker cuts off itself do not count.

`CompensateRequest.operation` names the step that the compensation undoes, for example `award-shift`, not the compensation. A step and its compensation therefore share the `idempotency-key` and the participant's lock, on purpose: both act on the same step of the same saga.

## State machine

A saga is `running` until its last step is done, and then `completed`. When a step fails for good, the saga becomes `compensating`, and then `compensated` once every compensation has succeeded. `completed` and `compensated` are final.

| Step state | Meaning |
| --- | --- |
| `pending` | Not run yet, or its last attempt failed and it waits for a retry |
| `done` | The participant answered `OK` |
| `failed` | The step failed for good. It caused the compensation. |
| `compensated` | Its compensation answered `OK` |
| `skipped` | The saga compensated before this step ran |

The Broker runs one step at a time, in order. It writes each result to `broker-db` before it sends the next call, so a restart never repeats a step that it recorded as done. A participant still handles a repeated call safely, because a call can succeed while its answer is lost.

### Forward retries

A step result is one of three kinds:

- `OK`: the step is done, and the next step runs.
- A rejection, an error with an `ErrorDetail` whose `http_status` is `4xx`, except `409 PARTICIPANT_BUSY` and `429`: the step failed for good, and the saga compensates.
- Anything else, including `5xx`, `STORAGE_UNAVAILABLE`, `PARTICIPANT_BUSY`, a timeout, a connection error, or no eligible replica: the step stays `pending` and is retried after 1, 5, and 30 seconds, then every 30 seconds.

A Player outage therefore delays the saga. Session keeps the shift `ending`, and the saga completes once Player answers. Up to and including the pivot, the retries stop at whichever comes first: 25 attempts of one step, or the saga's deadline 10 minutes after it started. The saga then compensates with the cause `attempts` or `deadline`. A retriable step after the pivot has no attempt limit or deadline. It is retried until it succeeds, because the steps before it can no longer be undone.

### Compensation

Compensation is possible only while the pivot is not done. It runs in reverse order, for every step that is `done`, and for the step that failed when its outcome is unknown. A step that timed out may have committed, so its compensation runs too. A step that was rejected committed nothing, and its compensation runs only to block a late duplicate, as the participant rules below require. Steps that never ran become `skipped`.

A compensation is retried on the same schedule until it answers `OK`, with no attempt limit and no deadline. It must not fail for good. A compensation that is rejected, and a retriable step that is rejected, both mean that the coordinator and the participant disagree. The Broker logs it at `ERROR` as `saga_conflict` and keeps retrying. The saga stays `compensating` or `running`, and its shift stays `ending`, which blocks that shift's cases. The rules below make this impossible in normal operation, so no automatic repair exists. An operator finds the saga in the [listing](#saga-listing), compares it with the participant's `saga_log`, and corrects the participant's data, after which the next retry succeeds.

### Participant rules

Each participant keeps one table in its own database:

```text
saga_log(saga_id uuid, operation text, state text, created_at timestamptz, primary key (saga_id, operation))
```

A step and its compensation take the transaction-level advisory lock `saga:<saga_id>:<operation>`, so they never run at the same time.

| Call | Row `applied` | Row `compensated` | No row |
| --- | --- | --- | --- |
| `RunStep` | `OK`, `applied` false | Rejects with `409 SAGA_COMPENSATED` | Applies the step and inserts `applied` in one transaction, then `OK`, `applied` true |
| `Compensate` | Undoes the step and sets `compensated` in one transaction, then `OK`, `applied` true | `OK`, `applied` false | Inserts `compensated`, then `OK`, `applied` false |

A step that arrives after its compensation therefore finds the `compensated` row and changes nothing. A compensation that arrives before its step leaves the row behind, so that the step never runs. A step that cannot get its lock or row in time answers `409 PARTICIPANT_BUSY`, which is retried.

### End-shift steps

`hold-shift` runs in Session's end request, under the existing `request:` and `session:` advisory locks. It runs the checks of the end operation, sets the status to `ending`, increments `revision`, stores the saga ID and the step requests under the idempotency identity, and inserts its `saga_log` row. An `ending` shift accepts no case start, decision, or other change, as an `ended` shift does.

Session's compensation `reopen-shift` sets the shift back to `active` and increments `revision`, only while it is `ending` under this saga ID. It sets the `hold-shift` row to `compensated` in the same transaction. It stores the response `409 PROGRESSION_REJECTED` under the idempotency identity, with the cause in `details`, so that a retry with the same key returns it. A shift that is already `ended` is never reopened. That would mean the coordinator and Session disagree, so Session rejects it with `409 SHIFT_ENDED`.

`award-shift` in Player uses the progression ledger under the advisory locks `progression:shift:<session_id>` and `player:<id>`, taken in ascending player ID order. It inserts one `progression_ledger` row of kind `shift` with `delta = max(0, score)` for each participant, records the `saga_id` and the session ID on each row, and recomputes each player's XP. An award belongs to its saga. A shift has at most one award that no `shift_reversal` offsets, which is its active award. A shift that was reopened and then ended by a new saga gets a new award, because its earlier award was reversed.

| Condition | Player's answer |
| --- | --- |
| This saga's award exists | `OK`, `applied` false |
| The shift has an active award from earlier, from an earlier saga, a two-phase commit, or a `ShiftEnded` event, with the same participants and score | `OK`, `applied` false. Nothing is recorded for this saga, so its compensation reverses nothing. |
| The shift has an active award with other values | `409 AWARD_CONFLICT` |
| A participant does not exist | `404 PLAYER_NOT_FOUND` |
| An XP total would exceed 2^31 - 1 | `422 XP_OVERFLOW` |

Player's compensation `revoke-shift-award` inserts one row of kind `shift_reversal` with the negated `delta` for each `shift` row of that saga, and recomputes XP. XP stays `max(0, sum of the ledger)`, as before.

`finish-end` in Session takes the same `session:` lock as `reopen-shift`. It sets the shift to `ended` only when the shift is `ending` under this saga ID, as `hold-shift` stored it. It sets `ended_at` and stores the `200` response under the idempotency identity. A shift that this saga already ended answers `OK`, `applied` false. A shift that belongs to another saga, or whose `hold-shift` row is `compensated`, is rejected with `409 SAGA_COMPENSATED`. With the pivot rule, neither case occurs in normal operation.

## Starting a saga and the end-shift response

`POST /api/v1/sessions/{session_id}/end` keeps its route, its owner rule, its `Idempotency-Key` rule, and its existing checks.

1. Session runs `hold-shift` in its own transaction and commits it. The saga is then recorded in Session, even if the Broker is down.
2. Session calls `StartSaga` with the stored saga ID and steps, holding no database lock.
3. The Broker inserts the saga and its steps, records `hold-shift` as done, and runs the next steps within the call's budget. It returns when the saga is final, when a step attempt failed and must wait for a retry, or 250 ms before the caller's deadline. Each step call gets at most 250 ms within the request. A call cut off this way is the Broker's own doing and counts toward no breaker, and recovery retries it.
4. A Session relay starts every stored saga that `StartSaga` has not accepted yet. It retries after 1, 5, and 30 seconds, then every 30 seconds, with the same request.

| Result | Response |
| --- | --- |
| `completed` | `200 Session` in `ended`, the stored response of `finish-end` |
| `running`, a Broker error, or no answer | `202 Session` in `ending`. The saga continues in the Broker or the relay. |
| `compensating` or `compensated` | `409 PROGRESSION_REJECTED` with the cause in `details`. Reads show the shift `ending` until Session's compensation has run, and then `active`. |

A retry with the same key returns the stored response once one exists. Until then, it returns `202` with the current session. A request that saw `compensating` returns `409` at once, while a retry can still return `202` until Session's compensation has stored the `409`. That is intended: the stored response follows Session's own state, not the Broker's. An end request for an `ending` shift with another key also returns `202`. An `ended` shift returns `200`, as before.

The synchronous end now enters `ending`. That replaces the earlier rule that it never did. `ending` is the visible pending state of the saga.

## Isolation

A saga gives up isolation between its steps. Other readers see each step as it commits:

- A participant's XP can rise while the shift is still `ending`. If the saga compensates, a reversing ledger entry takes the XP away again.
- `ending` is a semantic lock in Session. No case start, decision, or second end changes the shift until the saga is final.
- No service waits for another service's lock. A Player outage delays only this saga, and the shift's result stays stored in Session as `ending`.

## Recovery

A Broker task resumes sagas that their requests did not finish. It runs when the Broker starts and then every second. It claims rows with `FOR UPDATE SKIP LOCKED` and leases each claimed row for `T` plus 1 second, so two Broker instances never run the same saga at once. `T` is the outbound task timeout of the [resilience contract](resilience.md#configuration), 2 seconds by default. It runs the next forward step or compensation that is due, and records the result before the next call. A call that was in flight when the Broker stopped has no recorded result, so recovery sends it again. That repeat is safe because the [participant rules](#participant-rules) make every call repeatable.

| State at restart | Recovery |
| --- | --- |
| `running`, next step `pending` | Runs the step on the retry schedule |
| `running`, deadline passed, pivot not done | Becomes `compensating` with the cause `deadline` |
| `running`, pivot done | Runs the retriable step until it succeeds |
| `compensating` | Runs the remaining compensations in reverse order |
| `completed` or `compensated` | Nothing |

## Saga listing

The Broker serves `BrokerService.ListSagas` to the `gateway` and `operator` control principals. Other authenticated callers receive `PERMISSION_DENIED FORBIDDEN`. At most two listings run at once. A third returns `UNAVAILABLE TASK_LIMIT_EXCEEDED`.

| Request field | Rule |
| --- | --- |
| `page_size` | `1` to `100`. `0` means `20`. |
| `page_token` | Empty for the first page, otherwise a `next_page_token` from an earlier page |
| `flow`, `state` | Optional exact filters. A flow outside the catalogue, or a state other than `running`, `compensating`, `completed`, and `compensated`, returns `INVALID_ARGUMENT VALIDATION_ERROR`. |

Items are newest first. `next_page_token` is empty on the last page. A malformed token returns `INVALID_ARGUMENT VALIDATION_ERROR`. If `broker-db` does not answer within one second, the call returns `UNAVAILABLE STORE_UNAVAILABLE`. Each item holds the saga ID, flow, initiator, state, cause, times, and for each step its position, service, operation, state, attempts, compensation attempts, last status, and last error kind. It never holds a payload, a participant ID, or any credential.

Gateway exposes the listing to administrators:

```text
GET /api/v1/admin/broker/sagas?limit=Int&cursor=String&flow=String&state=String
```

Gateway handles it exactly like `GET /api/v1/admin/broker/dead-letters`:

- It verifies the administrator and accepts only these four query parameters. `limit` maps to `page_size`, and `cursor` to `page_token`.
- It makes one call with its control credential, allows 3 seconds, and accepts a response of at most 256 KiB.
- A Broker `INVALID_ARGUMENT` returns `400 VALIDATION_ERROR`, and any other Broker failure `503 DEPENDENCY_UNAVAILABLE`.
- Anonymous callers receive `401`, and authenticated non-administrators `403`.

```json
{
  "items": [
    {
      "saga_id": "6f1c2a8e-4b7d-4e19-9a3c-2d5e8f0b1c47",
      "flow": "end-shift",
      "initiator": "session",
      "state": "completed",
      "cause": null,
      "created_at": "2026-11-27T10:00:00Z",
      "deadline": "2026-11-27T10:10:00Z",
      "updated_at": "2026-11-27T10:00:00.120Z",
      "finished_at": "2026-11-27T10:00:00.120Z",
      "steps": [
        {"position": 1, "service": "session", "operation": "hold-shift", "state": "done", "attempts": 1, "compensation_attempts": 0, "last_status": null, "last_error_kind": ""},
        {"position": 2, "service": "player", "operation": "award-shift", "state": "done", "attempts": 1, "compensation_attempts": 0, "last_status": 200, "last_error_kind": ""},
        {"position": 3, "service": "session", "operation": "finish-end", "state": "done", "attempts": 1, "compensation_attempts": 0, "last_status": 200, "last_error_kind": ""}
      ]
    }
  ],
  "next_cursor": null
}
```

`cause` is `null` or `{operation, kind, code}`. `finished_at` is `null` until the saga is final.

## Broker storage

Migration `004_sagas.sql` adds two tables to `broker-db`. A later migration drops the two-phase commit tables.

```text
sagas(saga_id uuid primary key, flow text, initiator text, state text, deadline timestamptz,
  cause jsonb, created_at timestamptz, updated_at timestamptz, finished_at timestamptz,
  next_attempt_at timestamptz)

saga_steps(saga_id uuid, position int, service text, operation text, compensation text,
  payload jsonb, state text, attempts int, compensation_attempts int, last_status int,
  last_error_kind text, primary key (saga_id, position))
```

Finished sagas stay for inspection.

## Logs and metrics

The Broker writes these records. None of them contains a payload or a participant ID.

- `saga_started` at `INFO` with `saga_id` and `flow`
- `saga_step` for each call, with `saga_id`, `flow`, `phase` (`forward` or `compensate`), `operation`, `target_service`, `target_instance_id`, `attempt`, `outcome`, `duration_ms`, and `error_kind` on failure: `DEBUG` on success and `WARN` on failure
- `saga_compensating` at `WARN` with the cause
- `saga_completed` or `saga_compensated` at `INFO` with `duration_ms`
- `saga_conflict` at `ERROR`

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `student_id_broker_sagas_total` | Counter | `flow`, `outcome` | Final sagas: `completed` or `compensated` |
| `student_id_broker_saga_duration_seconds` | Histogram | `flow`, `outcome` | Time from the start to the final state |
| `student_id_broker_saga_steps_total` | Counter | `flow`, `operation`, `phase`, `outcome` | Step and compensation calls: `ok`, `retry`, or `rejected` |
| `student_id_broker_sagas_unresolved` | Gauge | `flow`, `state` | Sagas in `running` or `compensating`, read from `broker-db` every 5 seconds |

## Failure cases

| Case | Result |
| --- | --- |
| Normal end | The saga completes within the request. The end returns `200`, the shift is `ended`, and each participant has the XP. |
| Player has no ready replica or its database is down | The end returns `202` with the shift `ending`. The award is retried, and the saga completes once Player answers. |
| Player rejects the award | The saga compensates. Player's compensation records the rejection, Session reopens the shift, and a retry of the end returns `409 PROGRESSION_REJECTED`. |
| The award times out and then commits late | A later retry finds the `applied` row and answers `OK`. If the saga compensated first, the late call finds the `compensated` row and changes nothing. |
| The Broker restarts mid-saga | Recovery resumes at the first step that is not recorded as done. No recorded step runs twice. |
| The Broker is down when the end request arrives | The end returns `202` with the shift `ending`. Session's relay starts the saga when the Broker returns. |
| A step or compensation is repeated | `OK` with `applied` false, and no second change |
| The same end request is retried | It returns the stored response, or `202` while the saga runs |
| Retries run out, or the deadline passes, before the pivot is done | The saga compensates every step that may have committed, in reverse order. |
| Session is unavailable after the award | The award stays. `finish-end` is retried until Session answers, and the shift then becomes `ended`. |
| A shift is reopened by a compensation and ended again | The new saga gives a new award. The reversed award does not count. |

## What changes

- The end-shift response adds `202 Session` in `ending`. `409 PROGRESSION_REJECTED` now comes from the saga's compensation. The two-phase codes `409 SESSION_CHANGED`, `503 TRANSACTION_ABORTED`, and `503 COORDINATOR_UNAVAILABLE` are gone.
- Session still does not publish `ShiftEnded`, and Player keeps its consumer for events stored earlier. A shift's active award, from any source, prevents a second award.
- The progression ledger adds the kind `shift_reversal` for compensations.
