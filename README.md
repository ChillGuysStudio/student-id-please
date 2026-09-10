# Topic 3 - Student ID, please

Student ID, please is a distributed game built with microservices. Players act as Discord moderators for a university server, checking applicants' claims and credentials against university records and changing server rules.

This README describes the proposed Lab 0 design for implementation in later labs.

The game uses an event-driven architecture to simulate live moderation shifts. Players share findings through WebSocket chat channels, work with role-based access to information (information asymmetry), and carry their progression across shifts.

## Table of contents

- [Team overview](#team-overview)
- [Service boundaries](#service-boundaries)
- [Architecture diagram](#architecture-diagram)
- [Technologies & communication patterns](#technologies--communication-patterns)
- [Communication contract](#communication-contract)
- [Contribution & workflow guidelines](#contribution--workflow-guidelines)
- [Project board](#project-board)

## Team overview

| Developer | Services owned | Language / stack | Repositories |
| :--- | :--- | :--- | :--- |
| Chicu Andrei | Moderation Service<br>Discord DMs Service | Python / FastAPI | [moderation-service](https://github.com/andyp1xe1/pad-moderation-service)<br>[discord-dms-service](https://github.com/andyp1xe1/pad-discord-dms-service) |
| Vremere Adrian | Applicant Service<br>Credential Service | Java / Spring Boot | [applicant-service](https://github.com/mcittkmims/applicant-service)<br>[credential-service](https://github.com/mcittkmims/credential-service) |
| Alexei Maxim | Server Rules Service<br>University Record Service | Java / Spring Boot | [server-rules-service](https://github.com/MaxNoragami/server-rules-service)<br>[university-record-service](https://github.com/MaxNoragami/university-record-service) |
| Gebotari Alexandru | Player Service<br>Session Service | Python / FastAPI | [player-service](https://github.com/Tirppy/student-id-player-service)<br>[session-service](https://github.com/Tirppy/student-id-session-service) |

## Service boundaries

Each service is the only writer to the data it owns. Other services use APIs to request that data or consume events containing the data they need. Data copied into a local projection does not become a new source of truth.

### Player Service

The Player Service owns global player identity and persistent moderator progression:

- player accounts and authentication
- player profiles and friendships
- moderation teams and team membership
- XP, levels, and persistent progression

It updates progression from completed-shift and disciplinary events. It does not own applicants, moderation-session roles, admission decisions, or session scores.

### Server Moderation Session Service

The Server Moderation Session Service owns active Discord moderation shifts:

- moderation-shift creation and lifecycle
- the participant roster and the Moderator or Junior Moderator role assigned to each participant
- the current applicant reference
- the number of processed applications
- the aggregate shift score and penalties

It consumes individual outcomes from the Moderation Service and calculates the overall shift result. When a shift ends, it publishes the result for the Player Service to apply to player progression.

It does not own player accounts or progression, applicant details, individual admission decisions, server rules, or chat messages.

### Applicant Service

The Applicant Service generates and maintains applicant profiles, background details, and presented claims. These claims can include the applicant's name, student ID, major, year, university status, courses, and role.

An applicant can claim to be a FAF student, a student from another major, a teaching assistant, a university staff member, an alumnus, or an outsider. The claims may be false or may impersonate another person.

The service does not own submitted credentials, authoritative university records, credential-validation results, or admission decisions.

### Credential Service

The Credential Service validates the structure, authenticity, and integrity of physical or digital documents. It owns:

- documents and credentials presented by an applicant
- structural and authenticity checks
- the validation result for each credential

Credentials can include a student ID, a university email, an enrollment confirmation, or an ELSE course registration. A credential can be expired, forged, inconsistent, or incomplete.

The service does not own the applicant's claimed identity, authoritative university records, access rules, or admission decisions. A valid credential does not by itself grant access to the Discord server.

### Server Rules Service

The Server Rules Service owns versioned rules for accessing the Discord server. It evaluates applicant claims, credential results, university facts, and moderation history against the rule version active for the shift.

Rules can restrict access by major, year, enrollment duration, university role, allowed channels, or an existing ban. The service returns the expected policy result and the rules that matched.

It does not own applicant data, credentials, university records, bans, moderator actions, or scoring. The Moderation Service owns the comparison between the expected policy result and the Moderator's decision.

### University Record Service

The University Record Service owns authoritative university facts, including:

- current enrollment
- Outlook group email membership
- existing courses
- the current academic year
- the semester schedule
- FCIM server message records

It also owns permissions that determine which university records each Junior Moderator may inspect. The service enforces these permissions whenever a player requests a record.

It does not own applicant claims, submitted credentials, credential-validation results, or admission decisions.

### Moderation Service

The Moderation Service executes admission decisions and checks them against server rules. It owns:

- the Moderator's Accept, Reject, Flag, or Ban action for each applicant
- decision history and active bans
- the server-rule result used for the decision
- the correctness, violated rules, outcome, and penalty for one decision

The service obtains the required facts from the Applicant, Credential, University Record, and Server Rules services. It compares the Moderator's action with the result returned by the Server Rules Service, then publishes the decision outcome to the Server Moderation Session Service.

It does not own the source applicant data, credentials, university records, rule definitions, or aggregate shift score.

### Discord DMs Service

The Discord DMs Service owns moderation channels, channel membership, messages, and real-time message delivery over WebSockets. Session channels can include:

- `#enrollment-check`
- `#faculty-check`
- `#course-registration`
- `#general-mod-chat`

The service uses session roles and university-record permissions when granting channel access. It does not own those roles or permissions. It transports messages but does not verify whether their contents are correct.

### Applicant case initialization

The Applicant, Credential, or University Record service may receive the initial request for a new applicant case. The first service generates the authoritative `case_id` and publishes a `CaseInitialized` event with this `case_id` and the generation payload.

- Receiving services reuse the event's `case_id` and create only the domain records they own.
- Consumers must handle duplicate or concurrent initialization events idempotently, for example with a `UNIQUE(case_id)` constraint or an upsert, to prevent duplicate records or mismatched IDs. The initialization contract below defines how to reject conflicting payloads.

No service writes directly to another service's database. The shared `case_id` links the applicant profile, credentials, university records, moderation decision, and session entry across isolated databases without violating data ownership boundaries.

## Architecture diagram

<img src="docs/architecture.svg" alt="Architecture Diagram" width="1080"/>

## Technologies & communication patterns

## Technologies & Communication Patterns

This is the proposed Lab 0 design for implementation in later labs. The language and framework choices follow the architecture diagram. The endpoint paths, schemas, data storage, and delivery rules below are proposed contracts; they do not imply that services already run.

| Service | Language / framework | Storage owned by service | Communication |
| --- | --- | --- | --- |
| Player | Python / FastAPI | PostgreSQL: accounts, profiles, friendships, teams, progression | REST; consumes `ShiftEnded` and `DisciplinaryActionApplied` |
| Server Moderation Session | Python / FastAPI | Redis + PostgreSQL: active shifts, participants, score (Redis for locks/live state, Postgres for history) | REST; consumes `DecisionScored`; publishes `ShiftEnded` |
| Applicant | Java / Spring Boot | MongoDB: applicant claims and case initialization metadata | REST; publishes/consumes `CaseInitialized` |
| Credential | Java / Spring Boot | MongoDB: submitted credentials and validation results | REST; publishes/consumes `CaseInitialized` |
| Server Rules | Java / Spring Boot | PostgreSQL: immutable rule versions | Internal REST policy evaluation; REST for shift rules |
| University Record | Java / Spring Boot | MongoDB: university facts and record permissions | REST; publishes/consumes `CaseInitialized` |
| Moderation | Python / FastAPI | PostgreSQL: decisions, policy snapshots, bans, disciplinary actions | REST orchestration; publishes `DecisionScored` and `DisciplinaryActionApplied` |
| Discord DMs | Python / FastAPI | Redis + MongoDB: channels, memberships, messages (Mongo for durable channels/memberships/history, Redis for live WS/PubSub) | REST for channel/history access; WebSockets for live chat |


### Selection rationale and trade-offs

#### Python / FastAPI

Player APIs, session orchestration, moderation decisions, and live DMs involve many network waits and small transformations. FastAPI supports typed request models and asynchronous HTTP/WebSocket handling; Python keeps scoring and orchestration code concise.

Use appropriate drivers or workers for blocking database and broker operations, and keep CPU-heavy work off the live-chat path. Maintaining Python alongside Java requires extra tooling and satisfies the required two-language team split.

#### Java / Spring Boot

Applicant generation, document validation, versioned policy evaluation, and university records share structured domain models and invariants. Java's types and Spring's validation, security, and transaction facilities suit these services and their isolated databases.

The trade-off is more configuration and runtime overhead. One framework across the case-data services keeps implementation conventions consistent. Initial generation is bounded and deterministic, without external AI calls.

#### Storage per service

We chose the database engines that best fit the data structure of each specific domain. Some services utilize multiple stores to separate live state from persistent history.

- **PostgreSQL:** Used for the Player, Server Moderation Session, Server Rules, and Moderation services. These require strict ACID transactions, relational joins, and structured ledgers to reliably manage XP progression, shift history and outbox guarantees, immutable rule sets, and final admission decisions.
- **MongoDB:** Used for the Applicant, Credential, and University Record services, along with Discord DMs channels, memberships, and chat history. Document databases handle unpredictable, schema-less structures well. This lets us store vastly different records (like an `Enrollment` versus an `FcimMessage`) naturally, without creating SQL tables full of empty columns. It also reliably handles the high write volume of chat messages and ensures channel permissions survive broker restarts.
- **Redis:** Acts as an ephemeral in-memory datastore for the Discord DMs and Session services. It coordinates live WebSocket message broadcasting (via Pub/Sub) and connection caching—leaving durable channel and membership records to MongoDB—and provides distributed locks for concurrent case starts alongside fast lookups for active shift rosters.

#### REST / HTTP with JSON

Immediate reads and commands use request/response communication. Both frameworks support JSON, which is human-readable and easy to inspect during a lab demonstration. It is more verbose than Protobuf and provides no distributed transaction. Callers need explicit timeout, retry, and unavailable responses. UUIDs are JSON strings to avoid language-specific integer serialization issues.

#### RabbitMQ / AMQP

Case initialization, decision scoring, and progression propagation use durable events, so producers can publish while consumers are unavailable. The trade-offs are eventual consistency, duplicate delivery, and broker operations. The contract defines readiness, deduplication, and an outbox; it does not assume exactly-once delivery.

#### WebSockets

DMs need server-to-client delivery during active shifts. A persistent connection avoids repeated polling, but requires reconnect/history recovery and permission rechecks. DMs persists messages before broadcast; clients recover missed messages through the REST history endpoint.

#### API Gateway

One public entry point routes REST and the WebSocket upgrade, verifies player authentication, and applies request limits. This simplifies client routing but adds a shared dependency. Each service still enforces its own authorization. The team must agree on the gateway implementation before deployment. It is infrastructure, not an additional domain service.

### Interaction map

The table lists the planned interactions, including authorization and event paths omitted from the diagram for readability.

| Caller / producer | Receiver / consumer | Purpose and transport |
| --- | --- | --- |
| Client via gateway | All services' public endpoints | REST/JSON; authenticated player commands and permitted reads |
| Client via gateway | Discord DMs | WebSocket upgrade and chat frames |
| Session | Player | REST: check team and player membership |
| Session | Server Rules, University Record | REST: pin the published rule version and validate permission distribution when starting a shift |
| Session | Applicant, Credential, University Record | Internal REST: initialize a case through one selected service, poll readiness in all three |
| Moderation | Session | Internal REST: verify active shift, assigned Moderator, current case and pinned rules |
| Moderation | Applicant, Credential, University Record | Internal REST: gather complete case facts for scoring |
| Moderation | Server Rules | Internal REST: evaluate those facts and pre-existing bans/history |
| Moderation | Player | Internal REST: validate the target of a disciplinary action |
| Applicant, Credential, Server Rules, University Record, Discord DMs | Session | Internal REST: verify shift participation, roles and lifecycle |
| Discord DMs | University Record | Internal REST: enforce record-derived channel permissions |
| Applicant / Credential / University Record | Other two case services | RabbitMQ: initialize owned records using the same `case_id` |
| Moderation | Session | RabbitMQ: apply `DecisionScored` once |
| Session | Player | RabbitMQ: apply final `ShiftEnded` progression once |
| Moderation | Player | RabbitMQ: apply `DisciplinaryActionApplied` once |

## Communication contract

### Data ownership and consistency

Each service is the sole writer of its database. Cross-service reads use the APIs below; events maintain local projections that are never a new authority. Database foreign keys stay within one service. Callers validate cross-service UUID references through the owner API and recheck cached data for authorization-sensitive operations.

University records describe simulated people. The `subject_id` identifies the person in those records, while `case_id` identifies the application. Bans use `subject_id`, so returning under a new case does not discard a ban. A case may have no known university subject.

Services commit mutations and pending events in the same local database transaction using an outbox. A publisher retries until RabbitMQ confirms receipt. Consumers commit a unique `(consumer, event_id)` inbox record with their domain update before acknowledging.

Domain constraints such as `UNIQUE(case_id)`, `UNIQUE(session_id, case_id)` for final decisions, and `UNIQUE(session_id)` for applied shift progression also prevent semantic duplicates. There is no distributed transaction: partially initialized cases remain pending, and downstream failures never become negative admission decisions.

### Shared REST conventions

#### Paths and data types

Public paths below are gateway paths under `/api/v1`. Internal paths start with `/internal/v1`; the gateway does not expose them. Each endpoint belongs to the named service.

Requests and non-empty responses use `application/json`. Field names use `snake_case`.

| Notation | Meaning |
| --- | --- |
| `Id` | UUID string |
| `Time` | RFC 3339 UTC timestamp string |
| `Int` | Signed 32-bit integer |
| `Bool` | Boolean |
| `T[]` | Array of `T` |
| `T?` | Optional field |

`T | null` means a required nullable field. All other fields are required. Scores may be negative; counts are non-negative. Objects below are type notation, not JSON literals.

#### Authentication and authorization

Authentication uses `Authorization: Bearer <access_token>`. Player owns token issuance. Services verify signature, issuer, audience, and expiry. Access tokens expire after 15 minutes. Refresh tokens are opaque, stored hashed, expire after 7 days, and rotate on use; logout revokes the refresh session.

Administrators provision global `admin` access; players cannot select it during registration. Shift roles come from Session, never a client-submitted role claim.

Internal calls use service credentials scoped to caller, receiver, and operation. A service identity alone does not authorize an arbitrary player action. Callers propagate the initiating player's identity in verified auth context; receiving services check it against Session. Player-facing responses never include hidden generation data, expected decisions, or another player's restricted records.

#### Idempotency

Every mutating REST request includes `Idempotency-Key: <UUID>`. An identical retry to the same endpoint by the same caller returns the original status/body; key reuse with a different body returns `409`.

Services retain keys and results for the lifetime of the associated case/shift. Authentication operations retain them for 24 hours, and clients must not retry outside that window. Replays still require valid authorization. Clients retry a case-start request through the same entry service using the same key; routing the same logical request to a different service is not supported.

#### Pagination

Collections use optional `limit: Int` (default 50, range 1 to 100) and `cursor: string` query parameters. `Page<T> = {items: T[], next_cursor: string | null}`; cursors are opaque and scoped to the caller and resource. Stable ordering uses creation time then ID. Empty collections return `200` with `items: []`.

#### Errors and retries

Common error shape: `Error = {code: string, message: string, request_id: Id, details: {field: string, reason: string}[]}`. Do not include hidden facts, secrets, or stack traces.

| Status | Meaning |
| --- | --- |
| `400` | Malformed request |
| `401` | Invalid auth |
| `403` | Insufficient permission |
| `404` | Absent resource |
| `409` | State/key conflict |
| `422` | Invalid field values |
| `429` | Rate limit |
| `503` | Unavailable dependency |

An existing but unfinished case returns `409 CASE_NOT_READY` with `Retry-After: 1`, never an empty result interpreted as false facts. Rate limits also include `Retry-After` seconds. Endpoint tables specify success responses; these common errors apply wherever relevant.

Internal reads have a 2-second timeout. Only safe reads and commands carrying the original idempotency key may retry, at most twice with backoff. A failed dependency returns `503`; the caller does not fabricate facts or correctness. Pagination, timeout, and size values are initial contract defaults to review during implementation.

Example error response:

```json
{
  "code": "CASE_NOT_READY",
  "message": "Case records are still being initialized.",
  "request_id": "9d1ea947-4194-4897-a8db-71698f62fd2a",
  "details": []
}
```

### Shared domain types

```text
Role = "moderator" | "junior_moderator"
ApplicantRole = "student" | "teaching_assistant" | "staff" | "alumnus" | "outsider"
Action = "accept" | "reject" | "flag" | "ban"
RecordKind = "enrollment" | "outlook_group" | "course" | "academic_year" | "schedule" | "fcim_message"
CredentialKind = "student_id" | "university_email" | "enrollment_confirmation" | "else_registration"
Claims = {name: string, student_id: string | null, major: string | null,
          year: Int | null, university_status: "active" | "inactive" | "graduated" | "none",
          courses: string[], role: ApplicantRole}
Applicant = {case_id: Id, session_id: Id, claims: Claims}
Credential = {credential_id: Id, case_id: Id, kind: CredentialKind,
              holder_name: string, student_id: string | null, issuer: string,
              issued_at: Time, expires_at: Time | null, email: string | null,
              course_ids: string[]}
Validation = {credential_id: Id, structurally_valid: Bool, authentic: Bool,
              expired: Bool, issues: string[], checked_at: Time}
UniversityRecord = {record_id: Id, case_id: Id, kind: RecordKind, subject_id: Id | null,
                    data: Enrollment | OutlookGroup | Course | AcademicYear | Schedule | FcimMessage}
Enrollment = {student_id: string, name: string, major: string, year: Int,
              status: "active" | "inactive" | "graduated", enrolled_since: Time,
              role: ApplicantRole}
OutlookGroup = {email: string, group_name: string, member: Bool}
Course = {course_id: string, title: string, enrolled: Bool}
AcademicYear = {label: string, starts_at: Time, ends_at: Time}
Schedule = {semester: string, course_id: string, starts_at: Time, ends_at: Time}
FcimMessage = {author_name: string, channel: string, text: string, sent_at: Time}
Permission = {session_id: Id, player_id: Id, record_kinds: RecordKind[]}
Ban = {ban_id: Id, subject_id: Id, source_case_id: Id, reason: string, created_at: Time}
PolicyResult = {rule_version: Id, expected_action: Action, allowed_channels: string[],
                matched_rule_ids: Id[], violated_rule_ids: Id[]}
Decision = {decision_id: Id, session_id: Id, case_id: Id, moderator_id: Id,
            action: Action, reason: string, policy: PolicyResult, correct: Bool,
            score_delta: Int, penalty: Int, created_at: Time}
```

`UniversityRecord.data` must match `kind` in the listed order; services reject arbitrary object payloads. `student_id` is a presented or university identifier, never the database case key.

Empty record arrays mean an authoritative completed lookup found no records. Only authorized internal consumers can read the full record set; players can inspect records within their permissions. Credential validation authenticates documents independently of access policy. `authentic` in generation inputs is private metadata and is not a field of the player-visible credential.

### Player Service endpoints

```text
Player = {player_id: Id, username: string, display_name: string, xp: Int, level: Int}
Tokens = {access_token: string, refresh_token: string, expires_in: Int, token_type: "Bearer"}
Team = {team_id: Id, name: string, owner_id: Id, member_ids: Id[]}
Friendship = {friendship_id: Id, requester_id: Id, recipient_id: Id,
              status: "pending" | "accepted"}
```

| Method and path | Authorized caller | Request body / additional query | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/players` | Anonymous | `{username: string, email: string, password: string, display_name: string}` | `201 Player`; unique username/email; password stored hashed, never returned |
| `POST /api/v1/auth/login` | Anonymous | `{email: string, password: string}` | `200 Tokens`; wrong credentials `401` |
| `POST /api/v1/auth/refresh` | Refresh-token holder | `{refresh_token: string}` | `200 Tokens`; old refresh token revoked atomically |
| `POST /api/v1/auth/logout` | Refresh-token holder | `{refresh_token: string}` | `204`, no body |
| `GET /api/v1/players/me` | Player | None | `200 Player` |
| `PATCH /api/v1/players/me` | Player | `{display_name: string}` | `200 Player`; XP/level cannot be edited |
| `GET /api/v1/players/{player_id}` | Player | None | `200 Player`; no email/password/token fields |
| `POST /api/v1/friendships` | Player | `{recipient_id: Id}` | `201 Friendship` in pending state |
| `PUT /api/v1/friendships/{friendship_id}/acceptance` | Recipient | Empty object | `200 Friendship` in accepted state |
| `GET /api/v1/friendships` | Player | Pagination | `200 Page<Friendship>` involving caller |
| `DELETE /api/v1/friendships/{friendship_id}` | Either participant | None | `204`, no body; removes or declines request |
| `POST /api/v1/teams` | Player | `{name: string}` | `201 Team`; caller becomes owner/member |
| `GET /api/v1/teams/{team_id}` | Team member | None | `200 Team` |
| `POST /api/v1/teams/{team_id}/members` | Team owner | `{player_id: Id}` | `200 Team`; target must be an accepted friend |
| `DELETE /api/v1/teams/{team_id}/members/{player_id}` | Owner or departing member | None | `200 Team`; owner cannot leave without deleting team |
| `DELETE /api/v1/teams/{team_id}` | Owner | None | `204`, no body; historical shift rosters remain snapshots |
| `GET /internal/v1/players/{player_id}` | Session or Moderation | None | `200 Player` |
| `GET /internal/v1/teams/{team_id}` | Session | None | `200 Team` |

Player consumes progression events, not client XP commands. Completed-shift XP is `max(0, score)` for each participant. Store those awards and distinct disciplinary `xp_penalty` deductions in a progression ledger; total XP is `max(0, sum(awards) - sum(deductions))`.

Recompute from that ledger so different delivery orders produce the same result. Level is `1 + floor(xp / 100)`. Shift decision penalties are already part of the final score and must not also produce disciplinary deductions.

### Server Moderation Session Service endpoints

```text
Participant = {player_id: Id, role: Role}
Session = {session_id: Id, team_id: Id, owner_id: Id,
           status: "lobby" | "active" | "ending" | "ended",
           participants: Participant[], rule_version: Id | null, started_at: Time | null,
           current_case_id: Id | null, processed_count: Int, score: Int, penalties: Int}
CaseStatus = {case_id: Id, session_id: Id, state: "pending" | "ready",
              ready_services: ("applicant" | "credential" | "university_record")[]}
SessionContext = {session: Session, player: Participant}
```

| Method and path | Authorized caller | Request body / additional query | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/sessions` | Team member | `{team_id: Id}` | `201 Session`; caller owns lobby and initially has Moderator role |
| `GET /api/v1/sessions` | Player | Pagination | `200 Page<Session>` for caller's joined sessions |
| `POST /api/v1/sessions/{session_id}/participants` | Member of that team | Empty object | `200 Session`; joins self as Junior Moderator while lobby is open |
| `PUT /api/v1/sessions/{session_id}/roles` | Session owner | `{participants: Participant[]}` | `200 Session`; complete existing roster, exactly one Moderator |
| `GET /api/v1/sessions/{session_id}` | Participant | None | `200 Session` |
| `POST /api/v1/sessions/{session_id}/start` | Session owner | Empty object | `200 Session`; pins currently published rule version and freezes roster/roles |
| `POST /api/v1/sessions/{session_id}/cases` | Assigned Moderator | `{entry_service: "applicant" \| "credential" \| "university_record"}` | `202 CaseStatus`; selects one initializer, reserves current case slot; scenario is chosen internally |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` | Participant | None | `200 CaseStatus`; readiness queried from all three owners |
| `POST /api/v1/sessions/{session_id}/end` | Session owner | Empty object | `202 Session` in ending state, or `200 Session` if already ended |
| `GET /internal/v1/sessions/{session_id}/context` | Case services, Moderation, Rules, University Record or DMs | Query `player_id: Id` | `200 SessionContext`; validates participation; callers check required role/status |

A shift starts with one Moderator and at least two Junior Moderators to distribute record permissions. Session serializes case-start and end commands. It calls exactly one of the three internal initializer endpoints below using a persisted idempotency key and verified Moderator context. If the response is lost, it retries that same service/key; it never fails over the command to a different initializer.

Initialization metadata pins the scenario and seed once, even for `random`. Each service still initializes its own records and can be the first service contacted, as required by Topic 3.

Normal gameplay always requests the internal `random` scenario; fixed scenarios are internal test fixtures. Players cannot choose or inspect the hidden scenario/seed. A case's status endpoint reports readiness only.

Only one case is current at a time. Session allows a new case after applying the current case's `DecisionScored`. It accepts a score event only for its current case and only once per decision; it increments `processed_count`, adds `score_delta`, and accumulates `penalty`.

Ending a shift with an undecided/pending current case returns `409`; if a submitted decision's event is still in transit, end waits in `ending`. Session publishes the final `ShiftEnded` only after counting all accepted decisions. Case starts and decisions reject `ending`/`ended` shifts. Clients poll `GET /sessions/{session_id}` until completion; timeout does not imply completion.

### Applicant, Credential and University Record initialization

```text
CaseStart = {session_id: Id, scenario: "eligible" | "forged" | "impersonation" | "outsider" | "random"}
CaseAccepted = {case_id: Id, session_id: Id, state: "pending"}
LocalCaseState = {case_id: Id, session_id: Id, state: "pending" | "ready"}
Generation = {scenario: "eligible" | "forged" | "impersonation" | "outsider",
              seed: string, subject_id: Id | null, claims: Claims,
              credentials: {credential: Credential, authentic: Bool}[],
              university_records: UniversityRecord[]}
```

| Method and path | Owner / authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /internal/v1/applicant/cases` | Applicant / Session | `CaseStart` plus propagated Moderator context | `202 CaseAccepted` |
| `POST /internal/v1/credential/cases` | Credential / Session | `CaseStart` plus propagated Moderator context | `202 CaseAccepted` |
| `POST /internal/v1/university-record/cases` | University Record / Session | `CaseStart` plus propagated Moderator context | `202 CaseAccepted` |
| `GET /internal/v1/applicant/cases/{case_id}/status` | Applicant / Session | None | `200 LocalCaseState` |
| `GET /internal/v1/credential/cases/{case_id}/status` | Credential / Session | None | `200 LocalCaseState` |
| `GET /internal/v1/university-record/cases/{case_id}/status` | University Record / Session | None | `200 LocalCaseState` |

The first service creates `case_id`, builds a coherent `Generation` payload, saves only its own domain records, and emits `CaseInitialized`. All IDs inside the payload must match that case. The other services reuse the event's IDs and typed values; they do not randomize received facts on their own.

False claims, forged credentials, and impersonation are deliberate differences inside that payload, not accidental inconsistencies. For impersonation, `subject_id` is the actual simulated applicant and presented claims may refer to another person.

The initializer's payload is a generation instruction, not an alternate authoritative record database. Each domain owner validates and persists its portion; callers then read immutable initialization facts from that owner.

Consumers may receive the same event more than once. They must reject and quarantine conflicting initialization data for the same case, never overwrite it with an upsert.

A service marks local state ready only after committing its records; Session considers the case ready only when all three are ready. A `404` from a consumer during propagation counts as pending. Failed/quarantined initialization remains pending for operator repair. Moderation cannot score a decision until the case is ready. Hidden generation payloads are available only to these services.

### Applicant Service endpoints

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `GET /api/v1/sessions/{session_id}/applicants/{case_id}` | Assigned Moderator in active shift | None | `200 Applicant`; presented claims only |
| `GET /internal/v1/applicants/{case_id}` | Moderation | Query `session_id: Id` | `200 Applicant`; verifies case/shift association |

### Credential Service endpoints

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/credentials` | Assigned Moderator in active shift | Pagination | `200 Page<Credential>` |
| `POST /api/v1/sessions/{session_id}/credentials/{credential_id}/validation` | Assigned Moderator in active shift | Empty object | `200 Validation`; credential must belong to current case |
| `GET /internal/v1/cases/{case_id}/credential-results` | Moderation | Query `session_id: Id` | `200 {case_id: Id, credentials: Credential[], validations: Validation[]}`; complete results for every credential |

The internal endpoint performs or reuses deterministic validation even when the player did not request it. Checks use the shift's start time as the expiry reference, so a replay cannot change correctness mid-case. Forgery checks use the private authenticity metadata. Credentials are immutable during an active case.

### Server Rules Service endpoints

```text
Rule = {rule_id: Id, priority: Int, kind: "major" | "year" | "enrollment_duration" |
        "role" | "ban" | "credential", on_match: Action, allowed_channels: string[],
        condition: MajorCondition | YearCondition | DurationCondition | RoleCondition |
                   BanCondition | CredentialCondition}
MajorCondition = {allowed_majors: string[]}
YearCondition = {min_year: Int, max_year: Int}
DurationCondition = {min_months: Int}
RoleCondition = {roles: ApplicantRole[]}
BanCondition = {active: Bool}
CredentialCondition = {required_kinds: CredentialKind[], require_authentic: Bool, require_unexpired: Bool}
RuleSet = {rule_version: Id, status: "draft" | "published", rules: Rule[],
           default_action: Action, default_channels: string[], created_at: Time}
PolicyInput = {session_id: Id, case_id: Id, rule_version: Id, claims: Claims,
               credentials: Credential[], validations: Validation[],
               university_records: UniversityRecord[], active_bans: Ban[],
               prior_decisions: {action: Action, created_at: Time}[]}
```

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/rule-versions` | Global admin | `{rules: Rule[], default_action: Action, default_channels: string[]}` | `201 RuleSet` in draft state |
| `POST /api/v1/rule-versions/{rule_version}/publish` | Global admin | Empty object | `200 RuleSet`; atomically becomes current for future shifts |
| `GET /api/v1/rule-versions/{rule_version}` | Player | None | `200 RuleSet`; non-admins see published versions only |
| `GET /internal/v1/rule-versions/current` | Session | None | `200 RuleSet`; no published set gives `409` |
| `POST /internal/v1/policy/evaluations` | Moderation | `PolicyInput` | `200 PolicyResult`; session's pinned version must match |

Rule conditions use `kind` to distinguish their types. Major/year/duration/credential conditions match when the applicant fails the stated requirement; role/ban conditions match when the stated role/ban exists.

University facts are authoritative for identity and enrollment checks. The Server Rules Service compares claims against those facts; a material identity mismatch defaults to `flag` before ordinary access rules. An existing subject ban always returns `ban`. Otherwise, matching rules use ascending priority (ties resolved by rule ID); the first determines action/channels, with the default used when none match.

Matched requirement failures populate `violated_rule_ids`. Channels are empty for any non-accept action. Months mean completed calendar months at shift start. Each credential required by the rules must pass; a missing required credential fails.

Rules and their versions are immutable after publication, and updates create a new version. The initial proposal limits the policy vocabulary; new rule kinds require a versioned schema update.

### University Record Service endpoints

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `PUT /api/v1/sessions/{session_id}/record-permissions` | Session owner while lobby is open | `{permissions: Permission[]}` | `200 {permissions: Permission[]}`; complete replacement for Junior Moderators only |
| `GET /api/v1/sessions/{session_id}/record-permissions/me` | Participant | None | `200 Permission`; Moderator has no direct record permissions |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/university-records` | Junior Moderator in active shift | Required query `kind: RecordKind`; pagination | `200 Page<UniversityRecord>`; unassigned kind gives `403` |
| `GET /internal/v1/sessions/{session_id}/record-permissions/{player_id}` | DMs or Session | None | `200 Permission` |
| `GET /internal/v1/cases/{case_id}/university-records` | Moderation | Query `session_id: Id` | `200 {case_id: Id, subject_id: Id \| null, records: UniversityRecord[]}`; full internal facts |

Permissions freeze at shift start. Session checks that every record kind has at least one Junior Moderator assigned to it and no single Junior Moderator has every kind. Starting with an incomplete distribution returns `409`. This initial game configuration needs at least two Junior Moderators.

No player can query the internal complete-record endpoint, and the Moderator learns hidden records through DMs. Missing subject records are a valid result for outsiders, not an authorization bypass.

### Moderation Service endpoints

```text
Discipline = {disciplinary_action_id: Id, player_id: Id, reason: string,
              xp_penalty: Int, created_at: Time}
```

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/sessions/{session_id}/decisions` | Assigned Moderator in active shift | `{case_id: Id, action: Action, reason: string}` | `201 Decision`; one final decision per current case |
| `GET /api/v1/sessions/{session_id}/decisions` | Participant | Pagination | `200 Page<Decision>`; committed outcomes only |
| `GET /api/v1/sessions/{session_id}/decisions/{decision_id}` | Participant | None | `200 Decision`; validates shift association |
| `GET /api/v1/bans` | Global admin | Optional query `subject_id: Id`; pagination | `200 Page<Ban>` |
| `POST /api/v1/disciplinary-actions` | Global admin | `{player_id: Id, reason: string, xp_penalty: Int}` | `201 Discipline`; non-negative penalty, distinct from decision scoring |

Moderation checks Session context and all case data before evaluation. It supplies prior history and bans from its own database to Rules; it never accepts an expected answer from the player. It snapshots `PolicyResult` with the immutable decision.

The initial score is `+10` for a correct action and `-5` for an incorrect one (`penalty` is 0 for a correct action or 5 for an incorrect one). Correctness means the action equals `expected_action`.

`flag` is a final outcome for this case, with no investigation workflow in the initial contract. `ban` creates a persistent subject ban in the same transaction as the decision, even if the player chose incorrectly. A ban without an identifiable `subject_id` returns `422 SUBJECT_REQUIRED`; rules must use reject/flag for an unidentifiable outsider. Admissions return allowed channel names; this is a simulation, not a call to Discord's production API.

Before creating a ban, evaluate policy against bans that existed before this decision. Then persist the decision, new ban, and outbox in one transaction. This prevents a new ban from making its own action appear correct.

Competing decision requests with different keys receive `409` after the first decision wins; retries with the winning key return its original result. Players can see decision results only after commit; they cannot preview correctness through an evaluation endpoint.

### Discord DMs Service endpoints and WebSocket frames

```text
Channel = {channel_id: Id, session_id: Id, name: string, member_ids: Id[]}
Message = {message_id: Id, client_message_id: Id, channel_id: Id,
           author_id: Id, text: string, sent_at: Time}
```

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `GET /api/v1/sessions/{session_id}/channels` | Participant | None | `200 {channels: Channel[]}`; only caller's allowed channels |
| `GET /api/v1/channels/{channel_id}/messages` | Authorized channel member | Pagination | `200 Page<Message>` in chronological order |
| `POST /api/v1/sessions/{session_id}/chat-tickets` | Participant in active shift | Empty object | `201 {ticket: string, expires_at: Time}`; single-use, 30-second lifetime, bound to player and shift |
| `GET /api/v1/sessions/{session_id}/ws` (upgrade) | Chat-ticket holder | Query `ticket: string` | `101 Switching Protocols`; REST-style auth errors before upgrade |

DMs creates the four named session channels on first access without duplicating them on retries. `#general-mod-chat` admits all participants. The Moderator can join all channels to receive findings.

Junior Moderators may join `#enrollment-check` with enrollment or academic-year access, `#faculty-check` with outlook-group or FCIM-message access, and `#course-registration` with course or schedule access. These are permissions to discuss records, not permission to read extra records.

DMs verifies Session roles and University Record permissions on connection, history reads, and every send; failures deny access. Ended shifts permit authorized history reads but close live connections with code `1000` and reason `SHIFT_ENDED`. Connections also recheck lifecycle/auth expiry on a 30-second heartbeat; expiry closes with `1008`. Redact query tickets from logs. A consumed or expired ticket cannot reconnect.

All frames are JSON objects:

| Direction / type | Fields | Behavior |
| --- | --- | --- |
| Client `message.send` | `{type: "message.send", client_message_id: Id, channel_id: Id, text: string}` | 1 to 2000 characters; authenticated author is derived server-side |
| Server `message.ack` | `{type: "message.ack", client_message_id: Id, message_id: Id}` | Sent to author after persistence; duplicate `(author_id, client_message_id)` returns original ack |
| Server `message.created` | `{type: "message.created", message: Message}` | Broadcast only to authorized members; clients deduplicate by `message_id` |
| Server `error` | `{type: "error", client_message_id: Id \| null, error: Error}` | Invalid frame, permission failure or reused ID with different content; no broadcast |

Control-frame ping/pong runs every 30 seconds; two missed responses close the connection. Reconnect requires a new chat ticket and REST history recovery using the last retained pagination cursor; persistent `client_message_id` makes a lost acknowledgement safe to retry. Each channel's history order is stable by `(sent_at, message_id)`; cross-channel delivery order is not guaranteed.

With multiple DMs replicas, fan-out must reach every replica with connected members, for example through dedicated per-replica broker queues. A competing-consumer queue delivers each chat message to only one replica and does not meet this requirement.

### RabbitMQ event contract

All events use a durable topic exchange `student-id.events.v1`, persistent JSON messages, publisher confirms and manual consumer acknowledgements. `schema_version` is `1`. Event names, routing keys and payloads are fixed below; changing/removing fields requires a new major schema/exchange version. Consumers tolerate additional optional fields.

```text
Event<T> = {event_id: Id, event_type: string, schema_version: Int,
            occurred_at: Time, producer: "applicant" | "credential" | "university_record" |
            "moderation" | "session", correlation_id: Id, payload: T}
CaseInitializedPayload = {case_id: Id, session_id: Id, generation: Generation}
DecisionScoredPayload = {decision_id: Id, session_id: Id, case_id: Id, moderator_id: Id,
                        action: Action, correct: Bool, score_delta: Int, penalty: Int}
ShiftEndedPayload = {session_id: Id, participant_ids: Id[], processed_count: Int,
                     score: Int, penalties: Int, ended_at: Time}
DisciplinaryPayload = {disciplinary_action_id: Id, player_id: Id, xp_penalty: Int,
                       reason: string}
```

| Event / routing key | Producer | Durable subscriber queue(s) | Payload / correlation |
| --- | --- | --- | --- |
| `CaseInitialized` / `case.initialized` | Any one of Applicant, Credential, University Record | `applicant.case-initialized.v1`, `credential.case-initialized.v1`, `university-record.case-initialized.v1` | `CaseInitializedPayload`; `correlation_id = case_id` |
| `DecisionScored` / `decision.scored` | Moderation | `session.decision-scored.v1` | `DecisionScoredPayload`; `correlation_id = case_id` |
| `ShiftEnded` / `shift.ended` | Session | `player.shift-ended.v1` | `ShiftEndedPayload`; `correlation_id = session_id` |
| `DisciplinaryActionApplied` / `discipline.applied` | Moderation | `player.discipline-applied.v1` | `DisciplinaryPayload`; `correlation_id = disciplinary_action_id` |

Every subscriber gets its own queue; replicas of a single service share that service's queue. An initializer may consume its own case event as a deduplicated no-op and never republishes a received initialization. Publication must use the same `event_id` for retries. Consumers also deduplicate by the payload's case/decision/shift/disciplinary-action ID, because a producer defect could assign a second event ID to the same business operation.

Transient failures retry at 1, 5, and 30 seconds using delayed retry queues. After those retries, messages move to a durable service-specific dead-letter queue named `<subscriber-queue>.dlq` for inspection/replay. Schema-invalid or conflicting messages go there without retries. Replays keep IDs and remain idempotent. Consumers must not drop messages on failure or requeue without a retry limit.

Broker credentials restrict publishers and consumers to their needed exchanges/queues; only the three initialization services may read hidden `CaseInitialized` payloads. Services retain outbox entries until confirmation and inbox/domain deduplication records for the lifetime of the domain records.

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

### Contract verification scenarios

Before implementing endpoints, review these scenarios together with the owning service developers. Implementation PRs must cover them with relevant unit/integration tests:

- Initialize a case through each of the three entry services; verify all records share its ID, hidden data stays internal, and retries reproduce the original case.
- Deliver an initialization or scoring event twice; verify no extra records, processed applications, XP or penalties. Conflicting payloads must be quarantined.
- Delay one case consumer; readiness remains pending and a decision cannot be submitted/scored from incomplete facts.
- Attempt university-record reads and chat sends with the wrong role, record permission or shift; require denial without leaking facts.
- Publish new rules during an active shift; that shift uses its pinned version and future shifts use the new one.
- Submit two decisions concurrently, end a shift while scoring is in transit, and redeliver the completion event; verify one decision and one complete progression update.
- Reconnect chat after a lost acknowledgement; verify retry deduplication and recovery of persisted history.

## Contribution & workflow guidelines

### Branching model

We follow a Gitflow-inspired branching model with `main`, `dev`, and short-lived feature/task branches:

```text
main (stable / production releases)
 └── dev (integration of current lab)
      ├── feat/lab-X/service-or-feature
      ├── fix/lab-X/issue-description
      ├── docs/lab-X/update-description
      └── chore/lab-X/task-description
```

#### Naming conventions

`main` holds production-ready releases and receives merges only from `dev` at lab completion. `dev` is the integration branch for the current lab.

| Task | Branch pattern | Example |
| --- | --- | --- |
| Feature | `feat/lab-X/service-or-feature` | `feat/lab-1/player-auth` |
| Fix | `fix/lab-X/issue-description` | `fix/lab-0/submodule-link-error` |
| Documentation | `docs/lab-X/update-description` | `docs/lab-0/communication-contracts` |
| Maintenance | `chore/lab-X/task-description` | `chore/lab-0/update-submodules` |

### Commit conventions

Use [Conventional Commits v1.0.0](https://www.conventionalcommits.org/) to keep the git log readable:

`<type>(<scope>): <short summary in imperative mood>`

Use the changed component as the commit scope. Reserve the lab scope for PR titles.

| Type | Use for | Example |
| --- | --- | --- |
| `feat` | New features or service functionality | `feat(game-service): implement websocket cycle timer` |
| `fix` | Bugs, errors, or unwanted behavior | `fix(user-service): fix jwt token expiration validation` |
| `docs` | Documentation only: READMEs, architecture diagrams, API specifications | `docs(readme): add contribution and workflow rules` |
| `style` | Code formatting, such as whitespace or semicolons, without logic changes | `style(player-service): format files according to prettier rules` |
| `refactor` | Code restructuring without behavior changes or new features | `refactor(resource-service): extract database connection logic into helper module` |
| `test` | New or updated unit/integration tests | `test(exam-service): add unit tests for grade calculation endpoints` |
| `chore` | Maintenance, build configuration, dependencies, or submodules | `chore(submodules): link private user-service repository` |

### Merge strategy

| Source | Target | Method | Purpose |
| --- | --- | --- | --- |
| Task branch | `dev` | Squash and Merge | Keep a linear history of completed tasks |
| `dev` | `main` | Rebase and Merge | Preserve milestone history at final lab evaluation |

Delete task branches after merging their PRs into `dev`. Keep `main` and `dev` as permanent branches.

### Versioning strategy

Tag versions only on `main` after completing lab checkpoints or hotfixes:

- Major lab releases use `vX.0.0` after merging `dev` into `main` with all lab requirements complete. Examples: `v0.0.0`, `v1.0.0`, `v2.0.0`.
- Hotfixes on `main` use `vX.0.Y`, for example `v1.0.1`.

### Pull request format

#### PR naming convention

PR titles must use the lab as the Conventional Commits scope:

`<type>(lab-X): <short imperative summary>`

Examples:

- `docs(lab-0): define architecture diagram and workflow rules`
- `feat(lab-1): implement JWT authentication in player service`

#### PR description template

All PRs targeting `dev` or `main` must use this format:

```markdown
## Why?
[Explain the goal or problem this PR addresses]

## Changes
[Brief overview of the technical approach/implementation and changes included]

## How to Test?
[Provide step-by-step instructions on how reviewers can verify these changes]

## Screenshots / Evidence (Optional)
[Attach screenshots, API test output, or logs if applicable]
```

#### PR reviewing process

`main` and `dev` require a PR, at least one peer approval on the latest changes (CPR only), resolved review threads, and linear history. All CI pipelines and tests must pass before merging. Both branches block force pushes and deletion; repository administrators have no configured bypass. `dev` permits squash merges, and `main` permits rebase merges.

The required `PR policy` check validates PR titles, branch names and targets, and required description sections. PRs into `main` must come from this repository's `dev`; task PRs target `dev`.

Lab 0 has a PR workflow check with no service-code coverage target. For later implementation PRs, the recommended code coverage target is 69%. Focus unit and integration tests on critical business logic, security and authorization boundaries, and core contract flows. Exhaustive line coverage is not the goal.

Reviewers check:

- Code quality, readability, and modularity
- Branch and commit naming
- Test coverage and endpoint functionality
- Security and secret protection

### Example lab workflow

#### 1. Task development

- Update local `dev`, then branch off it: `git checkout -b <type>/lab-X/<description>`. You can also create the task branch from `origin/dev`.
- Commit changes: `git commit -m "<type>(<scope>): <summary>"`
- Push and open a PR targeting `dev`.

#### 2. Peer review and integration

- Request at least one peer approval.
- Verify CI checks, submodule pointers, and absence of secrets.
- Merge into `dev` using Squash and Merge.

#### 3. Lab completion and release

- Open a PR from `dev` to `main` once the lab requirements are met.
- Perform final testing and submission verification.
- Merge into `main` using Rebase and Merge.
- Fetch and switch to the released `main` before tagging; do not tag the task branch or `dev`.
- Tag the release on `main`: `git tag -a vX.0.0 -m "Lab X completion"` && `git push origin vX.0.0`

## Project board

The team tracks lab tasks, issues, and progress on the [GitHub Project Board](https://github.com/orgs/ChillGuysStudio/projects/2).
