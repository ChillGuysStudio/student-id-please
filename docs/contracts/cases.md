# Case initialization

Session selects one initializer. The other two case services derive only their own records. See the [domain types](domain.md), [simulation data](simulation.md), and [event contract](events.md).

```text
CaseStart = {session_id: Id, scenario: "eligible" | "forged" | "impersonation" | "outsider" | "random",
             seed: string?, subject_id: Id?}
CaseAccepted = {case_id: Id, session_id: Id, state: "pending"}
LocalCaseState = {case_id: Id, session_id: Id, state: "pending" | "ready"}
CaseSeed = {case_id: Id, session_id: Id,
            scenario: "eligible" | "forged" | "impersonation" | "outsider",
            seed: string, subject_id: Id | null, university_snapshot_id: Id, reference_at: Time}
GeneratedCredential = {credential: Credential, authentic: Bool}
CaseInitializedPayload =
    CaseSeed & {claims: Claims}
  | CaseSeed & {credentials: GeneratedCredential[]}
  | CaseSeed & {university_records: UniversityRecord[]}
```

| Method and path | Owner and authorized caller | Request | Success response |
| --- | --- | --- | --- |
| `POST /internal/v1/applicant/cases` | Applicant owns<br>Session calls | `CaseStart` with Moderator context | `202 CaseAccepted` |
| `POST /internal/v1/credential/cases` | Credential owns<br>Session calls | `CaseStart` with Moderator context | `202 CaseAccepted` |
| `POST /internal/v1/university-record/cases` | University Record owns<br>Session calls | `CaseStart` with Moderator context | `202 CaseAccepted` |
| `GET /internal/v1/applicant/cases/{case_id}/status` | Applicant owns<br>Session calls | None | `200 LocalCaseState` |
| `GET /internal/v1/credential/cases/{case_id}/status` | Credential owns<br>Session calls | None | `200 LocalCaseState` |
| `GET /internal/v1/university-record/cases/{case_id}/status` | University Record owns<br>Session calls | None | `200 LocalCaseState` |

The event envelope's `producer` is the discriminator: `applicant` requires `claims`, `credential` requires `credentials`, and `university_record` requires `university_records`. Each payload has one domain section, including when its value is an empty array. The payload omits `source` and `generation_version`. Embedded `case_id` values must match the outer case, and entity IDs are unique within their owning service. A record's `subject_id` identifies its person; global academic-year and schedule records have null subjects.

The initializer obtains the snapshot ID and reference time from verified Session context, resolves `random` once, and allocates the case ID and any new subject ID once. It commits its owned records, original event, and idempotency result together. Optional internal `seed` and `subject_id` inputs support reproducible fixtures and returning reference subjects; players cannot supply them. A seed contains 1 to 128 ASCII letters, digits, hyphens, underscores, or periods. Generate a random UUID string if omitted. A supplied subject must have an enrollment or affiliation in the pinned snapshot, or the command returns `422 UNKNOWN_SUBJECT`. The `outsider` scenario requires no subject; supplying one returns `422 INVALID_SCENARIO`. When a subject is supplied with `random`, select from `[eligible, forged, impersonation]`.

Consumers verify that the referenced snapshot belongs to the event's session and has the same `reference_at`. They use the authenticated initializer's original Session authorization and ignore player identities in event data. The Applicant, Credential, and University Record services are the authorized producers of initialization events. Consumers quarantine an event that reuses a snapshot from another shift as a schema or context conflict.

## Deterministic choices and source precedence

For a bounded choice, calculate SHA-256 over the UTF-8 JSON array `[key, purpose]` with no extra whitespace. Interpret the first eight digest bytes as an unsigned big-endian integer and take modulo the candidate count. Candidates sort by stable code or UUID unless this contract specifies their order. Empty required candidate sets return `409 GENERATION_DATA_UNAVAILABLE`; an optional course list may be empty. Use neither process-global random state nor event delivery order.

Use `seed` for scenario, program, year, and preset choices with purposes `scenario`, `major`, `year`, and `preset`. `random` without a supplied subject selects from `[eligible, forged, impersonation, outsider]`. Program candidates sort by code; year candidates are integers from 1 to that program's length in numeric order. Use `subject_id` (or `case_id` for an outsider) with purposes `first-name` and `last-name` for the name tables. Each service generates credential and record UUIDs with UUIDv5 and namespace `case_id`: `credential:<kind>`, `record:enrollment`, `record:academic_year`, `record:outlook_group:<group_name>`, `record:course:<course_id>`, `record:schedule:<course_id>`, and `record:fcim_message:<reference_id>`. One case may have many documents and records. `UNIQUE(case_id)` protects the aggregate rather than each child row.

Each owner stores its selected reusable preset or template values when it reserves a pending case and before it generates data. Retries reuse the stored selection after an administrator edits or deletes the live template. The seed alone cannot snapshot editable data. Inbox state distinguishes a reserved or pending event from a completed event. A worker resumes pending generation and acknowledges the event after domain completion.

| Owner | As initiator | As subscriber |
| --- | --- | --- |
| Applicant | Select a local profile preset, generate first/last names, reserve a new university identity when applicable, then generate only presented claims | From credentials: use holder first/last names and enrollment proof fields, mailbox email, and ELSE courses. From university records: use enrollment, Outlook membership, and enrolled courses. Apply the prescribed impersonation name pair once. |
| Credential | Generate names and reserve a new university identity when applicable, then build only its document bundle using local templates | From claims: print the supported identity and courses, restoring only the actual first/last pair for impersonation. From university records: print the verified affiliation and registered courses. Apply document authenticity rules below. |
| University Record | Reserve the identity locally and generate its authoritative enrollment/affiliation, memberships, course results, academic year, schedules, and optional FCIM facts | From claims: derive enrollment/affiliation and memberships, restoring only the actual first/last pair for impersonation. From credentials: derive identity from holder/enrollment fields and registrations from ELSE. Check codes and dates against the pinned snapshot; never treat `authentic = false` as an instruction to invent a different enrollment. |

For a new University-initiated subject, use the same active-student defaults as Credential, selecting up to two current-semester courses. Applicant defaults come from its selected preset. For an existing reference subject, all initiators use that subject's recorded facts instead of changing its role or identity through a preset. Existing course registrations come from the snapshot's `registration` entries, limited to courses scheduled for the current semester.

Received source fields form the derivation input. Consumers cannot ignore them and generate a different person from the seed. A source may omit fields it cannot express. For example, an empty outsider document bundle conveys no names, so Applicant uses the deterministic name rule. When a new subject's mailbox is incomplete, a subscriber reads the existing University identity reservation. It does not reconstruct an email from the subject UUID or allocate another suffix. University fills course titles and schedules from its snapshot. The scenario's named differences define the permitted contradictions. Any other contradiction with an existing reference subject causes a conflicting initialization.

## Scenario divergence rules

| Scenario | Claims | Credentials | University records |
| --- | --- | --- | --- |
| `eligible` | Truthful identity and affiliation | Authentic, structurally valid, unexpired bundle | Confirm identity and affiliation; the role may still fail access policy |
| `forged` | Truthful identity and affiliation | Enrollment confirmation has `authentic = false`; other documents remain authentic | Confirm the actual affiliation even though one supporting document is forged |
| `impersonation` | Replace only `first_name` and `last_name` with the deterministic different presented pair | Genuine documents retain the actual holder fields | Retain the actual subject and names, revealing the contradiction |
| `outsider` | Status `none`, role `outsider`, null student fields, no courses, deterministic personal email | Empty bundle | Empty record set; local state can still be ready |

The first impersonation fixture changes the first and last name alone. Recover the actual pair from the supplied subject's snapshot enrollment or existing identity reservation, then derive the presented pair from the case ID as specified above. All six subscriber paths remain deterministic without a hidden `actual` profile. Full stolen-identity bundles and other lie patterns require new divergence rules shared by all services. The `subject_id` identifies the actual applicant instead of the presented name pair.

`eligible` describes consistent evidence. Server Rules still decides whether to accept the case. Case services do not send the scenario to Server Rules, choose a policy result, or include an expected action in a generation event.

Consumers persist the original producer and normalized payload with their derived records. Duplicate comparison ignores object-key order, while generation arrays use stable order. An identical initialization under the same or a different event ID is a no-op after completion. Different producer, metadata, or source values for the same case go to quarantine without overwriting or rerolling the stored case. A subscriber creates its own domain projection and publishes no new initialization event.

A service marks its local state ready only after committing its records, including a completed empty bundle. Session marks the case ready only when all three owners report ready. During event propagation, a known Session case with a consumer `404` is still pending. Failed or quarantined initialization remains pending for repair. Moderation cannot score it. Only the three case services read hidden initialization payloads; neither readiness responses nor public administrative preset APIs expose them.
