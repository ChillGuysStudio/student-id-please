# Simulation data

These fixtures and representation rules apply to generated evidence. [Case initialization](cases.md) defines how services derive their records.

The values below are simulated teaching fixtures. They do not represent an official UTM curriculum or a closed list. Administrators can add programs, courses, academic periods, and university facts through the University data CRUD. The same representation rules apply to new entries.

## University reference data and snapshots

```text
ProgramDefinition = {code: string, name: string, study_years: Int}
CourseDefinition = {course_id: string, title: string, major: string, year: Int,
                    semester: "autumn" | "spring"}
UniversityRegistration = {course_id: string}
UniversityDataKind = "program" | "registration" | RecordKind
UniversityDataInput = {kind: UniversityDataKind, subject_id: Id | null,
                       data: ProgramDefinition | UniversityRegistration | CourseDefinition | Enrollment |
                             OutlookGroup | AcademicYear | Schedule | FcimMessage}
UniversityData = UniversityDataInput & {reference_id: Id}
UniversitySnapshot = {snapshot_id: Id, session_id: Id, reference_at: Time,
                      entries: UniversityData[]}
IdentityReservationInput = {case_id: Id, subject_id: Id, first_name: string, last_name: string,
                            role: ApplicantRole, university_status: UniversityStatus,
                            major: string | null, admission_year: Int | null}
UniversityIdentity = {subject_id: Id, first_name: string, last_name: string,
                      student_id: string | null, email: string}
```

For reference data, `kind = course` uses `CourseDefinition`; the per-case `Course` type records the result of looking up a course and that person's registration. `kind = registration` links a subject to a course and uses `UniversityRegistration`. Enrollment, registration, Outlook membership, and FCIM messages require a non-null `subject_id`. Programs, course definitions, academic years, and schedules use `subject_id = null`. Each reference subject has one enrollment or affiliation row. Course and program codes are unique, and each `(subject_id, course_id)` pair has one registration. Snapshot creation validates references and rejects overlapping academic periods. Programs last from 1 to 8 years. Course titles and program names contain 1 to 120 characters.

At shift start, Session creates one immutable university snapshot and pins its ID alongside the rule version. Applicant and Credential fetch that snapshot through internal REST, while University reads its copy. The snapshot supplies reusable university data without copying another service's generated case. Services may cache a snapshot by ID but cannot replace it with current editable data. An outage leaves initialization pending or returns `503` before acceptance. Services do not substitute fallback facts.

Editing or deleting live reference data affects future snapshots. Services retain existing snapshots for the lifetime of their shifts and cases. A `snapshot_id` identifies a data snapshot. Generator versions use a separate identifier. Event-schema changes follow the existing RabbitMQ `schema_version` contract.

## Initial programs and courses

Seed programs are `FAF` (Software Engineering), `IA` (Applied Informatics), `TI` (Information Technology), and `SC` (Computer Systems), each with four study years. A program code contains 2 to 6 uppercase ASCII letters. Course codes contain no more than 32 uppercase letters, digits, or hyphens, and each code is unique. The initial course definitions follow:

| Major | Year | Autumn course and title | Spring course and title |
| --- | --- | --- | --- |
| FAF | 1 | `FAF-PROG1`: Programming Foundations | `FAF-DISCRETE`: Discrete Structures |
| FAF | 2 | `FAF-OOP`: Object-Oriented Design | `FAF-DATA`: Data Structures |
| FAF | 3 | `FAF-NET`: Networked Applications | `FAF-DB`: Database Design |
| FAF | 4 | `FAF-DIST`: Distributed Systems | `FAF-TEST`: Software Testing |
| IA | 1 | `IA-COMP`: Computing Basics | `IA-MATH`: Applied Mathematics |
| IA | 2 | `IA-ALGO`: Algorithms | `IA-STATS`: Statistics |
| IA | 3 | `IA-MODEL`: Data Modeling | `IA-OPT`: Optimization |
| IA | 4 | `IA-ML`: Machine Learning | `IA-VIS`: Data Visualization |
| TI | 1 | `TI-INTRO`: IT Foundations | `TI-WEB`: Web Foundations |
| TI | 2 | `TI-OS`: Operating Systems | `TI-DB`: Database Administration |
| TI | 3 | `TI-SEC`: Systems Security | `TI-OPS`: Service Operations |
| TI | 4 | `TI-CLOUD`: Cloud Applications | `TI-AUDIT`: Infrastructure Audit |
| SC | 1 | `SC-LOGIC`: Digital Logic | `SC-ELEC`: Electronics |
| SC | 2 | `SC-ARCH`: Computer Architecture | `SC-EMBED`: Embedded Programming |
| SC | 3 | `SC-SIGNAL`: Signal Processing | `SC-CTRL`: Control Systems |
| SC | 4 | `SC-RT`: Real-Time Systems | `SC-IOT`: Connected Devices |

`AcademicYear` ranges are half-open: `starts_at <= reference_at < ends_at`. The initial period is `2026-2027`, from `2026-09-01T00:00:00Z` to `2027-09-01T00:00:00Z`. Autumn runs until `2027-02-01T00:00:00Z`, and spring runs until the period ends. Seed one `Schedule` per course for its semester's interval. New periods and schedules are CRUD data. Snapshot creation requires one academic year and unambiguous course schedules at the reference time.

For generated students, course selection uses matching major, year, and current semester, sorted by course code. Select up to the preset's `course_count`; fewer available courses means select all available, including zero. A course cannot be registered if it does not exist. University derives a per-case `Course` row for each selected course. An unknown course claim produces `exists = false` without creating a catalog entry.

## Person fields and identifiers

| Role / status | Student ID and major | Year | Courses | University email |
| --- | --- | --- | --- | --- |
| `student` / `active` | Present | 1 through program length | Current program/year/semester | Student address |
| `student` / `inactive` | Present | Last study year | Empty | Student address; no active group membership |
| `teaching_assistant` / `active` | Present | 1 through program length | Current program/year/semester | Student address plus teaching-assistant group |
| `staff` / `active` | Both null | Null | Empty | Staff address |
| `alumnus` / `graduated` | Present | Null | Empty | Retained student address; alumni group |
| `outsider` / `none` | Both null | Null | Empty | Personal address |

First and last names are separate, required Unicode strings of 1 to 60 characters. Store each in Unicode NFC. Identity comparison trims ends, collapses internal whitespace, and case-folds each field on its own. Store and transmit the separate fields without a redundant full name. Clients may display `first_name + " " + last_name`. Course lists are sorted sets and cannot be null. Create codes in uppercase and emails in lowercase, then compare their canonical forms.

- Student ID. Use `{MAJOR}-{YY}-{SEQUENCE}`, for example `FAF-25-1`, `FAF-25-2`, then `FAF-25-10`. University allocates a positive, unpadded decimal sequence within `(major, admission_year)` in one transaction. The value must match `^[A-Z]{2,6}-[0-9]{2}-[1-9][0-9]*$`. Simulation admission years run from 2000 to 2099, and the two printed digits must match the stored full year. Sequence numbers increase and remain unavailable after reference deletion. Staff and outsiders have no student ID, while alumni retain their original ID. A presented ID provides evidence but cannot authenticate a user or identify a case.
- Study year. Let `A` be the first year of the pinned academic-year label. For current students, `year = A - admission_year + 1`; require `1 <= year <= study_years`. Generated enrollment starts on September 1 of the admission year. For alumni, use a completed program ending before the current academic year, with no current study year. An existing reference enrollment keeps its stored dates. Policy duration comes from those dates instead of the printed identifier.
- Email local part. Normalize the first and last name to lowercase ASCII as separate values, then join them with a period. Fold `ă/â` to `a`, `î` to `i`, `ș/ş` to `s`, and `ț/ţ` to `t`. Remove remaining combining marks and apostrophes, retain hyphens, collapse whitespace, and remove characters outside `[a-z0-9-]`. Both components must remain non-empty.
- University email. Students, teaching assistants, and alumni use `<first>.<last><suffix>@isa.utm.md`; staff use `<first>.<last><suffix>@utm.md`. The first reservation has no suffix, followed by `1`, `2`, and so on: `eliza.caraman@isa.utm.md`, `eliza.caraman1@isa.utm.md`, `eliza.caraman2@isa.utm.md`. In one transaction, University allocates the lowest unused suffix for `(normalized first, normalized last, domain)`. It does not reuse an address. A later legal-name update leaves the allocated mailbox unchanged. Student groups are `students`, `major:<code>`, and `year:<n>`; add `teaching-assistants` for TAs. Staff use `staff`, alumni use `alumni`. Inactive students retain groups with `member = false`; active affiliations and alumni use `member = true`.
- Outsider email. Outsiders use no university mailbox. Use `<first>.<last><n>@example.net`, where `n` is a deterministic positive value from the case seed. This simulated presented value sits outside University's uniqueness namespace.
- Stable synthetic names. Choose a first name from `[Eliza, Gavril, Iulian, Larisa, Petru, Sabina]` and a last name from `[Bivol, Caraman, Duca, Mocanu, Plesca, Vieru]` using the deterministic choices below. Existing reference subjects keep their names. For name impersonation, choose the presented pair by `case_id` with purposes `presented-first-name` and `presented-last-name`. If either selected field equals the corresponding actual field after normalization, advance to the next candidate in the cycle. The resulting fields differ from the actual names, use names from the lists, and contain no case ID.

Examples of the email normalizer use names not present in the seed catalog:

| First name | Last name | Student mailbox base |
| --- | --- | --- |
| `Cătălin` | `Mîndru` | `catalin.mindru@isa.utm.md` |
| `Sorina-Maria` | `Botezatu` | `sorina-maria.botezatu@isa.utm.md` |
| `Nicolae` | `D'Amico` | `nicolae.damico@isa.utm.md` |

For an existing `subject_id`, reference enrollment and memberships take precedence over generated defaults. Contradictory reference entries fail snapshot validation. For a new university-affiliated subject, the initializer first chooses names and requests one University identity reservation. Applicant and Credential may request the reservation through internal REST, and University runs the same operation inside its service. The response fixes the student ID and university email placed in the source event. Subscribers reuse that identity. An initializer may allocate a new subject UUID but cannot relabel an existing person to bypass a ban.

The reservation is unique by `subject_id` and idempotent by case and idempotency key. Repeating identical data returns the original identity. Changing names, role, major, or admission year for an existing reservation returns `409 IDENTITY_CONFLICT`. University allocates the next student sequence and email suffix in one transaction. A consumed reservation remains allocated after a case-propagation failure, which prevents another person from receiving the same identifiers.

## Cross-service representation invariants

| ID | Invariant |
| --- | --- |
| `I1` | Every applicant-evidence identity object has separate non-empty `first_name` and `last_name`; no applicant-evidence wire type has a combined person `name`. |
| `I2` | Role/status pairs follow the person-fields table; services reject unknown enum values. |
| `I3` | Students, teaching assistants, and alumni have a reserved student ID and major; staff and outsiders have neither. |
| `I4` | Student IDs match `{MAJOR}-{YY}-{SEQUENCE}` and the stored major/admission year; sequence is positive and unpadded. |
| `I5` | University emails use the role's domain and University's reserved suffix; outsiders never receive a university domain. |
| `I6` | A subject keeps the same reserved student ID and university email across cases; University does not reallocate them. |
| `I7` | Active student/TA courses exist in the pinned program, year, and semester; staff, alumni, inactive students, and outsiders have no current courses. |
| `I8` | Course and group lists are non-null sorted sets; services reject duplicates. |
| `I9` | Exactly one source branch appears in `CaseInitialized`, matching the authenticated producer. |
| `I10` | Only the scenario table's named fields may diverge; `eligible` is evidence consistency, not guaranteed admission. |
| `I11` | Generated case evidence and university snapshots are immutable; CRUD changes affect future snapshots/cases only. |
| `I12` | Empty outsider documents/records are completed evidence and can reach `ready`; missing delivery remains pending. |

## Credential bundles and defects

Every non-outsider generation bundle includes an enrollment or affiliation confirmation. It provides enough printed identity information for the other services to derive their data when Credential initiates. Staff receive an affiliation confirmation of the same kind with null student fields. The confirmation remains in the document bundle and does not create a separate `claims` section.

| Kind | When generated | Kind-specific data | Default issuer |
| --- | --- | --- | --- |
| `student_id` | Student ID is present | `major` | `SIM-REGISTRY` |
| `university_email` | University affiliation exists | `email`, `groups`, `role` | `SIM-IT` |
| `enrollment_confirmation` | University affiliation exists, including staff and alumni | Major, year, status, role, enrollment date, academic-year label, confirmation number | `SIM-REGISTRY` |
| `else_registration` | At least one current course | Academic year, semester, sorted course IDs | `SIM-ELSE` |

Default issuance is the shift reference time; default expiry is the pinned academic-year end. Historical enrollment dates appear in separate fields. Confirmation numbers use `CONF-<case_id>`. Authentic alumni confirmations prove graduation alone. A genuine alumni document may remain unexpired.

| Defect | Representation | Validation |
| --- | --- | --- |
| Forged | Private `authentic = false` on the enrollment confirmation; printed fields may remain consistent | `authentic = false`, issue `FORGED` |
| Expired | `expires_at <= reference_at` | `expired = true`, issue `EXPIRED` |
| Incomplete | A required printed string is `""` or a required printed list is empty, e.g. the mailbox address | `structurally_valid = false`, issue `INCOMPLETE` |
| Inconsistent | A card's printed major differs from the enrollment confirmation / its own ID | `structurally_valid = false`, issue `INCONSISTENT` |

Typed JSON fields remain present for defective documents. An absent envelope field, wrong JSON type, or mismatched `kind` and `data` causes a contract error. Gameplay defects use valid envelopes. A validator reports each applicable issue in sorted order so one severity label cannot hide another failure. `authentic` describes document issuance. It does not establish whether its bearer tells the truth, and an identity lie does not make each document forged.

The four initial scenarios add no expiry or structure defects. Internal fixtures can apply those defects to generated documents. Generated enrollment identity fields remain complete and provide the derivation anchor. A malformed mailbox address cannot become a new authoritative university email.
