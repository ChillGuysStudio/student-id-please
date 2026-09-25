# Server Moderation Session Service integration contract

Session owns moderation shift lifecycle, participants and roles, case references, aggregate score, and penalties. The [CPR communication contract](../../README.md#communication-contract) defines the shared REST, event, and case-initialization rules. The [private Session repository](https://github.com/Tirppy/student-id-session-service) contains the implementation and its run instructions. This document describes the Lab 1 integration used by other services.

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

## Storage, mocks, and Lab 1 verification

Session uses its own PostgreSQL database for shifts, cases, idempotency records, and event inbox/outbox entries. PostgreSQL transaction locks serialize concurrent writes. Redis caches live session views; it is not the authority for roles or scores. The later team deployment must persist Session's PostgreSQL data. SQLite supports isolated development.

The published Lab 1 review image is [`tirppy/student-id-session-service:1.0.0-rc.2`](https://hub.docker.com/r/tirppy/student-id-session-service/tags). Follow the [private run guide](https://github.com/Tirppy/student-id-session-service/blob/dev/docs/running.md) for standalone source or container setup. Session calls real Player and uses typed mocks for the unavailable teammate services. Those mocks return a representative published ruleset, distributed permissions, a stable snapshot ID, deterministic case IDs, and readiness responses. They do not generate applicant facts or decide admission outcomes. The [Session Postman collection](../../postman/session-service.json) supplies a `DecisionScored` fixture and contains only Session requests.

To run the collection in Postman, set `session_url`, `moderation_token`, `team_id`, `moderator_id`, `junior1_id`, `junior2_id`, and the three corresponding player tokens in a local environment. The default URL is `http://localhost:8002`. Start Player and Session first, with `PLAYER_MODE=http` and `EXTERNAL_SERVICES_MODE=mock` for Session. Session's outgoing service token must match Player's `session` token; its `SERVICE_TOKENS` map must include `moderation`. Keep token values out of Git.

The Docker-based Newman runner creates the three-player team automatically. Set `MODERATION_SERVICE_TOKEN`, then run `python tools/session-service/run_postman.py` from the CPR root. Set `PLAYER_SETUP_URL` if Player is not reachable at `http://localhost:8001`. For a Docker network, set `POSTMAN_DOCKER_NETWORK` and `SESSION_URL`. To check concurrent case, scoring, and end requests with RabbitMQ running, use `python tools/session-service/check_concurrency.py`.

Verification should cover start permissions, snapshot retries, each case initializer, pending readiness, duplicate decisions, one final outbox event, and concurrent end requests. The later team deployment must verify that shift totals, penalties, and snapshot IDs survive container recreation.
