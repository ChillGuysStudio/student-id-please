# Player and Session Lab 1 contract additions

These additions describe the Player and Session review builds. Existing domain paths, field names, event payloads, routing keys, and XP rules remain as defined in the common README.

## Runtime endpoints

| Owner | Method and path | Caller | Request | Success response |
| --- | --- | --- | --- | --- |
| Player | `GET /.well-known/jwks.json` | Anyone | None | `200 {keys: JWK[]}`. Public RSA keys only. JWK uses the standard JSON Web Key representation. |
| Player | `GET /health` | Anyone | None | `200 {status: "ok", service: "player"}` |
| Session | `GET /health` | Anyone | None | `200 {status: "ok", service: "session"}` |
| Player | `GET /ready` | Anyone | None | `200 {status: "ready", events: "rabbitmq" \| "http-fixtures"}` |
| Session | `GET /ready` | Anyone | None | `200 {status: "ready", player_mode: "http" \| "mock", external_services_mode: "http" \| "mock"}` |
| Session | `DELETE /api/v1/sessions/{session_id}` | Session owner while in lobby | None; `Idempotency-Key` required | `204`, no body. Active and historical shifts return `409 Error`. |
| Player | `POST /internal/v1/events` | Session or Moderation | `Event<ShiftEndedPayload>` or `Event<DisciplinaryPayload>`; `Idempotency-Key` required | `200 {event_id: Id, applied: Bool}` |
| Session | `POST /internal/v1/events` | Moderation | `Event<DecisionScoredPayload>`; `Idempotency-Key` required | `200 {event_id: Id, applied: Bool}` |

`Id` is a UUID string, and `Bool` is a Boolean. A configured database, cache, or broker that is unavailable causes readiness to return `503 Error`. The shared error object is `{code: string, message: string, request_id: Id, details: {field: string, reason: string}[]}`. FastAPI exposes `/docs` and `/openapi.json` for inspection.

## Internal authentication

Internal HTTP requests use `X-Service-Name` and `X-Service-Token`. Each receiver has a `SERVICE_TOKENS` JSON map. The receiver verifies the token for the named caller and checks that the caller is allowed to use the endpoint.

Player's internal reads and Session's context endpoint also require the initiating player's Bearer token. Session requires the `player_id` query to match that token's subject. Events use producer credentials instead of a player token. The event producer must match the authenticated service.

The Lab 1 demonstration should bind API ports to the loopback address when exposing them directly. Internal event adapters are for service calls and lab fixtures. A future gateway must not expose `/internal/v1` paths.

## End-shift behavior

Lab 1 returns `409 CASE_UNFINISHED` while a case is pending, undecided, or awaiting its scoring event. The owner retries after Session applies `DecisionScored`. Session then commits the ended state and one `ShiftEnded` outbox entry in one database transaction and returns `200 Session`.

Broker confirmation can occur later. `ended` means the final result is durable, not that Player has already applied the XP award. Player receives the event through RabbitMQ and deduplicates by event and business IDs. The `ending` enum value remains reserved and is not emitted by this implementation.

## Input limits

Player usernames contain 3 through 40 ASCII letters, digits, or underscores. Usernames and emails are normalized to lowercase. Passwords contain 10 through 128 characters. Team names and display names contain 1 through 80 characters. Session rosters contain at most 100 participants. Unknown client request fields return `422`.

Service consumers accept additional optional event fields for compatibility. The schema version remains `1`. Event timestamps include a timezone, integer scores use signed 32-bit values, and counts and penalties cannot be negative.

## Mock dependencies

Session's default `PLAYER_MODE=http` calls the real Player service. `EXTERNAL_SERVICES_MODE=mock` uses a fixed published ruleset, creates a stable university snapshot, distributes all record kinds among Junior Moderators, and returns deterministic case IDs with typed readiness responses. Any of the three initializer names can be selected.

Mock mode does not create applicant documents or evaluate admission policy. The demonstration supplies `DecisionScored` fixtures explicitly. Session still validates the Moderator, case state, scoring values, and duplicate IDs before changing its persistent totals.

`EXTERNAL_SERVICES_MODE=http` switches these adapters to the URLs in configuration. Invalid response shapes and unavailable dependencies return `503`. Initializer retries keep the persisted request ID, original entry service, and idempotency key.
