# Service APIs

Common API behavior comes from the [HTTP contract](http.md). Shared payloads use the [domain types](domain.md). [Integration principles](../integration.md) describe mocked and integrated deployments.

## Player Service endpoints
```text
Player = {player_id: Id, username: string, display_name: string, xp: Int, level: Int}
Tokens = {access_token: string, refresh_token: string, expires_in: Int, token_type: "Bearer"}
Team = {team_id: Id, name: string, owner_id: Id, member_ids: Id[]}
Friendship = {friendship_id: Id, requester_id: Id, recipient_id: Id,
              status: "pending" | "accepted"}
```

| Method and path | Authorized caller | Request body or query | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/players` | Anonymous | `{username: string, email: string, password: string, display_name: string}` | `201 Player`<br>Username and email are unique. The service stores a password hash and never returns it. |
| `POST /api/v1/auth/login` | Anonymous | `{email: string, password: string}` | `200 Tokens`<br>Wrong credentials return `401`. |
| `POST /api/v1/auth/refresh` | Refresh-token holder | `{refresh_token: string}` | `200 Tokens`<br>The service atomically revokes the old refresh token. |
| `POST /api/v1/auth/logout` | Refresh-token holder | `{refresh_token: string}` | `204`, no body |
| `GET /api/v1/players/me` | Player | None | `200 Player` |
| `PATCH /api/v1/players/me` | Player | `{display_name: string}` | `200 Player`<br>The request cannot change XP or level. |
| `GET /api/v1/players/{player_id}` | Player | None | `200 Player`<br>The response excludes email, password, and token fields. |
| `POST /api/v1/friendships` | Player | `{recipient_id: Id}` | `201 Friendship` in pending state |
| `PUT /api/v1/friendships/{friendship_id}/acceptance` | Recipient | Empty object | `200 Friendship` in accepted state |
| `GET /api/v1/friendships` | Player | Pagination | `200 Page<Friendship>` for the caller |
| `DELETE /api/v1/friendships/{friendship_id}` | Either participant | None | `204`, no body<br>Removes a friendship or declines a request. |
| `POST /api/v1/teams` | Player | `{name: string}` | `201 Team`<br>The caller becomes the owner and a member. |
| `GET /api/v1/teams/{team_id}` | Team member | None | `200 Team` |
| `POST /api/v1/teams/{team_id}/members` | Team owner | `{player_id: Id}` | `200 Team`<br>The target must be an accepted friend. |
| `DELETE /api/v1/teams/{team_id}/members/{player_id}` | Owner or departing member | None | `200 Team`<br>The owner cannot leave without deleting the team. |
| `DELETE /api/v1/teams/{team_id}` | Owner | None | `204`, no body<br>Historical shift rosters remain snapshots. |
| `GET /internal/v1/players/{player_id}` | Session or Moderation | None | `200 Player` |
| `GET /internal/v1/teams/{team_id}` | Session | None | `200 Team` |
| `POST /internal/v1/events` | Authenticated Session or Moderation producer | `ShiftEnded` or `DisciplinaryActionApplied` event | `200 {event_id: Id, applied: Bool}` |
| `GET /.well-known/jwks.json` | Anyone | None | `200` public verification keys |
| `GET /health` | Anyone | None | `200` process health |
| `GET /ready` | Anyone | None | `200` when configured dependencies are ready |

The internal event adapter supports authenticated fixtures when broker delivery is unavailable. It uses the same progression handler and deduplication rules as RabbitMQ. The authenticated producer must match the event type.

The Player Service consumes progression events. It does not accept client commands that change XP. Each participant receives `max(0, score)` XP when a shift ends. The service stores shift awards and separate disciplinary `xp_penalty` deductions in a progression ledger. Total XP is `max(0, sum(awards) - sum(deductions))`.

The service recalculates XP from the ledger so event delivery order cannot change the result. A player's level is `1 + floor(xp / 100)`. The final shift score already includes decision penalties, so the Player Service does not deduct them again.

## Server Moderation Session Service endpoints

```text
Participant = {player_id: Id, role: Role}
Session = {session_id: Id, team_id: Id, owner_id: Id,
           status: "lobby" | "active" | "ending" | "ended",
           participants: Participant[], rule_version: Id | null, started_at: Time | null,
           university_snapshot_id: Id | null,
           current_case_id: Id | null, processed_count: Int, score: Int, penalties: Int}
CaseStatus = {case_id: Id, session_id: Id, state: "pending" | "ready",
              ready_services: ("applicant" | "credential" | "university_record")[]}
SessionContext = {session: Session, player: Participant}
```

| Method and path | Authorized caller | Request body or query | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/sessions` | Team member | `{team_id: Id}` | `201 Session`<br>The caller owns the lobby and starts with the Moderator role. |
| `GET /api/v1/sessions` | Player | Pagination | `200 Page<Session>` for sessions that the caller joined |
| `POST /api/v1/sessions/{session_id}/participants` | Member of that team | Empty object | `200 Session`<br>The caller joins as a Junior Moderator while the lobby is open. |
| `PUT /api/v1/sessions/{session_id}/roles` | Session owner | `{participants: Participant[]}` | `200 Session`<br>The body includes the complete roster with exactly one Moderator. |
| `GET /api/v1/sessions/{session_id}` | Participant | None | `200 Session` |
| `POST /api/v1/sessions/{session_id}/start` | Session owner | Empty object | `200 Session`<br>Pins the current published rules and a university snapshot; freezes roster and roles. |
| `POST /api/v1/sessions/{session_id}/cases` | Assigned Moderator | `{entry_service: "applicant" \| "credential" \| "university_record"}` | `202 CaseStatus`<br>Calls the selected initializer with internal scenario `random` and reserves the current-case slot. |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` | Participant | None | `200 CaseStatus`<br>The service queries readiness from all three case owners. |
| `POST /api/v1/sessions/{session_id}/end` | Session owner | Empty object | `200 Session` in `ended`, including retries. An unfinished case returns `409`. |
| `DELETE /api/v1/sessions/{session_id}` | Session owner, lobby only | None | `204`, no body |
| `GET /internal/v1/sessions/{session_id}/context` | Case services, Moderation, Rules, University Record, or DMs | Query `player_id: Id` | `200 SessionContext`<br>The service validates participation. Callers check the required role and status. |
| `POST /internal/v1/events` | Authenticated Moderation producer | `DecisionScored` event | `200 {event_id: Id, applied: Bool}` |
| `GET /health` | Anyone | None | `200` process health |
| `GET /ready` | Anyone | None | `200` when configured dependencies are ready |

The internal event adapter supports scoring fixtures and uses the same inbox and business-ID checks as RabbitMQ delivery.

A shift starts with one Moderator and at least two Junior Moderators. The Server Moderation Session Service serializes commands that start a case or end the shift. For each case, it calls one of the three internal initializer endpoints with a stored idempotency key and verified Moderator context. If the response is lost, it retries the same service with the same key. It does not send the retry to another initializer.

Initialization metadata fixes the scenario and seed, including when the request specifies `random`. Each case service initializes its own records. Any of the three case services can receive the initial request, as Topic 3 requires.

Session reserves `started_at` once for a start attempt and passes it as `reference_at` when creating the university snapshot. A retry uses the same timestamp and idempotency key. The shift stays in the lobby until permissions, rules, and snapshot are available; it never starts with partially pinned configuration. `university_snapshot_id` is a reference only: its hidden contents are not included in public session responses.

Normal gameplay requests the internal `random` scenario. Fixed scenarios are internal test fixtures. Players cannot choose or inspect the hidden scenario or seed. The case-status endpoint reports only readiness.

Only one case can be current. The Server Moderation Session Service allows a new case after it applies `DecisionScored` for the current case. It accepts one event for that case and rejects events for other cases. The service then increments `processed_count`, adds `score_delta`, and accumulates `penalty`.

Ending a shift with a pending or undecided case returns `409`. A scoring event still in transit also returns `409`. The owner can retry after Session applies the event. Session commits the final result and its `ShiftEnded` outbox entry together, then returns `200`. The worker publishes the event after commit. Case-start and new decision requests reject ended shifts. This synchronous end operation does not enter `ending`.

## Applicant Service endpoints
```text
ProfilePresetInput = {label: string, role: ApplicantRole,
                      university_status: "active" | "inactive" | "graduated" | "none",
                      major: string | null, year: Int | null, course_count: Int, enabled: Bool}
ProfilePreset = ProfilePresetInput & {preset_id: Id}
```

Presets describe reusable generation choices rather than existing applicants. Labels contain 1 to 120 trimmed characters, and course counts range from 0 to 10. Seed these enabled presets once, with IDs assigned by the service:

| Label | Role | Status | Major | Year | Course count |
| --- | --- | --- | --- | --- | --- |
| FAF first year | `student` | `active` | FAF | 1 | 2 |
| FAF second year | `student` | `active` | FAF | 2 | 2 |
| IA second year | `student` | `active` | IA | 2 | 2 |
| FAF teaching assistant | `teaching_assistant` | `active` | FAF | 4 | 2 |
| University staff | `staff` | `active` | null | null | 0 |
| FAF graduate | `alumnus` | `graduated` | FAF | null | 0 |
| Visitor | `outsider` | `none` | null | null | 0 |

`eligible`, `forged`, and `impersonation` select enabled non-outsider presets compatible with the pinned snapshot; `outsider` uses outsider fields. A new alumni ID uses admission year `A - study_years`; an inactive student uses admission year `A - year + 1`, keeps the preset's last year, and has no courses. Staff have `enrolled_since = null`. Supplied reference subjects take precedence. The Applicant Service validates CRUD syntax, then checks program and course compatibility against the pinned snapshot during generation. An empty compatible preset set fails generation without changing the preset's major or year.

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/admin/applicant-presets` | Global admin | `ProfilePresetInput` | `201 ProfilePreset` |
| `GET /api/v1/admin/applicant-presets` | Global admin | Pagination | `200 Page<ProfilePreset>` |
| `GET /api/v1/admin/applicant-presets/{preset_id}` | Global admin | None | `200 ProfilePreset` |
| `PUT /api/v1/admin/applicant-presets/{preset_id}` | Global admin | Full `ProfilePresetInput` | `200 ProfilePreset` |
| `DELETE /api/v1/admin/applicant-presets/{preset_id}` | Global admin | None | `204`, no body; existing case snapshots remain |
| `GET /api/v1/sessions/{session_id}/applicants/{case_id}` | Assigned Moderator in active shift | None | `200 Applicant` with presented claims only |
| `GET /internal/v1/applicants/{case_id}` | Moderation | Query `session_id: Id` | `200 Applicant`<br>The service verifies that the case belongs to the shift. |

## Credential Service endpoints

```text
CredentialTemplateInput = {kind: CredentialKind, issuer: string,
                           validity_days: Int | null, enabled: Bool}
CredentialTemplate = CredentialTemplateInput & {template_id: Id}
```

Seed one enabled template per kind using the issuer table and `validity_days = null`, which expires the document at the academic-year end. Issuer contains 1 to 120 characters. A positive number sets expiry to `issued_at + validity_days * 24 hours`. Each kind may have one enabled template; a duplicate returns `409 TEMPLATE_ALREADY_ENABLED`. PUT cannot change a template's kind. Templates control issuance defaults. Field schemas and applicant identities come from the shared contract, and new credential kinds require a schema change. Missing templates for required kinds return `409 GENERATION_DATA_UNAVAILABLE`. Templates produce usable documents. Tests pass expiry and structure defects to the same generator and validator through fixtures instead of public case-edit endpoints.

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/admin/credential-templates` | Global admin | `CredentialTemplateInput` | `201 CredentialTemplate` |
| `GET /api/v1/admin/credential-templates` | Global admin | Pagination | `200 Page<CredentialTemplate>` |
| `GET /api/v1/admin/credential-templates/{template_id}` | Global admin | None | `200 CredentialTemplate` |
| `PUT /api/v1/admin/credential-templates/{template_id}` | Global admin | Full `CredentialTemplateInput` | `200 CredentialTemplate` |
| `DELETE /api/v1/admin/credential-templates/{template_id}` | Global admin | None | `204`, no body; stored documents and validations remain |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/credentials` | Assigned Moderator in active shift | Pagination | `200 Page<Credential>` |
| `POST /api/v1/sessions/{session_id}/credentials/{credential_id}/validation` | Assigned Moderator in active shift | Empty object | `200 Validation`<br>The credential must belong to the current case. |
| `GET /internal/v1/cases/{case_id}/credential-results` | Moderation | Query `session_id: Id` | `200 {case_id: Id, credentials: Credential[], validations: Validation[]}` with complete results for every credential |

The internal endpoint runs or reuses deterministic validation even if the player did not request validation. Expiry checks use the shift start time, so a replay cannot change the result during a case. Forgery checks use private authenticity metadata. Credentials do not change during an active case.

## Server Rules Service endpoints

```text
Rule = {rule_id: Id, priority: Int, kind: "major" | "year" | "enrollment_duration" |
        "role" | "ban" | "credential", on_match: Action, allowed_channels: string[],
        applies_to_roles: ApplicantRole[],
        condition: MajorCondition | YearCondition | DurationCondition | RoleCondition |
                   BanCondition | CredentialCondition}
MajorCondition = {allowed_majors: string[]}
YearCondition = {min_year: Int, max_year: Int}
DurationCondition = {min_months: Int}
RoleCondition = {roles: ApplicantRole[]}
BanCondition = {active: Bool}
CredentialCondition = {required_kinds: CredentialKind[], require_authentic: Bool,
                       require_unexpired: Bool, require_structurally_valid: Bool}
RuleSet = {rule_version: Id, status: "draft" | "published", rules: Rule[],
           default_action: Action, default_channels: string[], created_at: Time}
PolicyInput = {session_id: Id, case_id: Id, rule_version: Id, claims: Claims,
               subject_id: Id | null, reference_at: Time,
               credentials: Credential[], validations: Validation[],
               university_records: UniversityRecord[], active_bans: Ban[],
               prior_decisions: {action: Action, created_at: Time}[]}
```

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/rule-versions` | Global admin | `{rules: Rule[], default_action: Action, default_channels: string[]}` | `201 RuleSet` in draft state |
| `GET /api/v1/admin/rule-versions` | Global admin | Pagination | `200 Page<RuleSet>` including drafts |
| `PUT /api/v1/rule-versions/{rule_version}` | Global admin | `{rules: Rule[], default_action: Action, default_channels: string[]}` | `200 RuleSet`; full replacement of a draft only |
| `DELETE /api/v1/rule-versions/{rule_version}` | Global admin | None | `204`, draft only; published version returns `409 RULE_VERSION_IMMUTABLE` |
| `POST /api/v1/rule-versions/{rule_version}/publish` | Global admin | Empty object | `200 RuleSet`<br>One transaction makes the version current for future shifts. |
| `GET /api/v1/rule-versions/{rule_version}` | Player | None | `200 RuleSet`<br>Players without `admin` access can read only published versions. |
| `GET /internal/v1/rule-versions/current` | Session | None | `200 RuleSet`<br>If no published version exists, the endpoint returns `409`. |
| `POST /internal/v1/policy/evaluations` | Moderation | `PolicyInput` | `200 PolicyResult`<br>The `rule_version` must match the version pinned to the session. |

The `kind` field identifies each condition type. `applies_to_roles = []` means all verified roles; otherwise skip the rule when the verified role is not listed. The `major`, `year`, `enrollment_duration`, and `credential` conditions match when a requirement fails. The `role` and `ban` conditions match when the specified role or ban exists. Prior decision history is accepted for audit context; the initial condition types do not inspect it.

| Fact/check | Authority and missing-value behavior |
| --- | --- |
| Actual person | `subject_id` from University's internal case response; a claimed student ID cannot identify the ban target |
| Major, year, role, status, enrollment date | Case enrollment/affiliation belonging to the actual subject; no enrollment means role `outsider`, status `none`, and null student fields |
| Email and registered courses | Case Outlook memberships and `Course` rows; reference catalogs alone do not prove membership |
| Credential condition | Credential Service validations, one per returned credential; a missing required document fails the requirement, while a missing validation for an existing document returns `422 INVALID_POLICY_INPUT` |
| Duration | Completed calendar months between authoritative `enrolled_since` and the shift reference time; unknown date or non-active status fails a duration requirement |
| Identity consistency | Compare claims and document holder identities with the actual subject's enrollment. Apply the normalization rules to names and compare IDs as written. Academic claims (major/year/status/role/courses) and claimed email must also agree with authoritative facts |
| Time and policy | `reference_at` and `rule_version` must match Session's pinned values; wall-clock time is not used |

Evaluation order is fixed:

1. Validate input completeness, case/session identity, rule version, and reference time. Dependency failure returns `503`, and Rules does not evaluate an unfinished case.
2. An existing ban for the actual non-null subject returns `ban` with reason `EXISTING_BAN`, regardless of documents.
3. A material claim/identity contradiction returns `flag` with reason `EVIDENCE_MISMATCH`. A truthful outsider with no records remains consistent. Credential validation handles malformed or empty printed fields without treating them as proof of a different identity.
4. Evaluate applicable rules in ascending priority, breaking ties by rule UUID. The first matching rule decides the action and channels. Return all matching rule IDs in that order. The `violated_rule_ids` array contains matching failed requirements and an active-ban condition, while positive role matches stay out of it. If none match, use the defaults.

Null major/year fails the corresponding requirement. Non-active enrollment also fails major/year requirements; a role-scoped rule can exempt staff and alumni. A credential requirement fails if a required kind is missing or any supplied document of a required kind fails a check whose flag is true. An empty `required_kinds` applies checks to all supplied documents and does not itself require a document. Structural, authenticity, and expiry checks remain separate. A month is a completed calendar month, clamping the anniversary day to the last day of the target month.

`PolicyResult.reasons` contains these stable codes as applicable: `EXISTING_BAN`, `EVIDENCE_MISMATCH`, `MAJOR_REQUIREMENT`, `YEAR_REQUIREMENT`, `DURATION_REQUIREMENT`, `CREDENTIAL_MISSING`, `CREDENTIAL_STRUCTURE`, `CREDENTIAL_AUTHENTICITY`, `CREDENTIAL_EXPIRED`, `ROLE_MATCH`, `BAN_MATCH`, or `DEFAULT_POLICY`. Deduplicate them in evaluation order. `BAN_MATCH` explains a configurable ban condition, including `active = false`; an existing active ban short-circuits first in normal evaluation. Early built-in results have empty rule-ID arrays because Rules evaluated no configurable rules. Every non-accept action has no channels. If a configured rule or default would ban an unidentified subject, return `reject` and append `SUBJECT_UNIDENTIFIED`. Moderation must receive an action it can execute.

### Baseline rules fixture

Seed one published ruleset with `default_action = reject` and no default channels. The labels below describe rules; persist real UUIDs as `rule_id`. Administrators can edit this data in future drafts. It contains no hidden scenario mappings.

| Priority | Roles in scope | Condition | Action / channels |
| --- | --- | --- | --- |
| 10 | `student`, `teaching_assistant`, `staff`, `alumnus` | Credential: required enrollment confirmation; require structure only | `flag` / none |
| 11 | All | Credential: all supplied kinds; require structure only | `flag` / none |
| 20 | All | Credential: all supplied kinds; require authenticity only | `ban` / none |
| 30 | All | Credential: all supplied kinds; require unexpired only | `reject` / none |
| 40 | `student`, `teaching_assistant` | Major allowed: `[FAF]` | `reject` / none |
| 50 | `student`, `teaching_assistant` | Year range: 1 to 4 | `reject` / none |
| 60 | `student` | Year range: 2 to 4 | `accept` / `general` (first-year limitation) |
| 70 | All | Role is `staff` or `teaching_assistant` | `accept` / `general`, `teachers` |
| 80 | All | Role is `student` | `accept` / `general`, `dark-memes`, `groapa` |
| 90 | All | Role is `alumnus` | `accept` / `general`, `alumni` |

For credential rows, unmentioned check flags are false; priorities 11, 20, and 30 use `required_kinds = []`. The priority-10 role scope lets a truthful outsider reach the default `reject`. An active FAF year 2 `eligible` case is accepted; an honest IA student is rejected; a forged confirmation leads to `ban`; the name-impersonation fixture leads to `flag`; an outsider is rejected. An existing subject ban overrides all five examples. The baseline handles unresolved document structure before authenticity failures. Changing that priority requires a new ruleset rather than a validator change. A later ruleset can add a 24-month duration requirement without changing the generator.

Rules does not subscribe to `CaseInitialized`, fetch generator presets, or receive `seed`, `scenario`, or private generation authenticity flags. It receives the normal `Validation.authentic` result. It may share enum definitions and comparison conventions, but must not regenerate an answer from a seed. Published versions are immutable and retained; an update creates a new draft. New condition types require a versioned schema update.

## University Record Service endpoints

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/admin/university-data` | Global admin | `UniversityDataInput` | `201 UniversityData` |
| `GET /api/v1/admin/university-data` | Global admin | Pagination; optional `kind: UniversityDataKind`, `subject_id: Id` | `200 Page<UniversityData>` |
| `GET /api/v1/admin/university-data/{reference_id}` | Global admin | None | `200 UniversityData` |
| `PUT /api/v1/admin/university-data/{reference_id}` | Global admin | Full `UniversityDataInput` | `200 UniversityData`; kind, subject, and natural code cannot change |
| `DELETE /api/v1/admin/university-data/{reference_id}` | Global admin | None | `204`; live references block deletion with `409 REFERENCE_IN_USE`, snapshots do not |
| `POST /internal/v1/university-identities/reservations` | Applicant, Credential, or University Record initializer | `IdentityReservationInput` | `200 UniversityIdentity`; reserves an unpadded student sequence and university-email suffix in one transaction |
| `GET /internal/v1/university-identities/{subject_id}` | Applicant, Credential, or University Record subscriber | Query `case_id: Id` | `200 UniversityIdentity`; reads an existing reservation for derivation without allocating one |
| `POST /internal/v1/university-snapshots` | Session | `{session_id: Id, reference_at: Time}` | `201 {snapshot_id: Id, session_id: Id, reference_at: Time}`; copies and validates current reference data in one transaction |
| `GET /internal/v1/university-snapshots/{snapshot_id}` | Applicant, Credential, University Record, or Session | None | `200 UniversitySnapshot`; full immutable reference data, internal only |
| `PUT /api/v1/sessions/{session_id}/record-permissions` | Session owner while lobby is open | `{permissions: Permission[]}` | `200 {permissions: Permission[]}`<br>The body replaces all Junior Moderator permissions. |
| `GET /api/v1/sessions/{session_id}/record-permissions/me` | Participant | None | `200 Permission`<br>The Moderator has no direct record permissions. |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/university-records` | Junior Moderator in active shift | Required query `kind: RecordKind` with pagination | `200 Page<UniversityRecord>`<br>An unassigned `kind` returns `403`. |
| `GET /internal/v1/sessions/{session_id}/record-permissions/{player_id}` | DMs or Session | None | `200 Permission` |
| `GET /internal/v1/cases/{case_id}/university-records` | Moderation | Query `session_id: Id` | `200 {case_id: Id, subject_id: Id \| null, records: UniversityRecord[]}` with all internal facts |

Record permissions do not change after a shift starts. The Server Moderation Session Service checks that at least one Junior Moderator can inspect each record kind. It also rejects an assignment that gives one Junior Moderator every kind. An incomplete or invalid assignment returns `409`. These rules require at least two Junior Moderators.

Players cannot call the internal endpoint that returns all records. The Moderator receives hidden record details from Junior Moderators through DMs. An empty record set is valid for an outsider and does not grant access to restricted records.

University reference CRUD accepts entries of existing kinds. Adding a course or person requires no schema change, while a new kind or required field requires a shared schema update. Updates replace the full resource; the API accepts no arbitrary JSON patches. Reference subjects must obey the person-field table, and student IDs and canonical emails are unique among them. Administrators must remove live dependents before deleting a referenced program, course, or subject affiliation. Case snapshots contain copied values and remain intact after live reference deletion. The API provides no PUT, PATCH, or DELETE for generated case records or immutable university snapshots.

Identity reservation is an internal University operation rather than a general Applicant CRUD endpoint. The initializer forwards the signed Session context received with `CaseStart`. University verifies the session and selected initializer, then binds the authenticated service's proposed case ID and subject to the reservation before Session receives `CaseAccepted`. Subscribers issue GET requests after propagation and verify the persisted Session case. The API uses case-oriented paths such as `/internal/v1/{service}/cases`. It omits the reference project's `/api/v1/applicants/next` endpoint and its claimed/actual whole-person payload.

## Moderation Service endpoints

```text
Discipline = {disciplinary_action_id: Id, player_id: Id, reason: string,
              xp_penalty: Int, created_at: Time}
```

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /api/v1/sessions/{session_id}/decisions` | Assigned Moderator in active shift | `{case_id: Id, action: Action, reason: string}` | `201 Decision`<br>Each current case has one final decision. |
| `GET /api/v1/sessions/{session_id}/decisions` | Participant | Pagination | `200 Page<Decision>` with committed outcomes only |
| `GET /api/v1/sessions/{session_id}/decisions/{decision_id}` | Participant | None | `200 Decision`<br>The service verifies that the decision belongs to the shift. |
| `GET /api/v1/bans` | Global admin | Optional query `subject_id: Id` with pagination | `200 Page<Ban>` |
| `POST /api/v1/disciplinary-actions` | Global admin | `{player_id: Id, reason: string, xp_penalty: Int}` | `201 Discipline`<br>The penalty cannot be negative and is separate from decision scoring. |

Before evaluation, the Moderation Service checks session context and readiness in all three services, then reads all case data. It takes the actual `subject_id` from University's internal response and uses it for existing bans and history. It sends those facts and the pinned `reference_at` to Server Rules. It excludes generator metadata and any player-supplied expected result. It stores the returned `PolicyResult` with the immutable decision.

A correct action adds 10 points. An incorrect action subtracts 5 points. The `penalty` is 0 for a correct action and 5 for an incorrect action. An action is correct when it equals `expected_action`.

The `flag` action ends the case. It does not start an investigation. The `ban` action creates a persistent ban for the `subject_id` in the same transaction as the decision, even when the action is incorrect. If the case has no `subject_id`, a ban request returns `422 SUBJECT_REQUIRED`. Rules must return `reject` or `flag` for an unidentified outsider. A decision with `action: accept` returns the allowed channel names. It does not call the production Discord API.

Before it creates a ban, the Moderation Service evaluates the policy against bans that existed before the decision. It then stores the decision, the new ban, and the outbox event in one transaction. The new ban therefore cannot make its own decision correct.

When different idempotency keys submit decisions at the same time, the first decision wins. Other requests return `409`. A retry with the winning key returns the original result. Players can read a decision result only after commit, and no endpoint previews whether a proposed decision is correct.

## Discord DMs Service endpoints and WebSocket frames

```text
Channel = {channel_id: Id, session_id: Id, name: string, member_ids: Id[]}
Message = {message_id: Id, client_message_id: Id, channel_id: Id,
           author_id: Id, text: string, sent_at: Time}
```

| Method and path | Authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `GET /api/v1/sessions/{session_id}/channels` | Participant | None | `200 {channels: Channel[]}` with only the caller's channels |
| `GET /api/v1/channels/{channel_id}/messages` | Authorized channel member | Pagination | `200 Page<Message>` in chronological order |
| `POST /api/v1/sessions/{session_id}/chat-tickets` | Participant in active shift | Empty object | `201 {ticket: string, expires_at: Time}`<br>The ticket works once, expires after 30 seconds, and belongs to one player and shift. |
| `GET /api/v1/sessions/{session_id}/ws` (upgrade) | Chat-ticket holder | Query `ticket: string` | `101 Switching Protocols`<br>Authentication errors use REST responses before the upgrade. |

The Discord DMs Service stores only a hash of each chat ticket in Redis. The Redis value contains the player and session IDs and expires after 30 seconds. The service uses `GETDEL` to consume the ticket once.

The Discord DMs Service creates the four session channels on first access. A retry does not create duplicate channels. Every participant can join `#general-mod-chat`, and the Moderator can join all channels.

A Junior Moderator can join `#enrollment-check` with enrollment or academic-year access. Outlook-group or FCIM-message access grants entry to `#faculty-check`. Course or schedule access grants entry to `#course-registration`. Channel membership permits discussion of records but does not grant access to additional records.

Before a client connects, reads history, or sends a message, the Discord DMs Service gets the current role from the Server Moderation Session Service. It gets record permissions from the University Record Service. A failed check denies access. After a shift ends, authorized clients can read history, but the service closes live connections with code `1000` and reason `SHIFT_ENDED`. Every 30 seconds, the service rechecks the shift lifecycle and token expiry. An expired token closes the connection with code `1008`. The service redacts query tickets from logs. A consumed or expired ticket cannot reconnect.

All frames are JSON objects:

| Direction and type | Fields | Behavior |
| --- | --- | --- |
| Client `message.send` | `{type: "message.send", client_message_id: Id, channel_id: Id, text: string}` | `text` contains 1 through 2000 characters. The service derives the author from authentication. |
| Server `message.ack` | `{type: "message.ack", client_message_id: Id, message_id: Id}` | Sent to the author after storage. A duplicate `(author_id, client_message_id)` returns the original acknowledgement. |
| Server `message.created` | `{type: "message.created", message: Message}` | Sent only to authorized members. Clients deduplicate by `message_id`. |
| Server `error` | `{type: "error", client_message_id: Id \| null, error: Error}` | Returned for an invalid frame, a permission failure, or a reused ID with different content. The service does not broadcast it. |

The service sends a WebSocket ping every 30 seconds. Two missed pong responses close the connection. A reconnect requires a new chat ticket. The client then recovers history through REST with its last retained pagination cursor. Reusing `client_message_id` makes it safe to retry after a lost acknowledgement. Each channel sorts its history by `(sent_at, message_id)`. Message order across channels is not defined.

When the Discord DMs Service has multiple replicas, each replica subscribes to the same Redis Pub/Sub channel. The service publishes a message only after it commits the message to PostgreSQL. Redis sends the publication to every connected replica, and each replica forwards it to authorized local connections. Redis does not replay missed publications. Clients recover missed messages from PostgreSQL history and deduplicate them by `message_id`.
