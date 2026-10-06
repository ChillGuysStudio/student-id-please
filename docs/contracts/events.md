# RabbitMQ events

The payload types come from the [domain contract](domain.md), [case initialization](cases.md), and [service APIs](api.md).

All events use the durable topic exchange `student-id.events.v1`. Messages use JSON and RabbitMQ persistent delivery. Publishers wait for broker confirms, and consumers acknowledge messages after processing. The `schema_version` is `1`. The event names, routing keys, and payload fields below are fixed. Removing or changing a field requires a new major schema and exchange version. Consumers accept additional optional fields.

```text
Event<T> = {event_id: Id, event_type: string, schema_version: Int,
            occurred_at: Time, producer: "applicant" | "credential" | "university_record" |
            "moderation" | "session", correlation_id: Id, payload: T}
// CaseInitializedPayload is the three-variant union in the initialization section.
DecisionScoredPayload = {decision_id: Id, session_id: Id, case_id: Id, moderator_id: Id,
                        action: Action, correct: Bool, score_delta: Int, penalty: Int}
ShiftEndedPayload = {session_id: Id, participant_ids: Id[], processed_count: Int,
                     score: Int, penalties: Int, ended_at: Time}
DisciplinaryPayload = {disciplinary_action_id: Id, player_id: Id, xp_penalty: Int,
                       reason: string}
```

| Event | Routing key | Producer | Durable subscriber queues | Payload and correlation |
| --- | --- | --- | --- | --- |
| `CaseInitialized` | `case.initialized` | Applicant, Credential, or University Record | `applicant.case-initialized.v1`<br>`credential.case-initialized.v1`<br>`university-record.case-initialized.v1` | `CaseInitializedPayload`<br>`correlation_id = case_id` |
| `DecisionScored` | `decision.scored` | Moderation | `session.decision-scored.v1` | `DecisionScoredPayload`<br>`correlation_id = case_id` |
| `ShiftEnded` | `shift.ended` | Session | `player.shift-ended.v1` | `ShiftEndedPayload`<br>`correlation_id = session_id` |
| `DisciplinaryActionApplied` | `discipline.applied` | Moderation | `player.discipline-applied.v1` | `DisciplinaryPayload`<br>`correlation_id = disciplinary_action_id` |

Each subscriber has its own queue. Replicas of one service share that service's queue. An initializer can consume its own case event as a deduplicated no-op, but it never republishes a consumed initialization event. A publication retry uses the original `event_id`. Consumers also deduplicate by the business ID in the payload. This protects against a producer that assigns two event IDs to one case, decision, shift, or disciplinary action.

After a temporary failure, delayed queues retry the message after 1, 5, and 30 seconds. If all retries fail, the message moves to `<subscriber-queue>.dlq`, a durable queue for inspection and replay. A message with an invalid schema or a conflicting payload moves there without a retry. A replay keeps the original IDs and remains idempotent. A consumer never drops a failed message or requeues it without a retry limit.

Broker credentials grant publishers and consumers access only to the exchanges and queues they need. Only the Applicant, Credential, and University Record services can read hidden `CaseInitialized` payloads. A service retains an outbox entry until the broker confirms it. The service retains inbox and domain deduplication records for as long as the related domain records exist.

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
