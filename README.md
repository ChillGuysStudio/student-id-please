# Topic 3 - Student ID, please

## Service Boundaries

Each service is the only writer to the data it owns. Other services use APIs to request that data or consume events containing the data they need. Data copied into a local projection does not become a new source of truth.

### Player Service

*Responsible for global player identity, user authentication, profile management, and persistent moderator progression.*

The Player Service owns:

- player accounts and authentication
- player profiles and friendships
- moderation teams and team membership
- XP, levels, and persistent progression

It updates progression from completed-shift and disciplinary events. It does not own applicants, moderation-session roles, admission decisions, or session scores.

### Server Moderation Session Service

*Manages active Discord moderation shifts, session rosters, assigned moderator roles, and aggregate shift scoring.*

The Server Moderation Session Service owns:

- moderation-shift creation and lifecycle
- the participant roster and the Moderator or Junior Moderator role assigned to each participant
- the current applicant reference
- the number of processed applications
- the aggregate shift score and penalties

It consumes individual outcomes from the Moderation Service and calculates the overall shift result. When a shift ends, it publishes the result for the Player Service to apply to player progression.

It does not own player accounts or progression, applicant details, individual admission decisions, server rules, or chat messages.

### Applicant Service

*Generates and maintains the profiles, claims, and background details of individuals attempting to join the Discord server.*

The Applicant Service owns the applicant profile and the claims presented by the applicant. These claims can include the applicant's name, student ID, major, year, university status, courses, and role.

An applicant can claim to be a FAF student, a student from another major, a teaching assistant, a university staff member, an alumnus, or an outsider. The claims may be false or may impersonate another person.

The service does not own submitted credentials, authoritative university records, credential-validation results, or admission decisions.

### Credential Service

*Validates the structural authenticity and integrity of physical or digital verification documents presented by applicants.*

The Credential Service owns:

- documents and credentials presented by an applicant
- structural and authenticity checks
- the validation result for each credential

Credentials can include a student ID, a university email, an enrollment confirmation, or an ELSE course registration. A credential can be expired, forged, inconsistent, or incomplete.

The service does not own the applicant's claimed identity, authoritative university records, access rules, or admission decisions. A valid credential does not by itself grant access to the Discord server.

### Server Rules Service

*Maintains active server access policies and evaluates applicant claims against current shift entry requirements.*

The Server Rules Service owns versioned rules for accessing the Discord server. It evaluates applicant claims, credential results, university facts, and moderation history against the rule version active for the shift.

Rules can restrict access by major, year, enrollment duration, university role, allowed channels, or an existing ban. The service returns the expected policy result and the rules that matched.

It does not own applicant data, credentials, university records, bans, moderator actions, or scoring. The Moderation Service owns the comparison between the expected policy result and the Moderator's decision.

### University Record Service

*Stores authoritative university databases and enforces player permission limits for inspecting verification records.*

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

*Executes admission decisions (Accept, Reject, Flag, Ban) and evaluates decision correctness against server rules.*

The Moderation Service owns:

- the Moderator's Accept, Reject, Flag, or Ban action for each applicant
- decision history and active bans
- the server-rule result used for the decision
- the correctness, violated rules, outcome, and penalty for one decision

The service obtains the required facts from the Applicant, Credential, University Record, and Server Rules services. It compares the Moderator's action with the result returned by the Server Rules Service, then publishes the decision outcome to the Server Moderation Session Service.

It does not own the source applicant data, credentials, university records, rule definitions, or aggregate shift score.

### Discord DMs Service

*Facilitates real-time, WebSocket-based communication across role-restricted moderation channels during active shifts.*

The Discord DMs Service owns moderation channels, channel membership, messages, and real-time message delivery over WebSockets. Session channels can include:

- `#enrollment-check`
- `#faculty-check`
- `#course-registration`
- `#general-mod-chat`

The service uses session roles and university-record permissions when granting channel access. It does not own those roles or permissions. It transports messages but does not verify whether their contents are correct.

### Applicant case initialization

The Applicant, Credential, or University Record service may receive the initial request for a new applicant case. Whichever service receives this first request generates the authoritative `case_id` and publishes a `CaseInitialized` event containing this `case_id` along with the generation payload to the event broker.

To maintain strict data consistency across services:
- **ID Reuse:** Receiving services consume the event and reuse the provided `case_id` to create only the domain records they own.
- **Idempotency:** Receiving services must handle duplicate or concurrent initialization events idempotently (e.g., enforcing a `UNIQUE(case_id)` constraint or performing upserts) to prevent duplicate records or mismatched IDs for the same applicant case.

No service writes directly to another service's database. The shared `case_id` links the applicant profile, credentials, university records, moderation decision, and session entry across isolated databases without violating data ownership boundaries.

## Architecture Diagram

<img src="docs/architecture.svg" alt="Architecture Diagram" width="1080"/>


## Technologies and Communication Patterns

This is the proposed Lab 0 design for implementation in later labs. The language and framework mapping follows the architecture diagram. Endpoint paths, schemas, PostgreSQL storage, and delivery rules below are the team's reviewable contract proposal; they do not imply that services already run.

| Service | Language / framework | Storage owned by service | Communication |
| --- | --- | --- | --- |
| Player | Python / FastAPI | PostgreSQL: accounts, profiles, friendships, teams, progression | REST; consumes `ShiftEnded` and `DisciplinaryActionApplied` |
| Server Moderation Session | Python / FastAPI | PostgreSQL: shifts, participants, roles, case references, score | REST; consumes `DecisionScored`; publishes `ShiftEnded` |
| Applicant | Java / Spring Boot | PostgreSQL: applicant claims and case initialization metadata | REST; publishes/consumes `CaseInitialized` |
| Credential | Java / Spring Boot | PostgreSQL: submitted credentials and validation results | REST; publishes/consumes `CaseInitialized` |
| Server Rules | Java / Spring Boot | PostgreSQL: immutable rule versions | Internal REST policy evaluation; REST for shift rules |
| University Record | Java / Spring Boot | PostgreSQL: university facts and record permissions | REST; publishes/consumes `CaseInitialized` |
| Moderation | Python / FastAPI | PostgreSQL: decisions, policy snapshots, bans, disciplinary actions | REST orchestration; publishes `DecisionScored` and `DisciplinaryActionApplied` |
| Discord DMs | Python / FastAPI | PostgreSQL: channels, memberships, messages | REST for channel/history access; WebSockets for live chat |

### Selection rationale and trade-offs

- **Python / FastAPI:** Player APIs, session orchestration, moderation decisions and live DMs involve many network waits and relatively small transformations. FastAPI's typed request models and asynchronous HTTP/WebSocket support fit this group, while Python keeps scoring and orchestration concise. Blocking database/broker operations must use appropriate drivers or workers, and CPU-heavy work must not block live chat. Maintaining Python alongside Java costs additional tooling, but satisfies the required two-language team split.
- **Java / Spring Boot:** Applicant generation, document validation, versioned policy evaluation and authoritative university records share structured domain models and invariants. Java's types and Spring's validation, security and transaction facilities suit these services and their isolated databases. The trade-off is more configuration and runtime overhead; using one framework throughout the case-data group keeps its implementation conventions consistent. Initial generation is bounded and deterministic, without external AI calls.
- **PostgreSQL per service:** Transactions and unique constraints suit team membership, one final decision per case, and duplicate-event protection. JSONB can hold variable credential details while identifiers and relationships remain typed columns. A common database engine reduces operational learning, but each service gets its own database and credentials, with no cross-service SQL or shared tables. One PostgreSQL server may host those isolated databases in a lab environment; this saves resources but shares its failure domain.
- **REST / HTTP with JSON:** Immediate reads and commands use request/response communication. Human-readable JSON is easy to inspect during a lab demonstration and supported by both frameworks. It is more verbose than Protobuf and provides no distributed transaction; callers need explicit timeout, retry, and unavailable responses. UUIDs are JSON strings, which avoids language-specific integer serialization issues.
- **RabbitMQ / AMQP:** Case initialization, decision scoring, and progression propagation use durable events so producers do not depend on consumers being available at the same instant. This introduces eventual consistency, duplicate delivery, and broker operations; the contract defines readiness, deduplication, and an outbox instead of assuming exactly-once delivery.
- **WebSockets:** DMs need server-to-client delivery while the shift is active. A persistent connection avoids repeated polling, but requires reconnect/history recovery and permission rechecks. Messages are persisted before broadcast; clients recover missed messages through the REST history endpoint.
- **API Gateway:** One public entry point routes REST and the WebSocket upgrade, verifies player authentication, and applies request limits. This simplifies client routing but adds a shared dependency. Each service still enforces its own authorization. The gateway implementation is an infrastructure choice to be agreed before deployment; it is not an additional domain service.

### Interaction map

The diagram is the overview; this table specifies the full planned interactions, including authorization and event paths omitted from the drawing for readability.

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

## Communication Contract

### Data ownership and consistency

Each service is the sole writer of its database. Cross-service reads use the APIs below; events maintain local projections that are never a new authority. Database foreign keys stay within one service. Cross-service UUID references are validated through the owner API, and cached data is rechecked for authorization-sensitive operations. University records describe simulated people; the `subject_id` identifies the person in those authoritative records, while `case_id` identifies the particular application. Bans use `subject_id`, so returning under a new case does not discard a ban. A case may have no known university subject.

Mutations and their pending events are committed in the same local database transaction using an **outbox**. A publisher retries until RabbitMQ confirms receipt. Consumers commit a unique `(consumer, event_id)` inbox record with their domain update before acknowledging. Domain constraints such as `UNIQUE(case_id)`, `UNIQUE(session_id, case_id)` for final decisions, and `UNIQUE(session_id)` for applied shift progression also prevent semantic duplicates. There is no distributed transaction: partially initialized cases remain pending, and downstream failures never become negative admission decisions.

### Shared REST conventions

- Public paths below are gateway paths under `/api/v1`. Internal paths start with `/internal/v1` and are never routed publicly. Each endpoint belongs to the named service.
- Requests and non-empty responses use `application/json`. Field names use `snake_case`. `Id` means a UUID string; `Time` means an RFC 3339 UTC timestamp string; `Int` is a signed 32-bit integer; `Bool` is a boolean. Scores may be negative; counts are non-negative. `T[]` means an array of `T`; `T?` means an optional field; `T | null` means a required nullable field. All other fields are required. Objects below are type notation, not JSON literals.
- Authentication uses `Authorization: Bearer <access_token>`. Player owns token issuance. Services verify signature, issuer, audience, and expiry. Access tokens expire after 15 minutes. Refresh tokens are opaque, stored hashed, expire after 7 days, and rotate on use; logout revokes the refresh session. Global `admin` is provisioned administratively and cannot be selected during registration. Shift roles come from Session, never a client-submitted role claim.
- Internal calls use service credentials scoped to caller, receiver and operation. A service identity alone does not authorize an arbitrary player action: the initiating player's identity is propagated in verified auth context and checked against Session. Player-facing responses never include hidden generation data, expected decisions, or another player's restricted records.
- Every mutating REST request includes `Idempotency-Key: <UUID>`. An identical retry to the same endpoint by the same caller returns the original status/body; key reuse with a different body returns `409`. Keys and results remain for the lifetime of the associated case/shift; authentication operations retain them for 24 hours, and clients must not retry outside that window. Replays still require valid authorization. Clients retry a case-start request through the same entry service using the same key; routing the same logical request to a different service is not supported.
- Collections use optional `limit: Int` (default 50, range 1–100) and `cursor: string` query parameters. `Page<T> = {items: T[], next_cursor: string | null}`; cursors are opaque and scoped to the caller and resource. Stable ordering uses creation time then ID. Empty collections return `200` with `items: []`.
- Common error shape: `Error = {code: string, message: string, request_id: Id, details: {field: string, reason: string}[]}`. Do not include hidden facts, secrets, or stack traces. Common statuses are `400` malformed request, `401` invalid auth, `403` insufficient permission, `404` absent resource, `409` state/key conflict, `422` invalid field values, `429` rate limit, and `503` unavailable dependency. An existing but unfinished case returns `409 CASE_NOT_READY` with `Retry-After: 1`, never an empty result interpreted as false facts. Rate limits also include `Retry-After` seconds. Tables specify success responses; these common errors apply wherever relevant.
- Internal reads have a 2-second timeout. Only safe reads and commands carrying the original idempotency key may retry, at most twice with backoff. A failed dependency returns `503`; the caller does not fabricate facts or correctness. Pagination, timeout and size values are initial contract defaults to review during implementation.

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

`UniversityRecord.data` must match `kind` in the listed order; no arbitrary object payload is accepted. `student_id` is a presented or university identifier, never the database case key. Empty record arrays mean an authoritative completed lookup found no records. The full record set can be read only by authorized internal consumers; player inspection is filtered by permission. Credential validation authenticates documents independently of access policy. `authentic` in generation inputs is private metadata and is not a field of the player-visible credential.

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

Player consumes progression events, not client XP commands. Completed-shift XP is `max(0, score)` for each participant. Store those awards and distinct disciplinary `xp_penalty` deductions in a progression ledger; total XP is `max(0, sum(awards) - sum(deductions))`. Recompute from that ledger so different delivery orders produce the same result. Level is `1 + floor(xp / 100)`. Shift decision penalties are already part of the final score and must not also produce disciplinary deductions.

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

A shift starts with one Moderator and at least two Junior Moderators, so record permissions can be distributed. Session serializes case-start and end commands. It calls exactly one of the three internal initializer endpoints below using a persisted idempotency key and verified Moderator context; if the response is lost it retries that same service/key. It never fails over that command to a different initializer. Initialization metadata pins the scenario and seed once, even for `random`. Each service still initializes its own records and can be the first service contacted, as required by Topic 3.

Normal gameplay always requests the internal `random` scenario; fixed scenarios are internal test fixtures. Players cannot choose or inspect the hidden scenario/seed. A case's status endpoint reports readiness only.

Only one case is current at a time. A new case is allowed after the current case's `DecisionScored` has been applied. Session accepts a score event only for its current case and only once per decision; it increments `processed_count`, adds `score_delta`, and accumulates `penalty`. Ending a shift with an undecided/pending current case returns `409`; if a submitted decision's event is still in transit, end waits in `ending`. The final `ShiftEnded` is published only after all accepted decisions are counted. Case starts and decisions reject `ending`/`ended` shifts. Clients poll `GET /sessions/{session_id}` until completion; timeout does not imply completion.

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

The first service creates `case_id`, materializes a coherent `Generation` payload, saves only its own domain records, and emits `CaseInitialized`. All IDs inside the payload must match that case. The other services reuse the event's IDs and typed values; they do not independently randomize received facts. False claims, forged credentials and impersonation are deliberate differences inside that payload, not accidental inconsistencies. For impersonation, `subject_id` is the actual simulated applicant and presented claims may refer to another person. The initializer's payload is a generation instruction, not an alternate authoritative record database. Each domain owner validates and persists its portion; immutable initialization facts are then read from that owner.

Consumers may receive the same event repeatedly. The same case with conflicting initialization data is rejected and quarantined, never overwritten with an upsert. A service marks local state ready only after committing its records; Session considers the case ready only when all three are ready. A `404` from a consumer during propagation counts as pending. Failed/quarantined initialization remains pending for operator repair, and no decision is scored until readiness is restored. Hidden generation payloads are available only to these services.

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

Rule conditions are discriminated by `kind`. Major/year/duration/credential conditions match when the applicant fails the stated requirement; role/ban conditions match when the stated role/ban exists. University facts are authoritative for identity and enrollment checks; claims are compared against those facts, and a material identity mismatch defaults to `flag` before ordinary access rules. An existing subject ban always returns `ban`. Otherwise, matching rules use ascending priority (ties resolved by rule ID); the first determines action/channels, with the default used when none match. Matched requirement failures populate `violated_rule_ids`. Channels are empty for any non-accept action. Months mean completed calendar months at shift start. Each credential required by the rules must pass; a missing required credential fails. Rules and their versions are immutable after publication, and updates create a new version. The proposed initial policy vocabulary is intentionally bounded; new rule kinds require a versioned schema update.

### University Record Service endpoints

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `PUT /api/v1/sessions/{session_id}/record-permissions` | Session owner while lobby is open | `{permissions: Permission[]}` | `200 {permissions: Permission[]}`; complete replacement for Junior Moderators only |
| `GET /api/v1/sessions/{session_id}/record-permissions/me` | Participant | None | `200 Permission`; Moderator has no direct record permissions |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/university-records` | Junior Moderator in active shift | Required query `kind: RecordKind`; pagination | `200 Page<UniversityRecord>`; unassigned kind gives `403` |
| `GET /internal/v1/sessions/{session_id}/record-permissions/{player_id}` | DMs or Session | None | `200 Permission` |
| `GET /internal/v1/cases/{case_id}/university-records` | Moderation | Query `session_id: Id` | `200 {case_id: Id, subject_id: Id \| null, records: UniversityRecord[]}`; full internal facts |

Permissions freeze at shift start; Session checks that every record kind is assigned to at least one Junior Moderator and no single Junior Moderator has every kind. Starting with an incomplete distribution returns `409`. Thus this initial game configuration needs at least two Junior Moderators. No player can query the internal complete-record endpoint, and the Moderator learns hidden records through DMs. Missing subject records are a valid result for outsiders, not an authorization bypass.

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

Moderation checks Session context and all case data before evaluation. It supplies prior history and bans from its own database to Rules; it never accepts an expected answer from the player. It snapshots `PolicyResult` with the immutable decision. The initial score is `+10` for a correct action and `-5` for an incorrect one (`penalty` is respectively 0 or 5); correctness means the action equals `expected_action`. `flag` is a final outcome for this case, with no investigation workflow in the initial contract. `ban` creates a persistent subject ban in the same transaction as the decision, even if the player chose incorrectly. A ban without an identifiable `subject_id` returns `422 SUBJECT_REQUIRED`; rules must use reject/flag for an unidentifiable outsider. Admissions return allowed channel names; this is a simulation, not a call to Discord's production API.

When creating a ban, evaluate policy against bans that existed **before** this decision, then persist the decision/new ban/outbox atomically. This prevents a newly created ban from making its own action appear correct. Competing decision requests with different keys receive `409` after the first decision wins; retries with the winning key return its original result. Player-visible decision results become available only after commit, so correctness cannot be previewed through an evaluation endpoint.

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

DMs creates the four named session channels idempotently on first access. `#general-mod-chat` admits all participants. The Moderator can join all channels to receive findings. Junior Moderators may join `#enrollment-check` with enrollment or academic-year access, `#faculty-check` with outlook-group or FCIM-message access, and `#course-registration` with course or schedule access. These are permissions to discuss records, not permission to read extra records. DMs verifies Session roles and University Record permissions on connection, history reads and every send; failures deny access. Ended shifts permit authorized history reads but close live connections with code `1000` and reason `SHIFT_ENDED`. Connections also recheck lifecycle/auth expiry on a 30-second heartbeat; expiry closes with `1008`. Query tickets must be redacted from logs, and a consumed/expired ticket cannot reconnect.

All frames are JSON objects:

| Direction / type | Fields | Behavior |
| --- | --- | --- |
| Client `message.send` | `{type: "message.send", client_message_id: Id, channel_id: Id, text: string}` | 1–2000 characters; authenticated author is derived server-side |
| Server `message.ack` | `{type: "message.ack", client_message_id: Id, message_id: Id}` | Sent to author after persistence; duplicate `(author_id, client_message_id)` returns original ack |
| Server `message.created` | `{type: "message.created", message: Message}` | Broadcast only to authorized members; clients deduplicate by `message_id` |
| Server `error` | `{type: "error", client_message_id: Id \| null, error: Error}` | Invalid frame, permission failure or reused ID with different content; no broadcast |

Control-frame ping/pong runs every 30 seconds; two missed responses close the connection. Reconnect requires a new chat ticket and REST history recovery using the last retained pagination cursor; persistent `client_message_id` makes a lost acknowledgement safe to retry. Each channel's history order is stable by `(sent_at, message_id)`; cross-channel delivery order is not guaranteed. If multiple DMs replicas are deployed, fan-out must reach every replica with connected members (for example, dedicated per-replica broker queues), rather than a competing-consumer queue that delivers each chat message to only one replica.

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

Transient failures retry at 1, 5 and 30 seconds using delayed retry queues; after those retries, messages move to a durable service-specific dead-letter queue named `<subscriber-queue>.dlq` for inspection/replay. Schema-invalid or conflicting messages go directly there. Replays keep IDs and remain idempotent. Consumer failures do not silently drop messages or repeatedly requeue without a bound. Broker credentials restrict publishers and consumers to their needed exchanges/queues; only the three initialization services may read hidden `CaseInitialized` payloads. Outbox entries are retained until confirmed; inbox/domain deduplication records remain for the lifetime of the domain records.

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

## Contribution & Workflow Guidelines

### Branching Model

We follow a Gitflow-inspired branching model with `main`, `dev`, and short-lived feature/task branches:

```text
main (stable / production releases)
 └── dev (integration of current lab)
      ├── feat/lab-X/service-or-feature
      ├── fix/lab-X/issue-description
      ├── docs/lab-X/update-description
      └── chore/lab-X/task-description
```

#### Naming Conventions

- **`main`**: Production-ready state. Only receives merges from `dev` upon lab completion.

- **`dev`**: Active integration branch for the current laboratory work.

- **Feature Branches**: `feat/lab-X/service-or-feature`
    - *Example:* `feat/lab-1/player-auth`

- **Fix Branches**: `fix/lab-X/issue-description`
    - *Example:* `fix/lab-0/submodule-link-error`

- **Documentation Branches**: `docs/lab-X/update-description`
    - *Example:* `docs/lab-0/communication-contracts`


- **Chore Branches**: `chore/lab-X/task-description`
    - *Example:* `chore/lab-0/update-submodules`


### Commit Conventions

Our commit strategy is strictly based on the **[Conventional Commits v1.0.0](https://www.conventionalcommits.org/)** specification to maintain a clean and readable git log.

**Commit Format:**
`<type>(<scope>): <short summary in imperative mood>`

* **`feat`**: Used when introducing a brand-new feature or service functionality.
  * *Example:* `feat(game-service): implement websocket cycle timer`
* **`fix`**: Used when patching a bug, error, or unwanted behavior in the codebase.
  * *Example:* `fix(user-service): fix jwt token expiration validation`
* **`docs`**: Used exclusively for documentation updates (README files, architecture diagrams, API specifications).
  * *Example:* `docs(readme): add contribution and workflow rules`
* **`style`**: Used for code style/formatting changes that do not affect logic (white-space, semi-colons, formatting).
  * *Example:* `style(player-service): format files according to prettier rules`
* **`refactor`**: Used for rewriting or restructuring code without changing existing behavior or adding features.
  * *Example:* `refactor(resource-service): extract database connection logic into helper module`
* **`test`**: Used when adding missing unit/integration tests or updating existing test suites.
  * *Example:* `test(exam-service): add unit tests for grade calculation endpoints`
* **`chore`**: Used for routine maintenance, build configuration, dependency updates, or git submodule management.
  * *Example:* `chore(submodules): link private user-service repository`


### Merge Strategy

- **Task branch --> `dev`**: Use *Squash and Merge* to maintain a clean, linear history of completed tasks on the integration branch. GitHub automatically enforces this as the only allowed merge method into `dev`.

- **`dev` --> `main`**: Use *Rebase and Merge* upon final lab evaluation to preserve full milestone history. GitHub automatically enforces this as the only allowed merge method into `main`.

- **Branch cleanup (automatic)**: GitHub deletes the remote task branch after its PR is merged into `dev`. Protected `main` and `dev` remain permanent branches. Closing a PR without merging does not trigger automatic deletion; local branch cleanup is manual.

Contributors still open the PR, request review, and initiate the merge after approval and required checks pass. These settings enforce the merge method; they do not automatically merge PRs.


### Versioning Strategy

Versions are tagged exclusively on `main` upon completing lab checkpoints or hotfixes:

* **Major Lab Releases (`vX.0.0`):** Created when merging `dev` into `main` after completing all lab requirements (e.g., `v0.0.0`, `v1.0.0`, `v2.0.0`).
* **Hotfixes (`vX.0.Y`):** Created if fixes are required on `main` (e.g., `v1.0.1`).

### Pull Request Format

#### PR Naming Convention
PR titles must follow the Conventional Commits scope pattern:  
`<type>(lab-X): <short imperative summary>`

* **Example:** `docs(lab-0): define architecture diagram and workflow rules`
* **Example:** `feat(lab-1): implement JWT authentication in player service`

#### PR Description Template
All PRs targeting `dev` or `main` must use the following structured format:

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

#### PR Reviewing Process

- **Minimum Approvals & Reviewers**: At least one
- **Automated Checks**: All CI pipelines and tests must pass before merging
- **Branch protection (automatically enforced)**: `main` and `dev` require a PR, one peer approval on the latest changes, resolved review threads, and linear history. Force pushes and deletion of these two branches are blocked. Repository administrators have no configured bypass.
- **PR policy check (automatic)**: The required `PR policy` check validates PR titles, branch names/targets and required description sections. PRs into `main` must come from this repository's `dev`; task PRs target `dev`. Contributors choose the target when opening the PR; the check rejects an invalid target.
- **Test coverage policy**: Lab 0 has a PR workflow check, with no service-code coverage target. Later implementation PRs must include tests for changed behavior and the relevant contract scenarios above, including authorization and failure paths; agree numerical coverage targets in each service before implementation.
- **Review Criteria**:
  - Code quality, readability, and modularity
  - Adherence to branch and commit naming standards
  - Test coverage and endpoint functionality
  - Security considerations and secret protection


### Example Lab Workflow

**1. Task Development**
* Branch off `dev`: `git checkout -b <type>/lab-X/<description>`
  (First update your local `dev`, or explicitly create the task branch from `origin/dev`.)
* Commit changes: `git commit -m "<type>(<scope>): <summary>"`
* Push and open PR targeting `dev`

**2. Peer Review & Integration**
* Request at least 1 peer approval
* Verify CI checks, submodule pointers, and lack of secrets
* Merge into `dev` using **Squash and Merge**
* GitHub automatically deletes the merged remote task branch; remove your local copy when no longer needed.

**3. Lab Completion & Release**
* Open PR from `dev` to `main` when lab requirements are met
* Perform final testing and submission verification
* Merge into `main` using **Rebase and Merge**
* Fetch and switch to the released `main` before tagging; do not tag the task branch or `dev`.
* Tag release on `main`: `git tag -a vX.0.0 -m "Lab X completion"` && `git push origin vX.0.0`


## Project Board

**[Github Project Board](https://github.com/orgs/ChillGuysStudio/projects/2)** - Tracks lab tasks, issues, and progress across all team members.
