# Domain types

These types define the shared wire format. [HTTP conventions](http.md) define primitive types and nullability.

## Shared enums

Services accept the wire values below and reject unknown values instead of mapping them to a local enum.

| Type | Allowed values |
| --- | --- |
| `Scenario` | `eligible`, `forged`, `impersonation`, `outsider` |
| `ApplicantRole` | `student`, `teaching_assistant`, `staff`, `alumnus`, `outsider` |
| `UniversityStatus` | `active`, `inactive`, `graduated`, `none` |
| `CredentialKind` | `student_id`, `university_email`, `enrollment_confirmation`, `else_registration` |
| `ValidationIssue` | `FORGED`, `EXPIRED`, `INCOMPLETE`, `INCONSISTENT` |
| `RecordKind` | `enrollment`, `outlook_group`, `course`, `academic_year`, `schedule`, `fcim_message` |
| `UniversityDataKind` | `program`, `registration`, plus every `RecordKind` |
| `Semester` | `autumn`, `spring` |
| `Action` | `accept`, `reject`, `flag`, `ban` |
| `RuleKind` | `major`, `year`, `enrollment_duration`, `role`, `ban`, `credential` |
| `RuleSetStatus` | `draft`, `published` |
| `LocalCaseState` | `pending`, `ready` |
| `SessionStatus` | `lobby`, `active`, `ending`, `ended` |
| `CaseProducer` | `applicant`, `credential`, `university_record` |

```text
Role = "moderator" | "junior_moderator"
ApplicantRole = "student" | "teaching_assistant" | "staff" | "alumnus" | "outsider"
Action = "accept" | "reject" | "flag" | "ban"
RecordKind = "enrollment" | "outlook_group" | "course" | "academic_year" | "schedule" | "fcim_message"
CredentialKind = "student_id" | "university_email" | "enrollment_confirmation" | "else_registration"
Claims = {first_name: string, last_name: string,
          student_id: string | null, major: string | null, year: Int | null,
          university_status: UniversityStatus,
          courses: string[], role: ApplicantRole, email: string}
Applicant = {case_id: Id, session_id: Id, claims: Claims}
Credential = {credential_id: Id, case_id: Id, kind: CredentialKind,
              holder_first_name: string, holder_last_name: string,
              student_id: string | null, issuer: string,
              issued_at: Time, expires_at: Time | null,
              data: StudentCard | UniversityEmail | EnrollmentProof | ElseRegistration}
StudentCard = {major: string}
UniversityEmail = {email: string, groups: string[], role: ApplicantRole}
EnrollmentProof = {major: string | null, year: Int | null,
                   status: "active" | "inactive" | "graduated", role: ApplicantRole,
                   enrolled_since: Time | null, academic_year: string,
                   confirmation_number: string}
ElseRegistration = {academic_year: string, semester: "autumn" | "spring", course_ids: string[]}
Validation = {credential_id: Id, structurally_valid: Bool, authentic: Bool,
              expired: Bool, issues: string[], checked_at: Time}
UniversityRecord = {record_id: Id, case_id: Id, kind: RecordKind, subject_id: Id | null,
                    data: Enrollment | OutlookGroup | Course | AcademicYear | Schedule | FcimMessage}
Enrollment = {student_id: string | null, first_name: string, last_name: string,
              major: string | null, year: Int | null,
              status: "active" | "inactive" | "graduated", enrolled_since: Time | null,
              role: ApplicantRole}
OutlookGroup = {email: string, group_name: string, member: Bool}
Course = {course_id: string, title: string | null, exists: Bool, enrolled: Bool}
AcademicYear = {label: string, starts_at: Time, ends_at: Time}
Schedule = {semester: string, course_id: string, starts_at: Time, ends_at: Time}
FcimMessage = {author_first_name: string, author_last_name: string,
               channel: string, text: string, sent_at: Time}
Permission = {session_id: Id, player_id: Id, record_kinds: RecordKind[]}
Ban = {ban_id: Id, subject_id: Id, source_case_id: Id, reason: string, created_at: Time}
PolicyResult = {rule_version: Id, expected_action: Action, allowed_channels: string[],
                matched_rule_ids: Id[], violated_rule_ids: Id[], reasons: string[]}
Decision = {decision_id: Id, session_id: Id, case_id: Id, moderator_id: Id,
            action: Action, reason: string, policy: PolicyResult, correct: Bool,
            score_delta: Int, penalty: Int, created_at: Time}
```

`UniversityRecord.data` must match its `kind`. Services reject any other object shape. A `student_id` identifies an applicant or a person in a university record. The `case_id` remains the database key for a case. In initialization events and complete internal responses, document and record arrays sort by kind and then entity UUID. Course-code lists use lexical order. Paginated reads follow the shared pagination order. Readers compare course and group lists as sets and ignore delivery order.

`Credential.data` must match `kind`: `student_id` uses `StudentCard`, `university_email` uses `UniversityEmail`, `enrollment_confirmation` uses `EnrollmentProof`, and `else_registration` uses `ElseRegistration`. The common holder first and last names and `student_id` identify the values printed on that document. `Enrollment` also represents staff affiliation, and staff may have no student ID. `Course.exists = false` requires `title = null` and `enrolled = false`.

An empty record array means that a completed authoritative lookup found no records. Only authorized internal consumers can read the full record set. Players can inspect only the records allowed by their permissions. Credential validation checks documents independently of the access policy. The `authentic` field in a generation input is private metadata and does not appear in a player-visible credential.
