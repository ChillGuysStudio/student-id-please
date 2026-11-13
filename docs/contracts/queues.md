# Message Broker queues and topics contract

This contract adds two kinds of queues to the [Message Broker](broker.md). A targeted queue carries a request whose caller knows the destination service. A topic queue carries a domain event whose producer does not know who consumes it. The [domain events contract](events.md) still defines the event names, schemas, producers, and consumer rules. The [discovery and resilience contract](resilience.md) still defines registration, lookup, and failure accounting.

The Broker implements both kinds in Go. Topic queues keep their state in the Broker's own PostgreSQL, `broker-db`. Domain services never connect to `broker-db`. RabbitMQ leaves the stack when the [migration](#migration) completes.

The [gRPC contract](grpc.md#events) replaces the REST publish and delivery endpoints with `BrokerService.PublishEvent` and `EventConsumerService.DeliverEvent`, and the topic listing with `BrokerService.ListTopics`. The commit, acknowledgement, retry, and storage rules below do not change.

## Targeted queues

Every request that the Broker dispatches to a replica enters the queue of its destination service. This covers Gateway dispatch with `X-Broker-Target`, service ingress after the route table selects the target, and the Broker's own policy reads. Each logical service has one queue. Replicas do not have their own queues.

Targeted requests stay in memory. The Broker holds the caller's HTTP request open while the request waits, so a Broker restart fails the waiting requests and loses nothing that a caller considers accepted.

| Setting | Default | Meaning |
| --- | --- | --- |
| `BROKER_QUEUE_CAPACITY` | `100` | Waiting requests per destination service. A positive integer. |
| `BROKER_REPLICA_MAX_IN_FLIGHT` | `32` | The upper bound on concurrent dispatched requests per replica generation. The slot limit of each generation is its `capacity` from the [load formula](routing.md#load), which never exceeds this value. A positive integer. |

The queue works in this order:

1. The request passes the existing admission gate, authentication, route, and policy checks in [service ingress](broker.md#service-ingress) or [Gateway dispatch](broker.md#gateway-dispatch).
2. If the service has no eligible instance, the Broker returns `503 NO_HEALTHY_INSTANCES` and queues nothing. If the queue already holds `BROKER_QUEUE_CAPACITY` requests, the Broker returns `503 QUEUE_FULL` at once.
3. Otherwise the request waits. The Broker starts requests in arrival order. A request pinned to a DMs instance waits only for that instance and does not block requests behind it.
4. When a replica has a free slot, the Broker takes the oldest request that the replica can serve and selects the instance by the [load and breaker rules](routing.md#selection). The cursor skips an instance whose slots are all in use. Selection happens at dispatch, not at enqueue, so a breaker exclusion or a new replica applies to requests that are already waiting.
5. The Broker sends one attempt and writes the response to the waiting caller. A [reroute](routing.md#rerouting) re-enters this queue at its original arrival position, ahead of later requests, and makes at most one reroute to another instance, for at most two attempts in total. It does not count against `BROKER_QUEUE_CAPACITY`.

Each queued request carries its `attempt_id` and a one-shot reply slot. The attempt's response goes only to that slot, so replies cannot cross between callers. A reply that arrives after the caller left is discarded and logged with `outcome: "abandoned"`.

The [time budget](broker.md#admission-and-time-budget) does not change. The Broker answers within `T - 250 ms` of receipt, and queue wait counts against that budget. A request still waiting when the budget runs out leaves the queue with `503 QUEUE_TIMEOUT`. A dispatched attempt's deadline is the remaining budget, capped by the signed authority expiry, as before.

Both queue responses carry `Retry-After: 1` and `X-Broker-Failure-Origin: none`. No backend attempt happened, so no instance counter moves. The caller does not count them against the Broker, because a busy destination is not a Broker failure. The admission gates keep `503 TASK_LIMIT_EXCEEDED` with origin `broker`.

Every physical attempt to a replica holds one of its `capacity` slots until the response body is consumed or the attempt fails. A cycle of nested calls under saturation therefore ends in `QUEUE_TIMEOUT` within the budget and cannot wait forever. Completion order is not guaranteed. Gateway public dispatch passes both codes to clients as `503` with their `Retry-After`.

## Topics

The topics are the four existing events. A topic name equals its `event_type`. The Broker accepts only the current schema version of each topic.

| Topic | `schema_version` | Producers | Subscribers |
| --- | --- | --- | --- |
| `CaseInitialized` | `2` | `applicant`, `credential`, `university_record` | `applicant`, `credential`, `university_record` |
| `DecisionScored` | `1` | `moderation` | `session` |
| `ShiftEnded` | `1` | `session` | `player` |
| `DisciplinaryActionApplied` | `1` | `moderation` | `player` |

The producer and subscriber columns are allowlists of registry names. The Broker rejects a publish from any other producer. Discovery rejects a registration that declares a topic outside its service's subscriber allowlist. The Broker also ignores such a pair if one reaches it. Only Applicant, Credential, and University Record can therefore receive hidden `CaseInitialized` payloads. Rules, DMs, Gateway, and the Broker subscribe to nothing.

Discovery and the Broker each hold this table in code. A change to it changes this contract, [events.md](events.md), Discovery, and the Broker together.

## Publish

A producer's outbox relay publishes one event per request:

```text
POST /internal/v1/topics/{topic}/events
Content-Type: application/json
X-Service-Name: <producer caller name>
X-Service-Token: <BROKER_SERVICE_TOKEN>

<Event envelope from events.md>
```

The caller credential is the producer's existing Broker credential. The Moderation publisher process uses Moderation's. Caller names map to registry names through `BROKER_CALLER_NAMES`, so `university-record` publishes as `university_record`. The request carries no actor grant and no `Idempotency-Key`. The envelope's `event_id` is the idempotency key. The existing 1 MiB body limit applies.

The Broker handles the path before the internal route table. It runs on the service ingress gate. The Broker checks the request in this order:

1. The caller authenticates. Gateway is not a producer.
2. `{topic}` is in the catalogue.
3. The caller's registry name is in the topic's producer allowlist.
4. The body is a JSON object with every envelope field. `event_id` and `correlation_id` are UUIDs, `occurred_at` is a `Time`, `payload` is an object, `event_type` equals `{topic}`, `schema_version` equals the topic's version, and `producer` equals the caller's registry name. The Broker does not validate the payload schema. Consumers own that.
5. In one transaction, the Broker inserts the event and one delivery row for each current subscriber of the topic, then commits.

| Status and code | Meaning | Relay action |
| --- | --- | --- |
| `201` | Committed now. Body `{event_id, topic, deliveries: Int}` | Mark the outbox row confirmed |
| `200` | This `event_id` was already committed with an equal envelope. Same body as the first commit | Mark the outbox row confirmed |
| `400 INVALID_REQUEST` | Malformed JSON or duplicated private headers | Keep the row, back off |
| `401 UNAUTHORIZED` | Caller authentication failed | Keep the row, back off |
| `403 TOPIC_FORBIDDEN` | The caller may not publish this topic, or `producer` is not the caller | Keep the row, back off |
| `404 UNKNOWN_TOPIC` | `{topic}` is not in the catalogue | Keep the row, back off |
| `409 EVENT_ID_CONFLICT` | This `event_id` exists with a different envelope | Keep the row, back off, log `ERROR` |
| `422 INVALID_EVENT` | The envelope fails step 4 | Keep the row, back off |
| `503 STORE_UNAVAILABLE` | `broker-db` failed. The commit may or may not have happened | Keep the row, back off |
| `503 TASK_LIMIT_EXCEEDED` | The service ingress gate is full | Keep the row, back off |

A `200` or `201` means the event and its deliveries are committed in `broker-db`. Nothing else confirms an outbox row. The Broker compares envelopes as `jsonb` values, so key order and whitespace do not matter. A retry after an uncertain result, including a timeout, sends the same `event_id` and receives `200` if the first attempt committed. `503` responses carry `Retry-After: 1`.

Responses carry the `X-Broker-*` attribution headers. `STORE_UNAVAILABLE` and `TASK_LIMIT_EXCEEDED` have origin `broker`, and the others have origin `none`. Relays back off 1, 5, then 30 seconds, capped at 30 seconds, and keep the original `event_id`. A relay is a background loop with no waiting caller, so it does not count publish failures in a Broker hop counter and never reports the Broker to Discovery. Each publish is still one bounded attempt with deadline `T` and no hidden retry.

An event published while a topic has no subscribers commits with `deliveries: 0`. No later subscriber receives it.

## Push delivery

Each subscriber service's pending deliveries form its topic queue. The Broker pushes each delivery to exactly one ready replica of that service, so the replicas compete for the queue. Every subscriber service receives its own copy.

```text
POST /internal/v1/events/{topic}
Content-Type: application/json
X-Service-Name: message-broker
X-Service-Token: <receiver hop token from BROKER_RECEIVERS>
X-Gateway-Assertion: <Broker-signed workload assertion>
Idempotency-Key: <event_id>
X-Request-ID: <event_id>
X-Event-Id: <event_id>
X-Event-Topic: <topic>
X-Event-Producer: <producer registry name>
X-Delivery-Attempt: <1, 2, ...>

<the stored envelope>
```

The hop credential and the assertion follow the existing [receiver rules](broker.md#assertions). The assertion is a `gateway-workload+jwt` with `iss=student-id-broker`, `kid=broker-v1`, `azp` set to the producer's caller name, and `aud` set to the subscriber's configured audience. It binds `POST`, the path, the body hash, and the `Idempotency-Key` hash, and it lives 30 seconds. The Broker signs a new one for each attempt.

A consumer accepts the delivery only when all of these hold:

- The hop and the assertion verify by the receiver rules.
- `azp` maps to the envelope's `producer`, and that producer is in the topic's producer allowlist.
- `{topic}` is a topic the consumer declares, and `X-Event-Id`, `X-Event-Topic`, and `X-Event-Producer` equal the body's values.

The verified `azp` is the authenticated producer for [retained initialization authority](cases.md#retained-initialization-authority). It replaces the RabbitMQ `user_id` check and the `BROKER_PRODUCERS` map.

The consumer commits its domain update and its inbox record before it responds. It deduplicates by `event_id` and by the business ID, exactly as it does today, because the Broker can deliver an event more than once.

| Consumer response | Broker action |
| --- | --- |
| `200` or `204` | The delivery is done. This includes a duplicate the consumer had already applied. |
| `409` or `422` | The delivery is dead-lettered and not retried. Use it for a conflicting payload or an invalid schema, as [events.md](events.md) requires. |
| Any other status, a connection error, a timeout, or an invalid response | The delivery is retried. |

A retry waits 1, 5, then 30 seconds after the failed attempt, then every 30 seconds. The [dead-letter contract](dead-letters.md) limits the attempts and moves rejected and exhausted deliveries to the `dead_letters` table. A timed-out attempt is uncertain, and the consumer's deduplication makes its retry safe.

Each attempt is one physical backend attempt. Its deadline is `T`. It records into the replica's breaker counter with the same qualifying failures as a dispatch, and three of them trip the breaker. The Broker reads at most 64 KiB of the response body and ignores its content.

The Broker pushes a delivery only to a ready, leased, non-excluded replica whose own registration declares the topic. It orders replicas by [load](routing.md#selection), with the service's round-robin cursor for ties. `BROKER_DELIVERY_REPLICA_IN_FLIGHT`, default `2`, caps concurrent deliveries per replica generation. These slots are separate from the targeted queue's slots, so event delivery cannot starve requests. A subscriber with no eligible replica keeps its deliveries pending.

Topic queues guarantee no order. The Broker claims the oldest due deliveries first, but parallel replicas and retries reorder them. Consumers must not depend on order.

## Storage

The Broker connects with `BROKER_DATABASE_URL`. At startup it applies its schema, then becomes ready. A later `broker-db` outage does not make the Broker unready, because targeted queues do not use it. During the outage, publishes return `STORE_UNAVAILABLE` and delivery pauses.

```text
events(
  event_id uuid primary key,
  topic text not null,
  producer text not null,
  envelope jsonb not null,
  published_at timestamptz not null)
deliveries(
  id bigserial primary key,
  event_id uuid not null references events,
  subscriber text not null,
  state text not null check (state in ('pending', 'in_flight', 'done', 'dead_lettered')),
  attempts int not null default 0,
  next_attempt_at timestamptz not null,
  lease_until timestamptz,
  last_status int,
  last_error_kind text,
  last_instance_id uuid,
  finished_at timestamptz,
  unique (event_id, subscriber))
subscriptions(
  topic text not null,
  subscriber text not null,
  since timestamptz not null,
  primary key (topic, subscriber))
```

Index `deliveries (subscriber, next_attempt_at) where state in ('pending', 'in_flight')`. The Broker sends the stored `envelope::text` on every attempt, so each consumer sees the same bytes each time.

A delivery worker claims due rows for one subscriber and the topics that a free replica declares:

```sql
UPDATE deliveries d SET state = 'in_flight', attempts = d.attempts + 1,
       lease_until = now() + $lease, last_instance_id = $instance
FROM events e
WHERE d.event_id = e.event_id AND d.id IN (
  SELECT d2.id FROM deliveries d2 JOIN events e2 USING (event_id)
  WHERE d2.subscriber = $subscriber AND e2.topic = ANY($topics)
    AND (d2.state = 'pending' AND d2.next_attempt_at <= now()
         OR d2.state = 'in_flight' AND d2.lease_until < now())
  ORDER BY d2.next_attempt_at, d2.id
  LIMIT $n FOR UPDATE OF d2 SKIP LOCKED)
RETURNING d.id, d.event_id, d.attempts, e.topic, e.envelope::text;
```

The lease is `T` plus one second. A success sets `done` and `finished_at`. A `409` or `422` moves the delivery to `dead_letters`. Any other failure sets `pending` with the next backoff time, `last_status`, and `last_error_kind`, until the [attempt limit](dead-letters.md#retry-policy) moves it to `dead_letters`. After a Broker restart, an expired `in_flight` row becomes claimable again. `SKIP LOCKED` keeps two workers from claiming one row. The Broker wakes the subscriber's worker after each commit and also polls every second.

## Subscriptions

Each registration declares the topics its service consumes. The Broker derives the logical subscribers from the live registry and stores them in `subscriptions`.

On each registry snapshot, the Broker updates `subscriptions` in one transaction for every service that has at least one ready instance in the snapshot:

- The service's topics are the union of the topics its ready instances declare, filtered by the subscriber allowlist.
- The Broker inserts the missing rows and deletes the rows outside that union.

A service with no ready instance keeps its rows. A restart, a scale to zero, a lease expiry, or an empty registry after a Discovery restart is not a change of interest. Events published meanwhile wait for the service in its queue. Only a ready instance that declares a different list changes the service's topics. An instance without a `topics` field, from an older Discovery, makes the Broker skip that service for that snapshot.

When a subscription row is deleted, the Broker creates no new deliveries for it. Pending deliveries stay pending and resume if the interest returns. A subscriber receives the events committed after its row exists. An event committed before then does not reach it.

## Discovery changes

`Registration` gains an optional `topics: string[]`. A missing field means `[]`. Discovery accepts the field and stores it sorted. It returns `422` for a name that is not in the catalogue, a duplicate name, or a non-array value. It returns `403 TOPIC_FORBIDDEN` for a topic outside the service's subscriber allowlist. Each domain service sends the field, even when it is empty.

`Instance` gains `topics: string[]`, so lookup returns each instance's topics.

Topic lifecycle follows the instance:

- A renewal can change `topics` within one boot. Discovery updates the list, keeps `registration_id`, increments `revision`, and logs `registration_changed` at `INFO` with the old and new lists. Changed addresses still conflict.
- A new boot registers its own list.
- An expired, removed, or shut-down instance leaves default lookup, so its topics no longer count.
- Removal records do not store topics. After a Discovery restart, renewals restore them.

The Broker reads topics from its existing one-second snapshot refresh. No other Discovery endpoint is added.

## Topic listing

The Broker serves `GET /internal/v1/topics` to the `gateway` and `operator` control principals. Other authenticated principals receive `403 FORBIDDEN`. At most two listings run at once. Gateway exposes it to administrators as `GET /api/v1/admin/broker/topics`, verified like `GET /api/v1/admin/logs`. Gateway makes one fixed call with its control credential, forwards no client path, query, or header, allows 3 seconds, and accepts at most 64 KiB. Any other Broker result returns `503 DEPENDENCY_UNAVAILABLE`.

The listing is built from current state and contains no payloads or event IDs:

- `topics`: every catalogue topic with its `producers` and one entry for each allowed subscriber. Each entry gives `subscribed` (a `subscriptions` row exists), `ready_instances` (ready instances whose registration declares the topic), and `deliveries`, the pending, in-flight, done, and dead-lettered counts.
- `targeted_queues`: each destination service with its current `depth` and `capacity`.
- `threads`: the `active` request threads and their `max`.

If `broker-db` does not answer within one second, the listing still returns `200` with `store_available: false` and `null` subscription and delivery values. If the registry snapshot is unusable, `registry_available` is `false` and `ready_instances` is `null`.

## Logging

The Broker writes these [logging contract](logging.md) records:

| `event` | Level | When | Fields besides the common ones |
| --- | --- | --- | --- |
| `event_published` | `INFO`, `WARN` when rejected | Each publish request | `event_type`, `event_id`, `producer`, `deliveries`, `status`. `outcome` is `published`, `duplicate`, or `rejected`, with `error_kind` when rejected. |
| `delivery` | `INFO` when done, `WARN` otherwise | Each delivery attempt | `event_type`, `event_id`, `target_service`, `target_instance_id`, `registration_id`, `attempt_id`, `attempt`, `status`. `outcome` is `delivered`, `retry`, or `dead_lettered`, with `error_kind` on failure. |
| `dispatch` | As before | Each targeted attempt | Adds `queue_ms`, the time the request waited. |
| `queue_rejected` | `WARN` | `QUEUE_FULL` or `QUEUE_TIMEOUT` | `target_service`, `caller`, `route`, `error_kind`. |

Consumers keep writing `event_consumed` with `processed`, `duplicate`, or `rejected` and add `attempt` from `X-Delivery-Attempt`. Producers write `event_published` when the Broker confirms. `event_id` correlates the records. Records never contain the envelope or payload.

## Migration

The cutover moves every producer and consumer in one CPR integration. It does not run RabbitMQ and the Broker side by side.

1. Release Discovery with `topics` first. Older registrants keep working.
2. Release the Broker with `broker-db`, publish, and delivery. It also removes the unagreed `/internal/v1/player/events` and `/internal/v1/session/events` routes, so events reach consumers only through topics.
3. Release each domain service with its consumer endpoint, its declared topics, and its relay publishing to the Broker. Each release removes its RabbitMQ client, queue declarations, retry and dead-letter queues, and `RABBITMQ_URL`.
4. Before the CPR integration deploys, drain the running stack. Stop new gameplay, then wait until every RabbitMQ queue, including `.retry.*` and `.dlq` queues, reports zero messages in `rabbitmqctl list_queues name messages`. If a `.dlq` holds messages, stop and resolve them first. Outbox rows that RabbitMQ never confirmed need no drain, because the new relays publish every unconfirmed row to the Broker with its original `event_id`.
5. Deploy the integration. Start the stack and wait until `subscriptions` lists every allowed pair from the [topics table](#topics) before gameplay resumes. Check it with `docker compose exec broker-db psql -U broker -c 'select * from subscriptions'`.
6. In the same integration, Compose drops the `rabbitmq` service, its `broker-data` volume, `scripts/start_broker.sh`, every `depends_on: rabbitmq`, and every `RABBITMQ_URL` and `BROKER_PRODUCERS` setting. `scripts/setup.py` drops `RABBITMQ_PASSWORD` and the three `*_BROKER_PASSWORD` values.

A clean checkout has no RabbitMQ state, so steps 4 and 5 reduce to waiting for `subscriptions`.

## Repository changes

| Repository | Change | Work |
| --- | --- | --- |
| Message Broker | Code | Per-service targeted queues with `BROKER_QUEUE_CAPACITY` and `BROKER_REPLICA_MAX_IN_FLIGHT`, `QUEUE_FULL` and `QUEUE_TIMEOUT`, and `queue_ms`. The topic catalogue, publish endpoint, `broker-db` schema, subscription derivation, delivery workers, push signing, and logs. Remove the two unagreed event routes. |
| Discovery | Code | `topics` in `Registration` and `Instance`, catalogue and allowlist validation, topic changes on renewal, and `registration_changed`. `decodeRegistration` in `cmd/discovery/registry_http.go` accepts four or five fields. |
| Gateway | None | No RabbitMQ use. Public dispatch passes `QUEUE_FULL` and `QUEUE_TIMEOUT` through. Realtime negotiation maps them to `503 REALTIME_UNAVAILABLE`. Verify both. |
| Player | Code | `POST /internal/v1/events/{topic}` for `ShiftEnded` and `DisciplinaryActionApplied`, replacing `POST /internal/v1/events`. Declare both topics. Remove the RabbitMQ worker and its readiness check. |
| Session | Code | Relay `ShiftEnded` to the Broker from its own loop instead of the consumer loop. `POST /internal/v1/events/DecisionScored`, replacing `POST /internal/v1/events`. Declare `DecisionScored`. Remove RabbitMQ and the unused Player event client. |
| Moderation | Code | The publisher process relays `DecisionScored` and `DisciplinaryActionApplied` to the Broker as `moderation`. Declare `[]`. Remove pika. |
| Applicant | Code | Relay `CaseInitialized` to the Broker. `POST /internal/v1/events/CaseInitialized` into the existing inbox, with `azp` as the authenticated producer. Declare `CaseInitialized`. Remove `RabbitCaseTransport` and `BROKER_PRODUCERS`. |
| Credential | Code | Same as Applicant. |
| University Record | Code | Same as Applicant. |
| Server Rules | Code | Declare `[]`. No events. |
| Discord DMs | Code | Declare `[]`. No events. |
| CPR | Config | Add `broker-db` (`postgres:17-alpine`, volume `broker-db-data`, `pg_isready` healthcheck). Set `BROKER_DATABASE_URL` and make `message-broker` depend on `broker-db`. Give `moderation-publisher` `BROKER_URL` and Moderation's `BROKER_SERVICE_TOKEN`. Generate `BROKER_DB_PASSWORD` in `scripts/setup.py`. Remove RabbitMQ as in [migration](#migration) step 6. Record the released images. |

## Verification

Each repository tests its own side. The Broker tests queue capacity, queue timeout, the pinned request that does not block others, publish idempotency and conflicts, the allowlists, the claim with a restart, and the delivery outcomes. Discovery tests topic validation, a forbidden pair, and a topic change on renewal. Each consumer tests a duplicate delivery, a wrong producer, and a mismatched header.

The released stack passes these checks with real services and no RabbitMQ:

- A full targeted queue returns `503 QUEUE_FULL` with `Retry-After`, and targeted requests keep their replies and deadlines.
- One `CaseInitialized` produces three deliveries, one each to Applicant, Credential, and University Record. With two replicas of each, every service applies it once.
- While Player runs a release that declares no topics, a `ShiftEnded` commits with no Player delivery. After Player's new release registers the topic, `subscriptions` shows the row, and the next `ShiftEnded` reaches Player without a Session change.
- A registration that declares `CaseInitialized` for `player` is rejected with `403`.
- A consumer replica stopped mid-delivery leaves the delivery pending, and another replica completes it. Restarting the Broker with volumes preserved loses no committed event.
- The [dispatch contract](broker.md#verification) checks for routing, breakers, and public flows still pass.
