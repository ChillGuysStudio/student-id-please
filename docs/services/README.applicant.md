# Applicant Service integration contract

This document defines the planned contract for the Applicant Service. The planned service uses Java, Spring Boot, and MongoDB storage. This contract specifies required behavior. It does not describe a running deployment. The [CPR communication contract](../../README.md#communication-contract) is authoritative for shared types, authentication, transport, and generation rules.

## Responsibilities and resource lifecycles

| Resource | Owner's operations | Purpose |
| --- | --- | --- |
| Profile presets | A global admin can create, list, read, replace, and delete presets. | Reusable choices for new cases that Applicant initiates |
| Applicant cases | Initialize, read, and report readiness | Immutable presented claims for one application |
| Initialization metadata and inbox and outbox | Internal operations only | Retry-safe creation and event consumption |

The Applicant Service owns what the applicant **claims**. It does not own university truth, documents, validation results, or admission decisions. The service does not store a separate authoritative `actual` profile. It may retain a consumed event internally for deduplication. A retained event is not a player response.

## Dependencies

| Interaction | Purpose |
| --- | --- |
| Session calls Applicant | Initialize one case and poll its local readiness |
| Applicant calls Session | Verify the Moderator and shift context, pinned university snapshot, and reference time |
| Applicant reads the University snapshot | Get fixed programs, courses, dates, and any supplied reference subject |
| Applicant reserves or reads a University identity | Get one stable student ID and a name-derived mailbox when Applicant initializes a new affiliated subject. Read the identity when repairing incomplete source evidence. |
| Applicant publishes `CaseInitialized` | Publish the event only when Applicant is the initializer. |
| Applicant consumes `CaseInitialized` | Derive claims when Credential or University initialized the case. |
| Moderation reads Applicant | Get presented claims for policy evaluation. |

The [initialization contract](../../README.md#applicant-credential-and-university-record-initialization) defines the exact event union. The [identity tables](../../README.md#shared-simulation-catalog-and-identity-rules) define the shared conventions.

## Data contract

### Relevant shared enums

| Type | Values used by Applicant |
| --- | --- |
| `Scenario` | `eligible`, `forged`, `impersonation`, `outsider` |
| `ApplicantRole` | `student`, `teaching_assistant`, `staff`, `alumnus`, `outsider` |
| `UniversityStatus` | `active`, `inactive`, `graduated`, `none` |
| `LocalCaseState` | `pending`, `ready` |
| Case event producer | `applicant`, `credential`, `university_record` |

```text
ProfilePresetInput = {label: string, role: ApplicantRole,
                      university_status: "active" | "inactive" | "graduated" | "none",
                      major: string | null, year: Int | null, course_count: Int, enabled: Bool}
ProfilePreset = ProfilePresetInput & {preset_id: Id}
Claims = {first_name: string, last_name: string,
          student_id: string | null, major: string | null, year: Int | null,
          university_status: UniversityStatus,
          courses: string[], role: ApplicantRole, email: string}
Applicant = {case_id: Id, session_id: Id, claims: Claims}
```

`ApplicantRole` is `student`, `teaching_assistant`, `staff`, `alumnus`, or `outsider`. A preset label is 1 to 120 characters after trimming. `course_count` is 0 to 10. It must be 0 for inactive students, staff, alumni, and outsiders. Person-field combinations follow the CPR table. An active student's year is positive. During generation, Applicant checks the year against the pinned program length. Applicant assigns `preset_id`. A preset create body cannot supply it.

Presets contain generation choices. They do not contain claims about a specific existing person. A preset cannot set a case ID, expected action, or private subject identity. University can add program codes without changing the Applicant enum. Generation reports incompatible or missing programs. It does not silently switch a preset's major.

## HTTP API

All paths below belong to Applicant. The public admin paths require authenticated global admin access. Ordinary players never have these capabilities.

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/admin/applicant-presets` | Admin | `ProfilePresetInput` | `201 ProfilePreset` |
| `GET /api/v1/admin/applicant-presets` | Admin | `limit`, `cursor` | `200 Page<ProfilePreset>` |
| `GET /api/v1/admin/applicant-presets/{preset_id}` | Admin | None | `200 ProfilePreset` |
| `PUT /api/v1/admin/applicant-presets/{preset_id}` | Admin | Full `ProfilePresetInput` | `200 ProfilePreset` |
| `DELETE /api/v1/admin/applicant-presets/{preset_id}` | Admin | None | `204` |
| `POST /internal/v1/applicant/cases` | Session + verified Moderator context | `CaseStart` | `202 CaseAccepted` |
| `GET /internal/v1/applicant/cases/{case_id}/status` | Session | None | `200 LocalCaseState` |
| `GET /api/v1/sessions/{session_id}/applicants/{case_id}` | Assigned Moderator, active shift | None | `200 Applicant` |
| `GET /internal/v1/applicants/{case_id}` | Moderation | Required query: `session_id` | `200 Applicant` |

```text
CaseStart = {session_id: Id, scenario: "eligible" | "forged" | "impersonation" | "outsider" | "random",
             seed: string?, subject_id: Id?}
CaseAccepted = {case_id: Id, session_id: Id, state: "pending"}
LocalCaseState = {case_id: Id, session_id: Id, state: "pending" | "ready"}
```

Applicant cases do not support `PUT`, `PATCH`, or `DELETE`. A preset replacement replaces the complete preset. Nullable fields must be present as null when they do not apply. Deleting a preset does not delete applicants or pending cases that already captured the preset. Deleting an unknown preset returns `404`. Replaying a successful delete with its original idempotency key returns the original `204`.

`Page<T> = {items: T[], next_cursor: string | null}`. The default `limit` is 50. The allowed range is 1 to 100. Every mutation requires `Idempotency-Key: <UUID>`. The same caller, key, path, and body return the original result. A changed body returns `409`. A case retry must use the same initializer.

## Generation behavior

### Applicant initiates

1. Validate the active shift and caller. Get the pinned reference snapshot and time.
2. Resolve the scenario, seed, case ID, and subject once. An explicit returning subject must exist in the snapshot. An outsider has a null subject.
3. For a new non-outsider subject, select an enabled and compatible non-outsider preset. Use preset-ID order and the CPR deterministic choice. Capture the preset's complete value locally before generation. For an existing subject, use reference facts instead of overwriting them with a preset.
4. Generate `first_name` and `last_name`. Then call `POST /internal/v1/university-identities/reservations` for a new affiliated subject. The returned `FAF-25-1`-style ID and name-derived UTM mailbox are authoritative. Outsiders do not call the reservation endpoint.
5. Generate only claims. For `impersonation`, replace only the first and last names with the deterministic different presented pair. The other initial scenarios have truthful claims.
6. Commit the claims and the original outbox event. A `202` response does not promise that the other two services are ready.

### Applicant subscribes

| Producer | How claims are derived |
| --- | --- |
| Credential | Read the holder's first name, last name, ID, and affiliation from `enrollment_confirmation`. Read the email from the mailbox and the courses from the ELSE registration. A damaged mailbox uses the subject's reserved email. Do not use a local profile preset to replace source values. |
| University Record | Read the actual subject's enrollment or affiliation, email, and enrolled course rows. Use empty courses when there are no registrations. Academic-year or course-catalog existence does not establish a person's enrollment. |
| Either, `impersonation` | Source documents and records retain the actual first and last names. Derive both different presented fields from the case ID once. Do not change the email, student ID, major, year, role, or courses. |
| Either, `outsider` | An empty source bundle is complete evidence of no university affiliation. Generate deterministic first and last names and a personal example-domain email. Use null student fields. |

An authentic document does not prove that the person meets the access rules. A forged document in the initial `forged` scenario still prints the correct affiliation. Applicant does not create a different person because the document's authenticity flag is false.

## Event example

The following example is one complete Applicant-produced event. It does not include credentials or university records.

```json
{
  "event_id": "55555555-5555-4555-8555-555555555555",
  "event_type": "CaseInitialized",
  "schema_version": 1,
  "occurred_at": "2026-09-10T10:00:00Z",
  "producer": "applicant",
  "correlation_id": "11111111-1111-4111-8111-111111111111",
  "payload": {
    "case_id": "11111111-1111-4111-8111-111111111111",
    "session_id": "33333333-3333-4333-8333-333333333333",
    "university_snapshot_id": "44444444-4444-4444-8444-444444444444",
    "reference_at": "2026-09-10T10:00:00Z",
    "scenario": "eligible",
    "seed": "demo-faf-year-2",
    "subject_id": "22222222-2222-4222-8222-222222222222",
    "claims": {
      "first_name": "Eliza",
      "last_name": "Caraman",
      "student_id": "FAF-25-1",
      "major": "FAF",
      "year": 2,
      "university_status": "active",
      "courses": ["FAF-OOP"],
      "role": "student",
      "email": "eliza.caraman@isa.utm.md"
    }
  }
}
```

This example assumes that University reference data contained the subject and registration before the snapshot. It also assumes the first reserved FAF 2025 sequence and mailbox base. The seed does not independently guarantee an arbitrary preset combination. For this case ID's impersonation fixture, Applicant presents `Larisa Vieru`. Credential and University retain `Eliza Caraman`. The mailbox remains `eliza.caraman@isa.utm.md`.

## Delivery, errors, and edge cases

The exchange is `student-id.events.v1`. The routing key is `case.initialized`. The durable queue is `applicant.case-initialized.v1`. Delivery uses persistent messages, an outbox, publisher confirms, and a transactional inbox. Applicant checks its own event against the stored initialization and acknowledges it as a no-op. Applicant never republishes its own event. For business-ID duplicates, compare the producer and normalized source payload, not only `event_id`.

| Status and code | Meaning and behavior |
| --- | --- |
| `400 MALFORMED_REQUEST` | Invalid JSON, invalid UUID syntax, or a missing idempotency header |
| `401 UNAUTHENTICATED` / `403 FORBIDDEN` | Invalid identity or the wrong admin or shift role |
| `404 NOT_FOUND` | Unknown preset or local case. During propagation, only Session interprets a missing subscriber for a known case as pending. |
| `409 IDEMPOTENCY_CONFLICT` | Same key with different body |
| `409 CASE_NOT_READY` | The local case exists, but generation is unfinished. The response includes `Retry-After: 1`. |
| `409 GENERATION_DATA_UNAVAILABLE` | No compatible enabled preset or program, or required snapshot data is incomplete |
| `409 IDENTITY_CONFLICT` | University already reserved the subject with different identity fields |
| `422 INVALID_FIELDS` | Impossible role, status, and nullability combination, or an invalid count |
| `422 UNKNOWN_SUBJECT` / `422 INVALID_SCENARIO` | Requested returning subject is absent, or an outsider request supplies a subject |
| `503 DEPENDENCY_UNAVAILABLE` | Session or the reference snapshot is unavailable. Applicant does not generate a replacement person. |

The error body is `{code, message, request_id, details: [{field, reason}]}`. Applicant rejects wrong-session resource requests before it exposes claims. No response includes the seed, scenario, source events, or another player's restricted facts.

Transient consumer failures retry after 1, 5, and 30 seconds. After those retries, the message moves to `applicant.case-initialized.v1.dlq`. An invalid schema, wrong producer or variant, or conflicting initialization goes directly to the DLQ. The consumer resumes a pending inbox reservation instead of treating it as completed. Replays retain the original IDs and selected local data.

## Required verification coverage

- Preset coverage includes create, read, update, and delete operations, invalid combinations, and same-key retries.
- Initialization coverage includes every initializer and all four scenarios. Source fields determine Applicant's output.
- Idempotency coverage compares the complete Applicant output before and after duplicate delivery and after a preset edit.
- Identity coverage includes staff and alumni nullability, unpadded student sequences, email suffix collisions, and a newly added university program or course.
- Outsider coverage includes a Credential-first case that still creates a ready Applicant profile.
- Dependency coverage delays University snapshot access. Applicant creates no fallback, reports no premature readiness, and exposes no hidden data in errors.
