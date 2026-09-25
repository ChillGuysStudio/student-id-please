# Server Moderation Session Service integration contract

Session owns moderation shift lifecycle, participants and roles, case references, aggregate score, and penalties. The [CPR communication contract](../../README.md#communication-contract) defines the shared REST, event, and case-initialization rules. The [private Session repository](https://github.com/Tirppy/student-id-session-service) contains the implementation and source run instructions. This page describes its integration and the published image's Lab 1 deployment.

## Responsibilities and lifecycle

| Resource | Owner's operations | Boundary |
| --- | --- | --- |
| Lobby and roster | Create, list, join, assign roles, delete a lobby | Player owns accounts and team membership. |
| Shift | Start, read, and end | Rules owns rule definitions; University Record owns snapshot contents. |
| Current case | Reserve one initializer, store its returned case ID, poll readiness | Applicant, Credential, and University Record own the case data. |
| Score | Count applied `DecisionScored` events and publish `ShiftEnded` | Moderation owns admission decisions; Player owns XP. |

The valid statuses are `lobby`, `active`, `ending`, and `ended`. The Lab 1 implementation does not enter `ending`; it returns `409` while a case or scoring event remains unfinished, then commits `ended` and returns `200`. A shift has exactly one Moderator and needs at least two Junior Moderators before it starts.

## Dependencies

| Interaction | Purpose |
| --- | --- |
| Session reads Player and Team | Confirm that participants exist and remain team members. |
| Session reads Server Rules | Pin one published rule version at shift start. |
| Session reads University Record permissions | Verify that record kinds are distributed across Junior Moderators. |
| Session creates a University snapshot | Pin immutable reference data for the shift. |
| Session calls one case initializer | Applicant, Credential, or University Record creates the case ID and its domain data. |
| Session polls all three case services | Keep a case pending until all local records are ready. |
| Moderation sends `DecisionScored` | Update the current case and aggregate totals once. |
| Session sends `ShiftEnded` to Player | Award persistent progression after the final result commits. |
| Session uses PostgreSQL | Persist shifts, cases, idempotency records, and event inbox/outbox rows. |
| Session uses Redis | Cache live views without making Redis the source of roles or scores. |

Other services call Session's context endpoint to verify shift participation and roles. Session returns a snapshot ID, not hidden university data. It never copies applicant claims, credentials, rules, decisions, or chat messages into its own domain tables.

## Data types

`Id` is a UUID string, `Int` is a signed 32-bit integer, and `Time` is an RFC 3339 UTC timestamp. `Id | null` denotes a present nullable field. The [shared types](../../README.md#shared-domain-types) define the full case and event payloads.

```text
Role = "moderator" | "junior_moderator"
Participant = {player_id: Id, role: Role}
Session = {session_id: Id, team_id: Id, owner_id: Id,
           status: "lobby" | "active" | "ending" | "ended",
           participants: Participant[], rule_version: Id | null,
           started_at: Time | null, university_snapshot_id: Id | null,
           current_case_id: Id | null, processed_count: Int,
           score: Int, penalties: Int}
CaseStatus = {case_id: Id, session_id: Id, state: "pending" | "ready",
              ready_services: ("applicant" | "credential" | "university_record")[]}
SessionContext = {session: Session, player: Participant}
```

Scores can be negative. Processed counts and penalties cannot be negative. The Moderator role comes from the Session roster; a client cannot claim it in a request header.

## HTTP API

Public endpoints require a player Bearer token. Mutations require a UUID `Idempotency-Key`. Lists use `limit` and `cursor` and return `Page<T>`.

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/sessions` | Team member | Team ID | `201 Session` |
| `GET /api/v1/sessions` | Player | Pagination | `200 Page<Session>` for the caller |
| `POST /api/v1/sessions/{session_id}/participants` | Same team member | Empty object | `200 Session` |
| `PUT /api/v1/sessions/{session_id}/roles` | Session owner | Complete participant roster | `200 Session` |
| `GET /api/v1/sessions/{session_id}` | Participant | None | `200 Session` |
| `POST /api/v1/sessions/{session_id}/start` | Session owner | Empty object | `200 Session` with pinned rule and snapshot IDs |
| `POST /api/v1/sessions/{session_id}/cases` | Assigned Moderator | Selected entry service | `202 CaseStatus` |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` | Participant | None | `200 CaseStatus` |
| `POST /api/v1/sessions/{session_id}/end` | Session owner | Empty object | `200 Session` in `ended` state |
| `DELETE /api/v1/sessions/{session_id}` | Session owner, lobby only | None | `204` |
| `GET /internal/v1/sessions/{session_id}/context` | Authorized service | Player ID query | `200 SessionContext` |
| `POST /internal/v1/events` | Moderation | `DecisionScored` event | `200 {event_id: Id, applied: Bool}` |
| `GET /health` | Anyone | None | `200` process health |
| `GET /ready` | Anyone | None | `200` when configured dependencies are ready |

The internal context endpoint requires `X-Service-Name`, `X-Service-Token`, and the initiating player's Bearer token. Its `player_id` query must match the verified token subject. The internal event adapter authenticates Moderation as the producer. FastAPI serves `/docs` and `/openapi.json`.

### Outbound REST calls

Session owns none of the data returned by these services. It validates their responses against copied contract types before changing a shift.

| Method and path | Owner | Purpose and expected response |
| --- | --- | --- |
| `GET /internal/v1/players/{player_id}` | Player | Verify a participant; `200 Player` |
| `GET /internal/v1/teams/{team_id}` | Player | Verify team membership; `200 Team` |
| `GET /internal/v1/rule-versions/current` | Server Rules | Pin a published rule; `200 RuleSet` |
| `GET /internal/v1/sessions/{session_id}/record-permissions/{player_id}` | University Record | Verify a Junior Moderator's permissions; `200 Permission` |
| `POST /internal/v1/university-snapshots` | University Record | Pin reference data; `201 SnapshotAccepted` |
| `POST /internal/v1/applicant/cases` | Applicant | Initialize a case; `202 CaseAccepted` |
| `POST /internal/v1/credential/cases` | Credential | Initialize a case; `202 CaseAccepted` |
| `POST /internal/v1/university-record/cases` | University Record | Initialize a case; `202 CaseAccepted` |
| `GET /internal/v1/applicant/cases/{case_id}/status` | Applicant | Poll `LocalCaseState` |
| `GET /internal/v1/credential/cases/{case_id}/status` | Credential | Poll `LocalCaseState` |
| `GET /internal/v1/university-record/cases/{case_id}/status` | University Record | Poll `LocalCaseState` |

## Shift start and case initialization

Before start, Session checks current team membership, every participant, the published rule version, and the record permissions. Each record kind needs an assigned Junior Moderator, and no one Junior Moderator may own all kinds. Session persists the rule ID, permission snapshot, reference time, and outbound request key before asking University Record for a snapshot. A failed snapshot request leaves the shift in the lobby. Retrying with the original client key reuses the same snapshot request.

Only the assigned Moderator can start a case. Session stores the selected initializer and key before making an external call. A lost response is retried against the same initializer with the same key. Applicant, Credential, or University Record returns a pending case ID; Session reports ready only after all three case owners do. A delayed consumer's `404` is treated as pending. Session creates no applicant or credential data itself.

The [shared initialization contract](../../README.md#applicant-credential-and-university-record-initialization) defines the event and identity rules. Session normally requests the internal `random` scenario. Fixed scenarios are test fixtures and are not selectable by players.

## Scoring and result event

Session consumes `DecisionScored` from Moderation through RabbitMQ queue `session.decision-scored.v1` or the authenticated internal fixture endpoint. It verifies the current case and Moderator, then applies each decision once. A correct decision adds 10 points with no penalty; an incorrect decision adds -5 points and 5 penalty points. Session aggregates results; it does not evaluate admission policy.

An unfinished case, including a scoring event still in transit, prevents shift end with `409`. After all accepted decisions are counted, Session commits `ended` and one `ShiftEnded` outbox event in the same PostgreSQL transaction. The worker publishes that event to Player. Retries do not create another final result or XP award. The [shared event table](../../README.md#rabbitmq-event-contract) defines the exact schema and routing keys.

## Storage and Lab 1 deployment

The published image is [`tirppy/student-id-session-service:1.0.0-rc.2`](https://hub.docker.com/r/tirppy/student-id-session-service/tags). It listens on container port `8002` and runs as a non-root user. Pin this version for the Lab 1 review. Session needs its own PostgreSQL database, real Player calls, Redis caching, and RabbitMQ result delivery. PostgreSQL transaction locks serialize concurrent writes; Redis is not the authority for roles or scores. SQLite supports isolated development.

Set these values in a local `.env`. Do not commit `.env` or service tokens. URL-encode reserved characters in database and broker passwords.

| Setting | Required value |
| --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://session:<password>@session-db:5432/session_db` for the shared deployment. |
| `PLAYER_MODE`, `PLAYER_URL`, `PLAYER_JWKS_URL` | `http`, `http://player:8001`, and `http://player:8001/.well-known/jwks.json`; Session uses Player's public key to verify access tokens. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | `student-id-please` and `student-id-players`, matching Player's issued tokens. |
| `OUTGOING_SERVICE_TOKEN`, `SERVICE_TOKENS` | The outgoing token must match Player's `session` entry. The JSON map needs a distinct `moderation` token for the internal event fixture. |
| `REDIS_URL` | Reachable cache URL, for example `redis://redis:6379/0`. |
| `RABBITMQ_URL`, `RABBITMQ_EXCHANGE` | Reachable broker URL, for example `amqp://studentid:<password>@rabbitmq:5672/`, and `student-id.events.v1`. |
| `EXTERNAL_SERVICES_MODE` | `mock` while teammate services are unavailable; switch to `http` when their real APIs and credentials are connected. |
| `RULES_URL`, `UNIVERSITY_RECORD_URL`, `APPLICANT_URL`, `CREDENTIAL_URL` | Reachable service URLs when `EXTERNAL_SERVICES_MODE=http`. |

The shared Compose deployment is a separate team task. Its current Session portion uses these containers on one network:

| Container | Image and startup | Storage and access |
| --- | --- | --- |
| `session-db` | `postgres:17-alpine`; create database `session_db` and user `session`; wait for `pg_isready -U session -d session_db`. | Persist `/var/lib/postgresql/data`. Keep port `5432` private. |
| `redis` | `redis:7.4-alpine`; wait for `redis-cli ping`. | Live cache entries may expire or be rebuilt; no durable volume is needed for Session data. |
| `rabbitmq` | `rabbitmq:4.1-management-alpine`; configure broker credentials and wait for `rabbitmq-diagnostics -q ping`. | Persist `/var/lib/rabbitmq`. Keep broker ports private. |
| `player` | Start the published Player image after its database and RabbitMQ are healthy. | Expose its API to Session on the deployment network. |
| `session` | Run the versioned image after PostgreSQL, Redis, RabbitMQ, and Player are healthy. | Bind API port `8002` to `127.0.0.1:8002` for a local check. |

To start the published image against running dependencies, set `TEAM_NETWORK` to their Docker network name. Put the values above in `.env`, then run from the directory containing it in PowerShell:

```powershell
docker pull tirppy/student-id-session-service:1.0.0-rc.2
docker run --rm --network $env:TEAM_NETWORK --env-file .env -p 127.0.0.1:8002:8002 tirppy/student-id-session-service:1.0.0-rc.2
```

`GET /health` checks the API process. `GET /ready` checks configured dependencies. The [private run guide](https://github.com/Tirppy/student-id-session-service/blob/dev/docs/running.md) covers source and isolated SQLite setup. The shared deployment must confirm that Session totals, penalties, and snapshot IDs survive container recreation.

With `EXTERNAL_SERVICES_MODE=mock`, Session calls real Player but supplies a published ruleset, distributed permissions, a stable snapshot ID, deterministic case IDs, and readiness responses through typed mocks. The mocks do not create applicant facts or decide admission outcomes. The [Session Postman collection](../../postman/session-service.json) supplies a `DecisionScored` fixture and contains only Session requests.

To run the collection in Postman, set `session_url`, `moderation_token`, `team_id`, `moderator_id`, `junior1_id`, `junior2_id`, and the three corresponding player tokens in a local environment. Its default URL is `http://localhost:8002`. Start Player and Session first. The Docker-based Newman runner creates the three-player team automatically. Set `MODERATION_SERVICE_TOKEN`, then run `python tools/session-service/run_postman.py` from the CPR root. Set `PLAYER_SETUP_URL` if Player is not reachable at `http://localhost:8001`; for a Docker network, set `POSTMAN_DOCKER_NETWORK` and `SESSION_URL`.

With RabbitMQ running, use `python tools/session-service/check_concurrency.py` to check concurrent case creation, scoring delivery, and end requests. Verify start permissions, snapshot retries, each case initializer, pending readiness, duplicate decisions, and one final outbox event. Keep all test credentials out of Git.
