# Server Rules Service integration contract

The planned Server Rules Service uses Java, Spring Boot, and PostgreSQL. It owns versioned access policy. It evaluates the complete evidence that Moderation supplies. The [CPR contract](../../README.md#server-rules-service-endpoints) defines the shared types and evaluation precedence.

## Responsibilities and lifecycle

| Resource | Operations | Mutability |
| --- | --- | --- |
| Draft ruleset | Create, list, read, replace, delete | A global admin can edit it |
| Published ruleset | Publish, read | Immutable and retained for historical shifts |
| Evaluation | POST with evidence, return result | Does not create or modify an applicant case |

An administrator can run and demonstrate full CRUD on drafts. To edit a published ruleset, the administrator creates a new draft. The administrator can use the old version's rules as the create input. Publishing atomically updates the current pointer for future shifts. It never changes the version pinned to a running shift.

Server Rules does not own the final player action, scoring, or bans. Moderation executes an action and compares it with `expected_action`. Server Rules returns policy evidence. It does not call Discord or update progression.

## Dependencies and inputs

- Session reads the current published version when it starts a shift.
- Players read their published rule definitions.
- Moderation submits claims, complete documents and validations, complete university case facts, the actual subject ID, existing bans, and history.
- Server Rules checks the initiating Moderator, the pinned policy, and the reference time through Session context.
- Server Rules does not publish or consume RabbitMQ events. It does not read Applicant presets, Credential templates, or university reference CRUD data.

The scenario and seed are **not policy inputs**. A consistent `eligible` case can fail an access requirement. At this boundary, the normal Credential `Validation.authentic` result replaces private generation authenticity.

## Types

### Relevant shared enums

| Type | Values used by Server Rules |
| --- | --- |
| `Action` | `accept`, `reject`, `flag`, `ban` |
| `ApplicantRole` | `student`, `teaching_assistant`, `staff`, `alumnus`, `outsider` |
| `CredentialKind` | `student_id`, `university_email`, `enrollment_confirmation`, `else_registration` |
| Rule kind | `major`, `year`, `enrollment_duration`, `role`, `ban`, `credential` |
| Rule status | `draft`, `published` |

```text
Rule = {rule_id: Id, priority: Int,
        kind: "major" | "year" | "enrollment_duration" | "role" | "ban" | "credential",
        applies_to_roles: ApplicantRole[], on_match: Action, allowed_channels: string[],
        condition: MajorCondition | YearCondition | DurationCondition | RoleCondition |
                   BanCondition | CredentialCondition}
MajorCondition = {allowed_majors: string[]}
YearCondition = {min_year: Int, max_year: Int}
DurationCondition = {min_months: Int}
RoleCondition = {roles: ApplicantRole[]}
BanCondition = {active: Bool}
CredentialCondition = {required_kinds: CredentialKind[], require_authentic: Bool,
                       require_unexpired: Bool, require_structurally_valid: Bool}
RuleSetInput = {rules: Rule[], default_action: Action, default_channels: string[]}
RuleSet = RuleSetInput & {rule_version: Id, status: "draft" | "published", created_at: Time}
PolicyInput = {session_id: Id, case_id: Id, rule_version: Id, claims: Claims,
               subject_id: Id | null, reference_at: Time,
               credentials: Credential[], validations: Validation[],
               university_records: UniversityRecord[], active_bans: Ban[],
               prior_decisions: {action: Action, created_at: Time}[]}
PolicyResult = {rule_version: Id, expected_action: Action, allowed_channels: string[],
                matched_rule_ids: Id[], violated_rule_ids: Id[], reasons: string[]}
```

The rule `kind` determines the condition shape. Rule IDs must be unique within a ruleset. Priorities must be non-negative. UUID order resolves equal priorities. Lists of codes, roles, kinds, and channels must not contain duplicates. Channel names omit `#`. The bounds are `min_year >= 1`, `max_year >= min_year`, and `min_months >= 0`. A major or role condition must have a non-empty allowed list. Non-accept actions require an empty channel list. This rule also applies to the ruleset default.

`applies_to_roles = []` applies to all verified roles. It does not mean no roles. A credential condition with no required kinds checks all supplied documents, but it does not require a document. An empty `rules` array is valid. After the built-in checks, it produces the defaults. Prior history is available as audit context. No initial condition type reads it.

## HTTP API

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/rule-versions` | Admin | `RuleSetInput` | `201 RuleSet`, draft |
| `GET /api/v1/admin/rule-versions` | Admin | `limit`, `cursor` | `200 Page<RuleSet>` |
| `GET /api/v1/rule-versions/{rule_version}` | Authenticated player/admin | None | `200 RuleSet`. Players see published rulesets only. |
| `PUT /api/v1/rule-versions/{rule_version}` | Admin | Full `RuleSetInput` | `200 RuleSet`, draft only |
| `DELETE /api/v1/rule-versions/{rule_version}` | Admin | None | `204`, draft only |
| `POST /api/v1/rule-versions/{rule_version}/publish` | Admin | `{}` | `200 RuleSet` |
| `GET /internal/v1/rule-versions/current` | Session | None | `200 RuleSet` |
| `POST /internal/v1/policy/evaluations` | Moderation + verified Moderator context | `PolicyInput` | `200 PolicyResult` |

All mutations use `Idempotency-Key`. A publish replay with the original key returns the original result. Publishing an already published version with a different key returns `409 RULE_VERSION_ALREADY_PUBLISHED`. It does not move the current pointer back to an older version. The service serializes concurrent publication locally. The last successful new publication becomes current.

Evaluation is a read-only calculation exposed as POST. A caller can safely retry it with the same complete input while authorization remains valid. Evaluation does not need a mutation idempotency key. Retries and the current wall-clock time do not change the returned policy. List pagination uses `{items, next_cursor}`. The default limit is 50, and the valid range is 1 through 100.

## Validation and evidence sources

Before Server Rules returns a policy result, it performs these checks:

1. Server Rules verifies the Session context. The shift must be active. The Moderator must be assigned. The case must be current. The rule version and reference time must match the pinned values. Moderation must already have confirmed that all three case services are ready.
2. Server Rules checks that embedded credential and record case IDs match `case_id`. It also checks that every object kind matches its schema.
3. Server Rules requires exactly one validation per credential. A missing document is evidence. A missing validation for a supplied document is malformed input. Server Rules never infers `authentic = true` from an absent validation.
4. Server Rules rejects multiple contradictory affiliation rows for the actual subject. Subject-specific university facts must belong to that subject. Global academic-year and schedule rows can have null subjects.
5. Moderation selects the prior decisions for the actual subject as audit context. Server Rules validates every explicit ban subject ID against the actual subject. The initial condition types do not read prior decisions.

| Evidence | Interpretation |
| --- | --- |
| Enrollment/affiliation | Authoritative source for actual first and last names, student ID, major, year, status, role, and enrollment date |
| Outlook entries | Authoritative source for the subject's email and memberships. `member = false` is not active membership. |
| Course rows | `exists` means that the course exists in the catalog. Only `enrolled = true` proves registration. |
| Credentials | Printed assertions and Credential validation. Credentials do not override university identity. |
| Empty university records | Completed absence, not a failed dependency. Truthful outsider fields can agree with it. |
| `subject_id` | Actual applicant for ban lookup. Server Rules never uses an ID parsed from a claim instead. |

Normalize and compare `first_name` and `last_name` independently with the CPR rule. Never concatenate them for identity comparison. Compare academic claims and course sets with the case facts. A blank or invalid printed document field is a structure issue. It is not proof of a different person. Valid printed holder fields or an ID that identifies somebody else are a material contradiction. Inactive enrollment can still have an email record with false membership. Do not infer active enrollment from the address alone.

## Evaluation precedence

| Order | Check | Outcome |
| --- | --- | --- |
| 1 | Existing ban for the actual identified subject | `ban`, reason `EXISTING_BAN` |
| 2 | Material identity or academic claim contradiction | `flag`, reason `EVIDENCE_MISMATCH` |
| 3 | Applicable rules sorted by priority and then UUID | First match determines action/channels |
| 4 | No rule matches | Use defaults, reason `DEFAULT_POLICY` |

Major, year, duration, and credential conditions match a **failed** requirement. Role and ban conditions match the stated fact. A null major or year fails its requirement. Non-active enrollment also fails major, year, and duration requirements. Use role scope to exempt staff or alumni where appropriate. A duration month is a completed calendar month at the pinned reference time. If an anniversary day does not exist in its month, clamp it to the last day of that month.

Server Rules returns all matching rule IDs in evaluation order. It includes failed requirements and active-ban conditions in `violated_rule_ids`. Positive role matches are not violations. Built-in outcomes have empty rule-ID arrays because Server Rules does not evaluate ordinary rules for those outcomes. Server Rules uses the [CPR reason codes](../../README.md#server-rules-service-endpoints), not scenario names. It deduplicates reasons in evaluation order.

Every non-accept result has no channels. If the subject is null, convert a rule or default `ban` to `reject` and append `SUBJECT_UNIDENTIFIED`. Moderation cannot persist a person ban without an identity. A forged document does not imply a ban under every possible ruleset. The baseline credential rule defines that behavior explicitly.

## Baseline fixture and example

When the rules database is empty, seed the [CPR baseline rules](../../README.md#baseline-rules-fixture) as one published version. Seed them only once. Startup must not overwrite admin edits or republish an old version. If no version is available, the current-version endpoint returns `409 NO_PUBLISHED_RULES`. Session then stays in the lobby.

| Complete evidence, no previous ban | Baseline result |
| --- | --- |
| Active FAF student, year 2, valid bundle | Accept: `general`, `dark-memes`, `groapa` |
| Active FAF student, year 1, valid bundle | Accept: `general` |
| Active IA student, valid bundle | Reject: major requirement |
| Truthful staff affiliation, valid bundle | Accept: `general`, `teachers` |
| Alumnus, valid graduation confirmation | Accept: `general`, `alumni` |
| Forged confirmation, otherwise coherent evidence | Ban: credential authenticity |
| Claims present `Larisa Vieru`, records and genuine documents retain `Eliza Caraman` | Flag: evidence mismatch |
| Truthful outsider, no documents/records | Reject: default policy |
| Any identified subject with existing ban | Ban: existing-ban override |

For the name-impersonation fixture, a complete evaluation returns:

```json
{
  "rule_version": "88888888-8888-4888-8888-888888888888",
  "expected_action": "flag",
  "allowed_channels": [],
  "matched_rule_ids": [],
  "violated_rule_ids": [],
  "reasons": ["EVIDENCE_MISMATCH"]
}
```

The request contains the normal claims, genuine documents and validations, and actual university records. It does not contain the string `impersonation`, a seed, or an expected decision. Moderation stores this result only after the player submits an action. No public evaluation preview exists.

## Errors and edge cases

| Status and code | Meaning |
| --- | --- |
| `400 MALFORMED_REQUEST` | Invalid JSON or UUID, or a missing key on a mutation |
| `401 UNAUTHENTICATED` / `403 FORBIDDEN` | Wrong identity or admin role, or a player attempting internal evaluation |
| `404 NOT_FOUND` | Unknown ruleset |
| `409 IDEMPOTENCY_CONFLICT` | Existing mutation key with a changed body |
| `409 RULE_VERSION_IMMUTABLE` | PUT or DELETE of a published version |
| `409 RULE_VERSION_ALREADY_PUBLISHED` | Attempt to publish an already published version with a new key |
| `409 NO_PUBLISHED_RULES` | No current version exists. A shift cannot start. |
| `409 SESSION_CONTEXT_CONFLICT` | The case, lifecycle, pinned time, or rule version does not match Session |
| `422 INVALID_RULESET` | Unsupported condition, invalid bounds, duplicate rule ID, or non-accept channels |
| `422 INVALID_POLICY_INPUT` | Incomplete or mismatched evidence, missing validations, or foreign-subject bans |
| `503 DEPENDENCY_UNAVAILABLE` | A required Session check or storage operation failed. This result is never a policy rejection. |

Errors use `{code, message, request_id, details: [{field, reason}]}`. Invalid input does not create a decision, a score, or an expected-action fallback.

## Required verification coverage

- Draft coverage includes full CRUD and publication. Published rulesets remain readable and reject edits and deletions.
- Version coverage publishes a second version during a shift. Existing shifts continue to use the first version.
- Baseline coverage checks every fixture row with full evidence and no scenario or seed in the policy input.
- Evidence coverage distinguishes a missing required document from a missing validation. It also includes separate first-name and last-name mismatches, null staff fields, inactive enrollment, and calendar-month boundaries.
- Precedence coverage includes ban-before-mismatch order, equal-priority UUID order, null-subject ban conversion, and empty channels for non-accept results.
- Determinism coverage retries evaluations after time passes. A Session outage produces an error, never a changed admission result.
