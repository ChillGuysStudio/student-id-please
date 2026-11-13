# Durable delivery and dead letters contract

This contract adds a finite retry policy and a dead-letter channel to topic delivery. It builds on the [queues and topics contract](queues.md) and the [gRPC contract](grpc.md). Everything those contracts define stays in force unless this document changes it.

## What is durable

Topic events are durable. The Broker commits an event and its deliveries to `broker-db` before `PublishEvent` returns `OK`, and it reloads pending and expired in-flight deliveries after a restart. Restarting the Broker or `broker-db` with their volumes kept loses no accepted event.

Targeted requests are not stored. A request that is waiting or running when the Broker stops fails for its caller with a connection error or `UNAVAILABLE`. The caller decides whether to retry under its own idempotency rules, as before.

Acknowledgement means that the next durable boundary committed:

| Step | Acknowledged when |
| --- | --- |
| Producer to Broker | `PublishEvent` returns `OK`, with `duplicate` true or false. The producer keeps its outbox row until then. |
| Broker to consumer | `DeliverEvent` returns `OK`. The consumer returns it only after its domain update and inbox record commit. |

Delivery is at least once. A lost `PublishEvent` reply is retried with the same `event_id` and an equal envelope, and the Broker answers `duplicate` true without new deliveries. A lost `DeliverEvent` reply, a consumer crash before it replies, or a Broker restart during an attempt leads to another attempt with the same `event_id`. Consumers deduplicate by `event_id` and by business ID, as they do today. Nothing in the stack claims exactly-once transport, and no step mints a new ID to hide an uncertain result.

## Retry policy

`BROKER_DELIVERY_MAX_ATTEMPTS`, default `5`, minimum `1`, maximum `20`, limits the attempts for one delivery. The waits after failed attempts stay 1, 5, then 30 seconds. With the default, the last attempt starts about 66 seconds after the first.

`attempts` counts claims. One claim is refunded: when the breaker excludes the selected replica before the Broker sends anything, the Broker restores the count and the delivery is due again at once. Every other claim counts, including a claim that failed before sending, such as a signing failure or a stored envelope that cannot be encoded. Those failures therefore end in `exhausted` instead of retrying forever. An attempt whose lease expired, for example because the Broker stopped, counts, because the consumer may have received it.

When `Claim` would reclaim an expired `in_flight` row whose `attempts` already equals the limit, it does not send it again. It moves the delivery to `dead_letters` with reason `exhausted` in the same transaction.

A subscriber service with no eligible replica keeps its deliveries `pending`. They are not claimed, so they use no attempts, and they are delivered when a replica becomes ready. Waiting for a consumer is not a retry.

| Attempt result | Broker action |
| --- | --- |
| `OK` | `done`. A duplicate the consumer already applied is also `OK`. |
| A status whose detail has `http_status` 409 or 422 | Dead-letter now with reason `rejected`. The consumer judged the event conflicting or invalid, so a retry cannot succeed. |
| The catalogue no longer allows the producer and subscriber pair | Dead-letter now with reason `forbidden_pair`. |
| Any other status, a connection error, or a timeout, and attempts are below the limit | `pending` with the next backoff. |
| The same, and this was the last allowed attempt | Dead-letter with reason `exhausted`. |

A delivery that fails does not hold up other deliveries. Each attempt still holds one replica delivery slot for at most `T`, and the Broker claims other due deliveries meanwhile. Other subscribers and other topics continue.

## Storage

Migration `002_dead_letters.sql` adds the table and the new delivery state:

```sql
CREATE TABLE dead_letters (
  id bigserial PRIMARY KEY,
  delivery_id bigint NOT NULL UNIQUE REFERENCES deliveries,
  event_id uuid NOT NULL REFERENCES events,
  topic text NOT NULL,
  producer text NOT NULL,
  subscriber text NOT NULL,
  reason text NOT NULL CHECK (reason IN ('rejected', 'exhausted', 'forbidden_pair')),
  attempts int NOT NULL,
  last_status int,
  last_error_kind text,
  last_instance_id uuid,
  published_at timestamptz NOT NULL,
  dead_lettered_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX dead_letters_topic ON dead_letters (topic, id);
CREATE INDEX dead_letters_subscriber ON dead_letters (subscriber, id);
```

`deliveries.state` accepts `dead_lettered` in place of `rejected`. The migration copies every existing `rejected` delivery into `dead_letters` and sets its state to `dead_lettered`, in one transaction. A row whose `last_error_kind` is `forbidden_pair` gets reason `forbidden_pair`. Every other row gets reason `rejected`.

The Broker moves a delivery in one transaction: it sets the delivery to `dead_lettered` while this attempt still holds the row, and it inserts the `dead_letters` row. A late result for a row that another attempt reclaimed changes nothing. The event row stays, because other subscribers may still need it. Nothing deletes dead letters, and nothing requeues them automatically.

## Dead-letter listing

The Broker serves `BrokerService.ListDeadLetters` to the `gateway` and `operator` control principals. Other authenticated callers receive `PERMISSION_DENIED FORBIDDEN`. At most two listings run at once. A third returns `UNAVAILABLE TASK_LIMIT_EXCEEDED`, which Gateway returns as `503 DEPENDENCY_UNAVAILABLE`.

| Request field | Rule |
| --- | --- |
| `page_size` | `1` to `100`. `0` means `20`. |
| `page_token` | Empty for the first page, otherwise a `next_page_token` from an earlier page. |
| `topic`, `subscriber` | Optional exact filters. A topic outside the catalogue or a service outside the subscriber allowlists returns `INVALID_ARGUMENT VALIDATION_ERROR`. |

Items are newest first, by `id`. `next_page_token` is empty on the last page. A malformed token returns `INVALID_ARGUMENT VALIDATION_ERROR`. If `broker-db` does not answer within one second, the call returns `UNAVAILABLE STORE_UNAVAILABLE`.

Each item holds `dead_letter_id`, `event_id`, `topic`, `producer`, `subscriber`, `reason`, `attempts`, `last_status`, `last_error_kind`, `last_instance_id`, `published_at`, and `dead_lettered_at`. It never holds the envelope, the payload, the correlation ID, or any credential. `event_id` lets an administrator follow the event through the logs.

Gateway exposes the listing to administrators:

```text
GET /api/v1/admin/broker/dead-letters?limit=Int&cursor=String&topic=String&subscriber=String
```

Gateway verifies the administrator like `GET /api/v1/admin/broker/topics`. It accepts only these four query parameters. `limit` maps to `page_size`, and `cursor` to `page_token`. It validates their form, rejects anything else with `400 VALIDATION_ERROR`, and makes one call with its control credential. It allows 3 seconds and accepts a response of at most 256 KiB. A Broker `INVALID_ARGUMENT` returns `400 VALIDATION_ERROR`. Any other Broker failure returns `503 DEPENDENCY_UNAVAILABLE`. Anonymous callers receive `401` and authenticated non-administrators `403`.

```json
{
  "items": [
    {
      "dead_letter_id": "17",
      "event_id": "0b6b3b9e-7d0c-4b8e-9c55-2f1a3c4d5e6f",
      "topic": "DecisionScored",
      "producer": "moderation",
      "subscriber": "session",
      "reason": "rejected",
      "attempts": 1,
      "last_status": 422,
      "last_error_kind": "http_4xx",
      "last_instance_id": "2c9d6f0e-1a2b-4c3d-8e9f-0a1b2c3d4e5f",
      "published_at": "2026-11-13T10:00:00Z",
      "dead_lettered_at": "2026-11-13T10:00:01Z"
    }
  ],
  "next_cursor": null
}
```

The topic listing's `deliveries` counts become `pending`, `in_flight`, `done`, and `dead_lettered`. `dead_lettered` replaces `rejected`.

## Logging

The attempt's `delivery` record has `outcome` `dead_lettered` when it moves the delivery. The move also logs one `WARN` record with event `dead_lettered`, `event_id`, `topic`, `producer`, `subscriber`, `reason`, `attempts`, `last_status`, and `last_error_kind`. It never logs the envelope or payload. A listing logs the usual `rpc_request` record.

## Producers and consumers

No service changes its event path. Each producer and consumer must already behave as below. Each repository verifies it and fixes only a real gap:

- Producers keep the outbox row until `PublishEvent` returns `OK`, retry with the same `event_id` and an equal envelope, and back off on every other result.
- Consumers commit the domain update and inbox record before returning `OK`, return `OK` without a second effect for a duplicate, return a detailed 422 for an invalid payload and a detailed 409 for a conflicting one, and return a retryable status for a transient failure.

| Topic | Producers | Subscribers |
| --- | --- | --- |
| `CaseInitialized` | Applicant, Credential, University Record | Applicant, Credential, University Record |
| `DecisionScored` | Moderation | Session |
| `DisciplinaryActionApplied` | Moderation | Player |
| `ShiftEnded` | Session | Player |

## Repository changes

| Repository | Change |
| --- | --- |
| Message Broker | Migration `002`, the attempt limit, the breaker-exclusion refund, the reclaim check at the limit, the dead-letter transaction, `ListDeadLetters`, the `dead_lettered` count, the `dead_lettered` log record, and tests. Vendor the updated `broker.proto`. |
| Gateway | `GET /api/v1/admin/broker/dead-letters`, the `dead_lettered` count in the topic listing, and tests. Vendor the updated `broker.proto`. |
| Producers and consumers | Verification against this section. Change only what fails it. |
| CPR | This contract, `broker.proto`, the demonstration commands, Postman checks for the listing's denials and success, and the image pins. |

## Verification

On the released stack:

- With a subscriber stopped, publish events, restart the Broker and `broker-db` with volumes kept, and start the subscriber. Every accepted event arrives once, and none is lost.
- Pause a consumer replica while it holds a delivery, so the attempt times out. The retry reaches a replica with the same `event_id`, and the business effect happens once.
- Publish an event twice with the same `event_id` and envelope. The second call returns `duplicate` true and creates no deliveries.
- Publish an event whose payload the consumer rejects. It is dead-lettered at once with reason `rejected`.
- Make one consumer fail retryably for every attempt. Its delivery is dead-lettered with reason `exhausted` after `BROKER_DELIVERY_MAX_ATTEMPTS` attempts, while the other subscribers of the same event and other topics continue.
- The listing pages correctly, returns no payload, and denies anonymous and non-administrator callers.
- Earlier grades' regression checks pass.
