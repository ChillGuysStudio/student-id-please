# Domain events

The payload types come from the [domain contract](domain.md), [case initialization](cases.md), and [service APIs](api.md). The Message Broker carries these events as topics. The [queues and topics contract](queues.md) defines publish, push delivery, subscriptions, and the allowlists.

Every event uses JSON. `CaseInitialized` uses `schema_version = 2`. The other events use `schema_version = 1`. A topic name equals its `event_type`. The event names and payload fields below are fixed. Removing or changing a required field requires a new major schema version. Consumers accept additional optional fields.

```text
Event<T> = {event_id: Id, event_type: string, schema_version: Int,
            occurred_at: Time, producer: "applicant" | "credential" | "university_record" |
            "moderation" | "session", correlation_id: Id, payload: T}
// CaseInitializedPayload is the version-2 three-variant union in cases.md.
DecisionScoredPayload = {decision_id: Id, session_id: Id, case_id: Id, moderator_id: Id,
                        action: Action, correct: Bool, score_delta: Int, penalty: Int}
ShiftEndedPayload = {session_id: Id, participant_ids: Id[], processed_count: Int,
                     score: Int, penalties: Int, ended_at: Time}
DisciplinaryPayload = {disciplinary_action_id: Id, player_id: Id, xp_penalty: Int,
                       reason: string}
```

| Event | Producer | Subscribers | Payload and correlation |
| --- | --- | --- | --- |
| `CaseInitialized` (schema 2) | Applicant, Credential, or University Record | Applicant, Credential, University Record | `CaseInitializedPayload`, including required `initialization_attempt_id`<br>`correlation_id = case_id`, never attempt ID |
| `DecisionScored` | Moderation | Session | `DecisionScoredPayload`<br>`correlation_id = case_id` |
| `ShiftEnded` | Session | Player | `ShiftEndedPayload`<br>`correlation_id = session_id` |
| `DisciplinaryActionApplied` | Moderation | Player | `DisciplinaryPayload`<br>`correlation_id = disciplinary_action_id` |

Each subscriber service receives one copy, and its replicas compete for that copy. An initializer can consume its own case event as a deduplicated no-op, but it never republishes a consumed initialization event. A publication retry uses the original `event_id`. Consumers also deduplicate by the business ID in the payload. This protects against a producer that assigns two event IDs to one case, decision, shift, or disciplinary action.

Version 2 requires the original Session initialization attempt reference in every source branch, including empty outsider bundles. Subscribers enforce [retained initialization authority](cases.md#retained-initialization-authority) before creating or resuming projections. The authenticated producer must be the retained selected initializer; `correlation_id`, `event_id`, and `case_id` are not substitutes for `initialization_attempt_id`.

The old version-1 `CaseInitialized` shape, exchange, queues, and stored events remain historical and unchanged. Its payload has the original `CaseSeed` fields without `initialization_attempt_id` and the same three domain branches. Do not synthesize an attempt reference, upgrade stored envelopes, dual-publish a new case as version 1, or replay unverifiable version-1 messages to authorize new effects. An exact already-completed duplicate can be acknowledged as a no-op. Otherwise quarantine unverifiable history under the existing bounded failure policy and preserve its domain data. This is not a legacy authorization protocol.

The Broker retries a failed delivery after 1, 5, and 30 seconds, then every 30 seconds. A consumer answers `409` or `422` for a conflicting payload or an invalid schema, and the Broker does not retry it. Neither the Broker nor a consumer drops a failed event. A redelivery keeps the original IDs and remains idempotent.

The topic allowlists grant each producer and subscriber only the topics it needs. Only the Applicant, Credential, and University Record services can read hidden `CaseInitialized` payloads. A service retains an outbox entry until the Broker answers its publish with `200` or `201`. A consumer commits its domain update and inbox record before it answers a delivery. The service retains inbox and domain deduplication records for as long as the related domain records exist.

Before the [migration](queues.md#migration), RabbitMQ carried these events on the topic exchanges `student-id.events.v1` and `student-id.events.v2`, with routing keys `case.initialized`, `decision.scored`, `shift.ended`, and `discipline.applied`.

Example scored event:

```json
{
  "event_id": "d75bfcbd-7c3d-4cc4-95f4-4f2f72bb1304",
  "event_type": "DecisionScored",
  "schema_version": 1,
  "occurred_at": "2026-09-10T10:00:00Z",
  "producer": "moderation",
  "correlation_id": "6b836035-a523-4269-a009-d0a48b3dca0b",
  "payload": {
    "decision_id": "5bbd83b2-c020-4a86-b865-cb3300d360de",
    "session_id": "a5ece187-b773-480f-a777-6626b7fbeb57",
    "case_id": "6b836035-a523-4269-a009-d0a48b3dca0b",
    "moderator_id": "e933b2da-19bb-46b1-a0d5-abb66c359034",
    "action": "accept",
    "correct": true,
    "score_delta": 10,
    "penalty": 0
  }
}
```
