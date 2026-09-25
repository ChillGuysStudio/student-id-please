# Credential service integration contract

Credential is a planned Java and Spring Boot service that uses MongoDB storage. The [CPR communication contract](../../README.md#communication-contract) defines the shared wire types and transport. This document defines Credential's behavior and integration edge cases.

## Responsibilities and resource lifecycles

| Resource | Operations | Purpose |
| --- | --- | --- |
| Document templates | Admin creates, lists, reads, replaces, and deletes | Issuer and validity defaults for future documents |
| Case document bundles | Initialize, read, and report readiness | Immutable documents presented for a case |
| Validation results | Compute once or reuse, then read | Evidence of structural validity, authenticity, and expiry |

Credential determines whether a document is sound. Server Rules decides access. Moderation records the player's decision. A valid document can belong to someone who is not entitled to access. A dishonest claim does not automatically make every document forged.

## Dependencies

- Session calls the initializer and the readiness endpoint. Credential checks the Session context for authorization and pinned reference data.
- Credential reads University's immutable snapshot for program, course, and date information and supplied reference subjects.
- Credential reserves one University identity when it initializes a new affiliated subject. Credential may read that reservation when it derives incomplete source evidence. Credential never invents a student sequence or mailbox suffix locally.
- Applicant or University initializes Credential through `CaseInitialized`. Credential publishes this event only when Session selects Credential as the initializer.
- The assigned Moderator reads documents and can request validation. Moderation reads the complete validation results even if the player never validated a document.

## Data types and templates

### Relevant shared enums

| Type | Values used by Credential |
| --- | --- |
| `Scenario` | `eligible`, `forged`, `impersonation`, `outsider` |
| `CredentialKind` | `student_id`, `university_email`, `enrollment_confirmation`, `else_registration` |
| `ApplicantRole` | `student`, `teaching_assistant`, `staff`, `alumnus`, `outsider` |
| `UniversityStatus` | `active`, `inactive`, `graduated`, `none` |
| `LocalCaseState` | `pending`, `ready` |

```text
CredentialTemplateInput = {kind: CredentialKind, issuer: string,
                           validity_days: Int | null, enabled: Bool}
CredentialTemplate = CredentialTemplateInput & {template_id: Id}
Credential = {credential_id: Id, case_id: Id, kind: CredentialKind,
              holder_first_name: string, holder_last_name: string,
              student_id: string | null, issuer: string,
              issued_at: Time, expires_at: Time | null,
              data: StudentCard | UniversityEmail | EnrollmentProof | ElseRegistration}
Validation = {credential_id: Id, structurally_valid: Bool, authentic: Bool,
              expired: Bool, issues: string[], checked_at: Time}
```

The [CPR domain types](../../README.md#shared-domain-types) define each `data` shape. The [credential bundle and defect table](../../README.md#credential-bundles-and-defects) defines when Credential generates each kind.

| Kind | Required printed data | Typical bundle membership |
| --- | --- | --- |
| `student_id` | Holder first and last names, student ID, major, issuer, and issue and expiry dates | Student, TA, alumni |
| `university_email` | Holder first and last names, email, groups, role, issuer, and issue and expiry dates | Every university-affiliated role |
| `enrollment_confirmation` | Holder first and last names and nullable student ID. Major, year, status, role, enrollment date, academic year, and confirmation number. | Every university-affiliated role, including staff with null student fields |
| `else_registration` | Holder first and last names and ID. Academic year, semester, and course IDs. | Current students and TAs with courses |

Every schema field is present. Legitimate nulls follow the person-field table. Outsiders have no documents. Confirmation numbers use `CONF-<case_id>`. `StudentCard.major` must agree with the major encoded in the printed `MAJOR-YY-SEQUENCE` ID. The confirmation's enrollment date must agree with the admission year encoded in that same ID. Enrollment dates and status are separate from the proof's issue date.

A template issuer is a non-empty string with at most 120 characters. `validity_days` is either null or a positive integer. Null sets expiry to the end of the academic year. Otherwise, expiry is the issue time plus the specified number of 24-hour days. Credential seeds the four default issuers from the CPR with one enabled template for each kind. A second enabled template of the same kind returns `409 TEMPLATE_ALREADY_ENABLED`. Template replacement cannot change the template kind. A different kind requires a new template.

## HTTP API

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/admin/credential-templates` | Admin | `CredentialTemplateInput` | `201 CredentialTemplate` |
| `GET /api/v1/admin/credential-templates` | Admin | `limit`, `cursor` | `200 Page<CredentialTemplate>` |
| `GET /api/v1/admin/credential-templates/{template_id}` | Admin | None | `200 CredentialTemplate` |
| `PUT /api/v1/admin/credential-templates/{template_id}` | Admin | Full `CredentialTemplateInput` | `200 CredentialTemplate` |
| `DELETE /api/v1/admin/credential-templates/{template_id}` | Admin | None | `204` |
| `POST /internal/v1/credential/cases` | Session + verified Moderator context | `CaseStart` | `202 CaseAccepted` |
| `GET /internal/v1/credential/cases/{case_id}/status` | Session | None | `200 LocalCaseState` |
| `GET /api/v1/sessions/{session_id}/cases/{case_id}/credentials` | Assigned Moderator, active shift | `limit`, `cursor` | `200 Page<Credential>` |
| `POST /api/v1/sessions/{session_id}/credentials/{credential_id}/validation` | Assigned Moderator, active shift, current case | `{}` | `200 Validation` |
| `GET /internal/v1/cases/{case_id}/credential-results` | Moderation | Required query: `session_id` | `200 {case_id: Id, credentials: Credential[], validations: Validation[]}` |

`CaseStart`, `CaseAccepted`, and `LocalCaseState` are the [shared initialization types](../../README.md#applicant-credential-and-university-record-initialization). Player endpoints never accept the optional internal seed or returning-subject fields. The API has no case or document PUT, PATCH, or DELETE endpoint. Deleting a template does not affect stored documents or templates already selected for pending cases.

Mutations use `Idempotency-Key`. A retry returns the original result. Reusing a key with a changed body returns `409`. Pagination uses `Page<T> = {items: T[], next_cursor: string | null}`. The default limit is 50, and the allowed range is 1 to 100. The internal result endpoint returns the complete result without pagination. It has exactly one validation for each credential and no orphan or duplicate validation IDs.

## Generation and event handling

### Initiator behavior

Credential generates a local document bundle from the supplied reference subject. For a new subject, Credential uses the shared deterministic active-student defaults. For a new affiliated subject, Credential chooses the first and last names before it calls University's identity-reservation endpoint. Credential calls that endpoint before printing any document. It uses the returned unpadded ID and UTM mailbox without changes. Credential generates an empty bundle for outsiders and does not reserve an identity. Credential captures the enabled templates locally when it reserves the pending aggregate. It then generates the bundle with the pinned university snapshot and reference time. Credential must generate only documents and their private authenticity metadata. It must not construct an event that contains Applicant claims or University case records.

Credential commits the bundle and the outbox event together. The event is `CaseSeed & {credentials: GeneratedCredential[]}` with the envelope value `producer = credential`. The first acceptance fixes its IDs, seed, resolved scenario, university snapshot, and reference time.

### Subscriber behavior

| Source | Derivation |
| --- | --- |
| Applicant claims | Use the received first and last names, reserved identity, affiliation, and courses for the applicable printed fields. Derive the enrollment date from reference facts or the synthetic admission-year convention. |
| University records | Use the enrollment, affiliation, and email facts. Generate ELSE proof only for enrolled courses. Course existence alone is insufficient. |
| `impersonation` from Applicant | Restore only the actual holder's first and last name pair from the reference subject or existing identity reservation. Do not print the deterministic presented pair on genuine documents. |
| `impersonation` from University | The records already contain the actual first and last name pair. Retain that pair. Applicant independently adds the alternate pair to its claims. |
| `forged` from either | Generate the normal bundle, then mark only the confirmation's private authenticity false. |
| `outsider` from either | Commit an empty bundle and become locally ready. |

The exchange is `student-id.events.v1`. The routing key is `case.initialized`, and the queue is `credential.case-initialized.v1`. The source's case data supplies the derivation input. Local templates supply only the issue defaults. Subscribers never republish. After completion, the subscriber treats its own events and repeated source payloads as no-ops. Conflicting source data for a case goes directly to the DLQ.

## Validation rules

| Check | Result |
| --- | --- |
| Required printed content is empty, such as mailbox email `""` | `structurally_valid = false`, `INCOMPLETE` |
| Printed format constraints, date constraints, or cross-document fields disagree | `structurally_valid = false`, `INCONSISTENT` |
| Course does not exist or belongs to a different program, year, or semester in the pinned snapshot | `structurally_valid = false`, `INCONSISTENT` |
| Private authenticity says false | `authentic = false`, `FORGED`. Do not change other documents. |
| Non-null expiry is at or before shift reference time | `expired = true`, `EXPIRED` |
| No failure | Structure and authenticity true, expired false, issues empty |

Credential must not call Server Rules during validation. Credential must not compare a lie in Applicant with university records and relabel every document as forged. All documents in the initial impersonation fixture are genuine. The claimed first and last name pair is the lie.

Credential stores the first validation result and reuses it. `checked_at` records the time of that first check. Expiry always uses the shift reference time. A template edit must not reissue a document or change its authenticity or expiry. Credential returns all applicable issue codes in lexical order.

Expiry and structure fixtures can exercise defects through internal unit and integration test inputs to the generator and validator. These fixtures do not add public case mutation APIs. For an expired fixture, also backdate the issue time. The relation `issued_at <= expires_at <= reference_at` then represents expiry without an unrelated chronology defect. When a fixture is an initialization source, keep the confirmation's identity fields intact. Fixture defects must affect non-anchor data such as the mailbox or card major.

## Example document and validation

The following document belongs to the year-2 FAF bundle from the Applicant reference example. It is not the complete bundle.

```json
{
  "credential_id": "7f5d3457-2e10-5456-8a10-9dbfb79fde87",
  "case_id": "11111111-1111-4111-8111-111111111111",
  "kind": "enrollment_confirmation",
  "holder_first_name": "Eliza",
  "holder_last_name": "Caraman",
  "student_id": "FAF-25-1",
  "issuer": "SIM-REGISTRY",
  "issued_at": "2026-09-10T10:00:00Z",
  "expires_at": "2027-09-01T00:00:00Z",
  "data": {
    "major": "FAF",
    "year": 2,
    "status": "active",
    "role": "student",
    "enrolled_since": "2025-09-01T00:00:00Z",
    "academic_year": "2026-2027",
    "confirmation_number": "CONF-11111111-1111-4111-8111-111111111111"
  }
}
```

For the `forged` fixture, the same printed fields can produce this validation:

```json
{
  "credential_id": "7f5d3457-2e10-5456-8a10-9dbfb79fde87",
  "structurally_valid": true,
  "authentic": false,
  "expired": false,
  "issues": ["FORGED"],
  "checked_at": "2026-09-10T10:01:00Z"
}
```

The credential ID is UUIDv5. Its namespace equals the case ID, and its name is `credential:enrollment_confirmation`. `Credential` never includes raw generation metadata. Only the explicit validation response exposes the validation verdict to an authorized Moderator.

## Errors and edge cases

| Status and code | Meaning |
| --- | --- |
| `400 MALFORMED_REQUEST` | Invalid JSON or UUID, or missing idempotency header |
| `401 UNAUTHENTICATED` or `403 FORBIDDEN` | Wrong identity, role, session, or requested credential outside current case |
| `404 NOT_FOUND` | Unknown template, case, or credential |
| `409 IDEMPOTENCY_CONFLICT` | Changed request using an existing key |
| `409 TEMPLATE_ALREADY_ENABLED` | Another enabled template has the same kind |
| `409 GENERATION_DATA_UNAVAILABLE` | Missing required template or incompatible reference data |
| `409 IDENTITY_CONFLICT` | University already reserved the subject with different identity fields |
| `409 CASE_NOT_READY` | Known unfinished case. `Retry-After: 1` |
| `422 INVALID_FIELDS` | Invalid kind, empty issuer, invalid validity days, or attempted kind change |
| `422 UNKNOWN_SUBJECT` or `422 INVALID_SCENARIO` | Invalid returning-subject or scenario input |
| `503 DEPENDENCY_UNAVAILABLE` | A required dependency is unavailable. Credential never returns an empty bundle as a substitute. |

Errors use `{code, message, request_id, details: [{field, reason}]}`. A defective but typed document returns `200 Validation` with failure flags instead of HTTP `422`.

After a transient consumer failure, the consumer retries after 1, 5, and 30 seconds. It then sends the event to `credential.case-initialized.v1.dlq`. An invalid event schema or conflicting initialization goes to that queue immediately. Domain updates and inbox completion commit together. A reserved pending inbox resumes work. A ready, empty outsider bundle returns empty arrays from both document and validation reads.

## Required verification coverage

- Template coverage includes create, list, read, replace, and delete operations. It enforces one enabled template for each kind and retains selected values across a pending retry.
- Generation coverage includes every producer and scenario combination, empty bundles, and staff affiliation proofs.
- Impersonation coverage compares separate claim, printed, and record names for the reversible name-only fixture.
- Identity coverage confirms that University, not Credential, allocates unpadded student sequences and mailbox collision suffixes.
- Time coverage checks expiry at the exact boundary and confirms that results do not change as time passes.
- Validation coverage checks forged, expired, incomplete, and inconsistent flags independently and together.
- Idempotency coverage duplicates an event with a new event ID, then sends conflicting source values. Credential creates no extra documents and overwrites nothing.

## Storage and Lab 1 deployment

The public image is `mcittkmims/credential-service:<version>` ([published tags](https://hub.docker.com/r/mcittkmims/credential-service/tags)). Set `IMAGE_TAG` to pin a release, for example `export IMAGE_TAG=1.0.0`. Leave it unset to use `latest`, which points to the most recently published release.

The API listens on container port `8082`. Credential uses MongoDB as a single-member replica set named `rs0`, because its idempotency and case operations use multi-document transactions. Persist MongoDB's `/data/db` directory in a named volume. The healthcheck initializes the replica set on first startup.

Set these values in a local `.env`. Do not commit `.env` or deployment credentials.

| Setting | Required value |
| --- | --- |
| `MONGODB_URI` | Replica-set URI for the `credential` database. In the shared network, use `mongodb://mongodb:27017/credential?replicaSet=rs0&directConnection=true`. |
| `SERVER_ADDRESS` | Bind address. The image sets `0.0.0.0`; use the default unless a different container address is needed. |
| `SERVER_PORT` | Service port. Defaults to `8082`. |

The shared deployment needs these containers on one network.

| Container | Image and startup | Storage and access |
| --- | --- | --- |
| `mongodb` | `mongo:8.0` with `--replSet rs0`; wait for the healthcheck to report a writable primary. | Persist `/data/db` in a named volume such as `mongo-data`. Do not publish port `27017` to clients. |
| `credential` | Run the published Credential image after MongoDB is healthy. | Container port `8082`, optionally bound to `127.0.0.1:8082`. |

To start the published image against MongoDB on a Docker network, set `TEAM_NETWORK` to that network name and provide the URI through `.env`:

```sh
docker pull "mcittkmims/credential-service:${IMAGE_TAG:-latest}"
docker run --rm --network "$TEAM_NETWORK" --env-file .env \
  -p 127.0.0.1:8082:8082 "mcittkmims/credential-service:${IMAGE_TAG:-latest}"
```

The [Credential Postman collection](../../postman/credential-service.json) covers every implemented endpoint. It uses local port `8082`. The shared Compose file is a separate team task.
