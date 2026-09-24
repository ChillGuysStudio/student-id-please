# University Record Service integration contract

The University Record Service is a planned Java and Spring Boot service with MongoDB storage. It owns university reference data, authoritative case records, and Junior Moderator record permissions. The [CPR contract](../../README.md#communication-contract) defines the shared types and communication conventions.

## Two data lifecycles

| Resource | Operations | Effect of changes |
| --- | --- | --- |
| University reference data | Admins create, list, read, replace, and delete it. | Changes affect the available data for future shifts. |
| University snapshots | Session creates them. Internal consumers read them. | Reference data stays fixed for the entire shift. |
| University identity reservations | The selected initializer creates them with one idempotent command. Subscribers can read them. | Student IDs and university mailboxes remain stable. The service never deletes or reuses them. |
| University case records | Initialize and read. | Evidence stays fixed for one applicant. No update or delete API exists. |
| Record permissions | Replace them while the lobby is open. Read them. | Controls which record kinds each Junior Moderator can inspect. |

Reference CRUD supports new courses, programs, affiliations, registrations, Outlook memberships, academic periods, schedules, and FCIM messages. Admins extend existing kinds by adding rows. New kinds and required fields need coordinated schema changes because generators and clients must understand them.

The service does not own presented claims, credentials, authenticity results, or decisions. When another service initializes a case, University Record derives its facts from that service's event. This derivation does not give the source service write access to the university database.

## Reference data shapes

### Relevant shared enums

| Type | Values used by University Record |
| --- | --- |
| `UniversityDataKind` | `program`, `registration`, `enrollment`, `outlook_group`, `course`, `academic_year`, `schedule`, `fcim_message` |
| `RecordKind` | `enrollment`, `outlook_group`, `course`, `academic_year`, `schedule`, `fcim_message` |
| `ApplicantRole` | `student`, `teaching_assistant`, `staff`, `alumnus`, `outsider` |
| `UniversityStatus` | `active`, `inactive`, `graduated`, `none` |
| `LocalCaseState` | `pending`, `ready` |

```text
UniversityDataKind = "program" | "registration" | "enrollment" | "outlook_group" |
                     "course" | "academic_year" | "schedule" | "fcim_message"
UniversityDataInput = {kind: UniversityDataKind, subject_id: Id | null,
                       data: ProgramDefinition | UniversityRegistration | Enrollment |
                             OutlookGroup | CourseDefinition | AcademicYear | Schedule | FcimMessage}
UniversityData = UniversityDataInput & {reference_id: Id}
ProgramDefinition = {code: string, name: string, study_years: Int}
CourseDefinition = {course_id: string, title: string, major: string, year: Int,
                    semester: "autumn" | "spring"}
UniversityRegistration = {course_id: string}
UniversitySnapshot = {snapshot_id: Id, session_id: Id, reference_at: Time,
                       entries: UniversityData[]}
IdentityReservationInput = {case_id: Id, subject_id: Id, first_name: string, last_name: string,
                            role: ApplicantRole, university_status: UniversityStatus,
                            major: string | null, admission_year: Int | null}
UniversityIdentity = {subject_id: Id, first_name: string, last_name: string,
                      student_id: string | null, email: string}
```

The [shared domain types](../../README.md#shared-domain-types) define the other record types. A reference entry has no `case_id`. Its `reference_id` identifies an editable resource. A per-case record has `record_id`, `case_id`, `kind`, `subject_id`, and typed `data`.

| Reference kind | Subject | Constraints and case interpretation |
| --- | --- | --- |
| `program` | Null | The code is unique. Study years range from 1 through 8. The service copies the entry into the shift's reference snapshot. It does not create a new player record kind. |
| `course` | Null | The course code is unique. The program must exist. The year must be in the program's range. The semester is autumn or spring. |
| `academic_year` | Null | The label uses `YYYY-YYYY` with consecutive years. Periods cannot overlap. The initial fixture runs from September 1 to the next September 1. |
| `schedule` | Null | The course must exist. The semester must match the course definition. The interval must be inside one academic year. |
| `enrollment` | Required | Each subject has one affiliation. Nullable student fields support staff. The person-field table applies. |
| `registration` | Required | The subject affiliation and the course must exist. Each `(subject_id, course_id)` pair is unique. The entry becomes a per-case `Course.enrolled` fact. |
| `outlook_group` | Required | The affiliation must exist. The email must be canonical. Each `(subject_id, group_name)` entry is unique. One person's email can belong to several groups. |
| `fcim_message` | Required | The affiliation must exist. The author, channel, and text must be non-empty. The timestamp must be valid. Supporting evidence is optional. |

`UniversityRecord.kind` remains limited to the six player-facing categories: `enrollment`, `outlook_group`, `course`, `academic_year`, `schedule`, and `fcim_message`. The `program` and `registration` reference entries support generation. They do not add player permissions.

Reference student IDs are unique among subjects. Each ID must match `{MAJOR}-{YY}-{SEQUENCE}`, the enrollment program, and the full admission year. The sequence is positive and unpadded. It does not encode a subject UUID or group. An email can occur in multiple groups for one subject, but it cannot belong to two subjects. Null staff IDs do not create uniqueness conflicts. A registration requires an active student or teaching assistant. The course must match that person's program and year. Delete and update constraints protect live references. Snapshots contain copied values, so they do not block deletion of live data.

Enrollment and Outlook reference writes claim the student ID or mailbox in the permanent identity registry that generated reservations use. An accepted supplied student ID advances the high-water mark for its cohort. An accepted supplied mailbox reserves its exact suffix. Deleting reference data never frees either value. An admin replacement of a legal name updates the first and last names in the registry. The replacement retains the student's ID and mailbox. These rules prevent generated identities from colliding with admin-managed subjects.

## Reference CRUD endpoints

All admin routes require authenticated global admin access. This rule includes the list and read routes. Admin routes do not bypass player permission checks on case endpoints.

| Method and path | Request | Success |
| --- | --- | --- |
| `POST /api/v1/admin/university-data` | `UniversityDataInput` | `201 UniversityData` |
| `GET /api/v1/admin/university-data` | `limit`, `cursor`. Optional: `kind`, `subject_id`. | `200 Page<UniversityData>` |
| `GET /api/v1/admin/university-data/{reference_id}` | None | `200 UniversityData` |
| `PUT /api/v1/admin/university-data/{reference_id}` | Complete `UniversityDataInput` | `200 UniversityData` |
| `DELETE /api/v1/admin/university-data/{reference_id}` | None | `204` |

PUT preserves the resource identity. The `kind`, `subject_id`, and natural program or course codes cannot change. To reassign a registration, delete it and create another registration. Updates also validate the resulting dependent data. Reducing a program below an existing course's year returns `409 REFERENCE_IN_USE`. Changing an affiliation so that it no longer matches its registered courses also returns `409 REFERENCE_IN_USE`. Delete dependents first when necessary. The service does not cascade case deletions.

This example adds an autumn course for FAF year 2:

```json
{
  "kind": "course",
  "subject_id": null,
  "data": {
    "course_id": "FAF-API",
    "title": "API Design",
    "major": "FAF",
    "year": 2,
    "semester": "autumn"
  }
}
```

POST returns the submitted data with a server-generated `reference_id`. Before starting a shift that might use this course, add a matching schedule entry:

```json
{
  "kind": "schedule",
  "subject_id": null,
  "data": {
    "semester": "autumn",
    "course_id": "FAF-API",
    "starts_at": "2026-09-01T00:00:00Z",
    "ends_at": "2027-02-01T00:00:00Z"
  }
}
```

To register an existing person, create `{kind: "registration", subject_id: <person UUID>, data: {course_id: "FAF-API"}}`. Adding only the course or schedule does not enroll that person.

## Identity reservations

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /internal/v1/university-identities/reservations` | Selected Applicant, Credential, or University Record initializer | `IdentityReservationInput` | `200 UniversityIdentity` |
| `GET /internal/v1/university-identities/{subject_id}` | Applicant, Credential, or University Record subscriber | Required query: `case_id` | `200 UniversityIdentity` |

For POST, the caller forwards the signed Session context from `CaseStart`. University verifies the session and confirms that the caller is the selected initializer. University then binds the authenticated service's proposed case ID and subject to the reservation. Session does not need to have received `CaseAccepted` first. Outsiders must not call this endpoint. Requests for students, teaching assistants, and alumni require a known major and admission year. Staff requests require both fields to be null. University enforces the role, status, and nullability table before allocation.

For a student, teaching assistant, or alumnus, University allocates the next positive sequence within `(major, admission_year)`. It formats the ID as `MAJOR-YY-SEQUENCE`, for example `FAF-25-1`, then `FAF-25-2`. For the mailbox, University applies the shared Romanian-name transliteration and selects the domain for the role. Students, teaching assistants, and alumni use `isa.utm.md`. Staff use `utm.md`. University tries `first.last`, then `first.last1`, `first.last2`, and later numeric suffixes. It never reuses suffixes or sequences.

The subject reservation, cohort sequence, and mailbox suffix commit in one MongoDB transaction. Unique indexes cover the subject ID, student ID, and canonical email. The command is idempotent by `(case_id, Idempotency-Key)`. An identical retry returns the original reservation. If the names, role, major, or admission year differ for the same subject or key, University returns `409 IDENTITY_CONFLICT`. It never allocates a second identity. A reservation remains consumed if later event publication or case derivation fails.

The GET route never creates data. University verifies that the requesting service is deriving the named case. It also verifies that the source event has the same subject ID. Services read existing reference subjects from the pinned snapshot instead. A missing reservation for a newly generated affiliated subject is a propagation conflict. The missing reservation does not permit generation of a replacement email.

## Shift snapshots

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /internal/v1/university-snapshots` | Session | `{session_id: Id, reference_at: Time}` | `201 {snapshot_id: Id, session_id: Id, reference_at: Time}` |
| `GET /internal/v1/university-snapshots/{snapshot_id}` | Applicant, Credential, University Record, Session | None | `200 UniversitySnapshot` |

Snapshot creation copies reference data atomically. A concurrent CRUD operation occurs entirely before or after the snapshot. The snapshot must contain exactly one academic year at the reference time, coherent subject fields, and unambiguous schedules for the courses used during generation. A schedule interval must agree with its semester and containing academic year. Each session can have exactly one snapshot. A duplicate request with the same session and reference time returns the existing snapshot. A request with a different time returns `409 SNAPSHOT_CONFLICT`. Session stores the returned ID before the session becomes active.

Reference CRUD can take several steps. For example, an admin can create a course before its schedule. These intermediate live states are permitted. Snapshot creation returns `409 GENERATION_DATA_UNAVAILABLE` until the data is complete. Admins do not need a distributed or bulk editing workflow to add a course.

The service never replaces a missing pinned snapshot with current reference data. It retains snapshots while their shifts or cases exist. Only services can fetch a snapshot because it can contain reference people and hidden evidence. Knowledge of a snapshot UUID does not grant access.

## Case and permission endpoints

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /internal/v1/university-record/cases` | Session + verified Moderator context | Shared `CaseStart` | `202 CaseAccepted` |
| `GET /internal/v1/university-record/cases/{case_id}/status` | Session | None | `200 LocalCaseState` |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/university-records` | Junior Moderator, active shift | Required: `kind: RecordKind`. Pagination: `limit`, `cursor`. | `200 Page<UniversityRecord>` |
| `GET /internal/v1/cases/{case_id}/university-records` | Moderation | Required query: `session_id` | `200 {case_id: Id, subject_id: Id \| null, records: UniversityRecord[]}` |
| `PUT /api/v1/sessions/{session_id}/record-permissions` | Session owner, open lobby | `{permissions: Permission[]}` | `200 {permissions: Permission[]}` |
| `GET /api/v1/sessions/{session_id}/record-permissions/me` | Participant | None | `200 Permission` |
| `GET /internal/v1/sessions/{session_id}/record-permissions/{player_id}` | DMs or Session | None | `200 Permission` |

`Permission = {session_id: Id, player_id: Id, record_kinds: RecordKind[]}`. University checks membership and role through Session. The Moderator receives an empty permission list and has no direct access to university case records. At least one Junior Moderator must receive each kind. No single Junior Moderator can receive all kinds. Permission replacement supplies the complete list for all Junior Moderators. Permissions freeze when the shift starts.

No PUT, PATCH, or DELETE endpoints exist for case records or snapshots. Pagination has a default of 50 and a range of 1 through 100. It uses an opaque cursor. Every command uses `Idempotency-Key`. An existing unfinished case returns `409 CASE_NOT_READY`. It does not return a misleading empty record set.

## Case generation

### Initiator behavior

As an initiator, the service creates a case. It generates only university records from the supplied reference subject or the shared active-student defaults. For a new affiliated subject, the service invokes its local identity-reservation operation before it creates records. It does not bypass the operation's counters or indexes. The initial outsider has a null subject and an empty record set. The service publishes `CaseSeed & {university_records: UniversityRecord[]}` with the envelope value `producer = university_record`. This source contains ground truth. Applicant introduces its own name divergence. Credential introduces its own authenticity divergence.

### Subscriber behavior

| Source | Required derivation |
| --- | --- |
| Applicant | Derive the affiliation from claims. Resolve titles, program length, dates, and schedules through the pinned snapshot. For `impersonation`, restore only the actual first and last name pair. |
| Credential | The confirmation anchors the holder's first and last names and affiliation. ELSE anchors the requested registrations. Use the subject's reserved email if the mailbox data is damaged. Forgery metadata does not prove a different enrollment. |
| Existing subject, either source | Preserve the actual affiliation, memberships, and registrations from the snapshot. A conflict outside the named divergence rule makes initialization invalid. |
| New subject, either source | Create university case facts that match the source fields and catalog constraints. Do not add invented programs or courses to live reference data. |

The service constructs a case enrollment or affiliation, the Outlook memberships, course lookup results, the current academic year, and the relevant schedules. It copies applicable reference FCIM messages when they exist. It must not create a message that proves a lie solely from the scenario label. Person records use the actual subject UUID. Academic-year and schedule records use null subjects.

For existing subjects, explicit reference registration entries for the current semester supply the registrations. For new subjects, known course selections from the source become registrations when they meet the program, year, and semester constraints. Include known registered courses and all source-requested course lookups. Deduplicate them by code. An unknown lookup uses `{course_id, title: null, exists: false, enrolled: false}`. The lookup does not create a course definition. If an initial honest source selects a known but incompatible course, the service reports a contract conflict. It does not change the university catalog.

Generated case facts remain case facts. They do not create live reference rows. To reuse a simulated person in later shifts, create the person's reference affiliation, memberships, and registrations through admin CRUD. Then use that subject in a future snapshot. A returning subject keeps its UUID and therefore keeps its ban history.

## Example case evidence

The internal case response for the shared Eliza Caraman example contains this enrollment record:

```json
{
  "record_id": "faa470bb-8205-5713-80f7-94d07355ea7a",
  "case_id": "11111111-1111-4111-8111-111111111111",
  "kind": "enrollment",
  "subject_id": "22222222-2222-4222-8222-222222222222",
  "data": {
    "student_id": "FAF-25-1",
    "first_name": "Eliza",
    "last_name": "Caraman",
    "major": "FAF",
    "year": 2,
    "status": "active",
    "enrolled_since": "2025-09-01T00:00:00Z",
    "role": "student"
  }
}
```

The record ID is UUIDv5. Its namespace is the case ID, and its name is `record:enrollment`. Other rows contain `eliza.caraman@isa.utm.md` and its groups, the `FAF-OOP` enrollment result, and the current academic year and schedule. Under name impersonation, the enrollment remains `Eliza Caraman`. Applicant presents `Larisa Vieru` for this case ID. The top-level `subject_id` in the internal response remains the actual applicant. Moderation must use that ID when it reads or creates bans.

## Events, errors, and edge cases

The service uses exchange `student-id.events.v1`, routing key `case.initialized`, and queue `university-record.case-initialized.v1`. It persists domain records and inbox completion together. It publishes through an outbox only on the initializer path. For duplicate messages, the consumer compares the producer and payload data. It acknowledges identical completed cases, resumes identical pending cases, and quarantines conflicts. A source event never causes the service to publish a second initialization.

| Status / code | Meaning |
| --- | --- |
| `400 MALFORMED_REQUEST` | The JSON or UUID is invalid, or the idempotency header is missing. |
| `401 UNAUTHENTICATED` / `403 FORBIDDEN` | The admin identity, shift participant, role, or requested record permission is wrong. |
| `404 NOT_FOUND` | The reference, case, or snapshot is unknown. The service does not create one. |
| `409 IDEMPOTENCY_CONFLICT` | The same key has a changed body. |
| `409 REFERENCE_CONFLICT` | A natural key or person identifier is duplicated, or academic years overlap. |
| `409 REFERENCE_IN_USE` | A deletion or edit would invalidate live dependents. |
| `409 SNAPSHOT_CONFLICT` | The session already has a snapshot with a different reference time. |
| `409 IDENTITY_CONFLICT` | The reservation key or subject changed, or a supplied reference identifier belongs to another subject. |
| `409 GENERATION_DATA_UNAVAILABLE` | The snapshot lacks a coherent academic period, schedule, or required reference data. |
| `409 CASE_NOT_READY` | The case is pending. The response includes `Retry-After: 1`. |
| `409 PERMISSIONS_FROZEN` | A request attempts to replace permissions after the lobby phase. |
| `422 INVALID_FIELDS` | The kind, data, nullability, date, or code combination is invalid, or the request changes immutable reference identity. |
| `422 UNKNOWN_SUBJECT` / `422 INVALID_SCENARIO` | The returning subject is absent or inconsistent with the scenario. |
| `503 DEPENDENCY_UNAVAILABLE` | Session or a required dependency is unavailable. Authorization checks still apply. |

Errors use the shared `{code, message, request_id, details}` shape. A request for a record kind without permission returns `403` before the service serializes restricted data. Admin CRUD does not let the Moderator bypass player-facing case routes.

Transient consumer failures retry after 1, 5, and 30 seconds. The consumer then sends them to `university-record.case-initialized.v1.dlq`. Schema and conflict failures go there immediately. A ready outsider returns `records: []` and a null subject. A case that has not arrived returns `404`. Session treats that response as pending only when Session already knows the case.

## Required verification coverage

- Reference coverage includes CRUD for each kind, a new course, a schedule, a registration, and dependent deletion failures.
- Snapshot immutability coverage pins a snapshot before live-data edits or deletions. Existing case responses remain byte-for-byte stable.
- Snapshot update coverage confirms that a later snapshot contains the reference changes.
- Generation coverage includes all three owners and all four scenarios. No cross-service writes or whole-applicant payloads occur.
- Person-record coverage includes staff nullability, alumni evidence, registration versus course existence, and duplicate subject identifiers.
- Concurrency coverage reserves the same cohort and name at the same time. IDs remain unpadded and increasing. Emails use no suffix, then `1`, then `2`. No value is reused after deletion or failure.
- Authorization and delivery coverage includes every record-kind permission, wrong-session requests, pending cases, duplicate events, and conflict quarantine.
