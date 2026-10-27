# Case initialization

Session selects one initializer. The other two case services derive only their own records. See the [domain types](domain.md), [simulation data](simulation.md), and [event contract](events.md).

```text
CaseStart = {session_id: Id, attempt_id: Id, case_id: Id, scenario: "random"}
CaseAccepted = {case_id: Id, session_id: Id, state: "pending"}
LocalCaseStateResponse = {case_id: Id, session_id: Id, state: LocalCaseState}
CaseSeed = {case_id: Id, session_id: Id, initialization_attempt_id: Id,
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
| `POST /internal/v1/applicant/cases` | Applicant owns<br>Session calls | `CaseStart` with retained Moderator acceptance | `202 CaseAccepted` |
| `POST /internal/v1/credential/cases` | Credential owns<br>Session calls | `CaseStart` with retained Moderator acceptance | `202 CaseAccepted` |
| `POST /internal/v1/university-record/cases` | University Record owns<br>Session calls | `CaseStart` with retained Moderator acceptance | `202 CaseAccepted` |
| `GET /internal/v1/applicant/cases/{case_id}/status` | Applicant owns<br>Session calls | None | `200 LocalCaseStateResponse` |
| `GET /internal/v1/credential/cases/{case_id}/status` | Credential owns<br>Session calls | None | `200 LocalCaseStateResponse` |
| `GET /internal/v1/university-record/cases/{case_id}/status` | University Record owns<br>Session calls | None | `200 LocalCaseStateResponse` |

The event envelope's `producer` is the discriminator: `applicant` requires `claims`, `credential` requires `credentials`, and `university_record` requires `university_records`. Each payload has one domain section, including when its value is an empty array. The payload omits `source` and `generation_version`. Embedded `case_id` values must match the outer case, and entity IDs are unique within their owning service. A record's `subject_id` identifies its person; global academic-year and schedule records have null subjects.

Session allocates and retains both `attempt_id` and `case_id` before dispatch. Every initialization command requires those exact IDs; an initializer must not generate replacement IDs or fall back when either is absent. It obtains the snapshot ID and reference time from verified retained acceptance, resolves `random` once, and allocates any new subject ID once. It commits its owned records, original version-2 event, and idempotency result together. The initializer must complete the University binding below before returning `CaseAccepted`, whose case and session IDs must equal Session's pins.

Production `CaseStart` follows Session's existing dispatch: `scenario = random`, with no `seed` or `subject_id` override. The accepted player request contains only `entry_service`; it does not authorize arbitrary fixture inputs. Deterministic generator tests may supply a local seed or reference subject, but that is not another network authority mode. Generate a UUID-string seed once and persist it. Seeds contain 1 to 128 ASCII letters, digits, hyphens, underscores, or periods. A selected reference subject must have enrollment or affiliation in the pinned snapshot. Outsiders have null subjects; a reference-subject selection excludes `outsider`.

## Retained initialization authority

These requirements repair the propagation gap in [#182](https://github.com/ChillGuysStudio/student-id-please/issues/182); they are a contract, not evidence that the adapters exist. All peer REST uses the internal Gateway with bounded existing HTTP clients. Workload authentication identifies the caller, not the accepted actor.

The [retained HTTP policy](retained-workload.md) fixes the exact caller, method, path, query, body, and hop key for initialization, local status, reservations, and snapshot reads. Actorless snapshot GET carries only explicit `session_id` and `attempt_id` context alongside its snapshot path. University independently checks fresh acceptance and its actual immutable snapshot before disclosure. This agreement does not activate Gateway routes.

1. The initializer accepts commands only from authenticated Session through Gateway and looks up `GET /internal/v1/sessions/{session_id}/accepted-attempts/{attempt_id}` under its own workload identity. Require acceptance version `1`, operation `case_initialize`, matching session/attempt/case IDs, its own canonical name as `entry_service`, retained `actor_role = moderator`, membership in `allowed_callers`, and effect `case_initialize` in `allowed_effects`. Verify the snapshot belongs to that session and has the retained `reference_at`. When a synchronous actor proof is present, its subject must equal retained `actor_id`. Session workload dispatch can resume retained work without that transient proof, but cannot invent actor authority.
2. The initializer's `Idempotency-Key` is exactly `attempt_id`, Session's case `request_id`, not the player's original key. Acceptance's `idempotency_key` remains the original player request key. Require `normalized_body_sha256` to equal SHA-256 of UTF-8 `json.dumps({"entry_service": entry_service}, sort_keys=True, separators=(",", ":"))` with Python's default ASCII escaping. It is not a hash of `CaseStart`, generated scenario/seed/subject, or raw Gateway bytes. Retain and compare this hash and original key unchanged on retries. Do not replace either with a downstream key or digest. Only the fixed dispatch body above is derivable from this existing accepted request. Changed pins or command data under the same attempt conflict.
3. Before new effects, require `lifecycle.session_status = active`, `attempt_status` in `accepted`, `pending`, or `ready`, and `effects_allowed = true` from a fresh lookup for that operation. Ended, completed, failed, superseded, missing, mismatched, or noncurrent attempts authorize nothing. A 404, forbidden caller, timeout, malformed response, or contradictory binding fails closed; transient failures may retry within existing bounds, never become successful empty evidence.
4. For a non-null subject, the selected initializer invokes University's existing [reservation operation](api.md#university-record-service-endpoints), or the same local operation when University initializes. University independently verifies retained acceptance, `subject_reserve`, the selected initializer, actor, snapshot, reference time, and pinned case, then commits the subject binding in its existing identity record before `CaseAccepted`. A reference identity keeps its existing identifiers and facts. A null-subject outsider skips reservation but not Session authority checks.
5. A subscriber uses the version-2 event's `initialization_attempt_id` for the same Session lookup. Require effect `case_project`, its own allowed caller, and authenticated event producer equal to retained `entry_service`. Match session, attempt, case, snapshot and reference time. For a non-null subject, read University's real reservation using those same IDs and match its persisted binding to acceptance and the event before deriving records. University applies the same check locally. `lifecycle.reservation = null` from Session supplies no subject-binding proof and does not show that University's persisted binding is absent. Neither event correlation nor workload identity substitutes for these checks.

An accepted asynchronous task may finish after the original `actor_expires_at` if its current retained scope still permits the effect. Retained actor/token metadata is not a bearer, refresh grant, admin permission, or authority for a new player action. Never store, replay, or forward the original bearer JWT for retained work. `attempt_id` here is an application initialization identity; it is not a Lab 3 outbound HTTP attempt ID. Each actual HTTP send still receives its own transport accounting identity, including lookup and retry sends.

Consumers quarantine cross-session snapshots and conflicting or unverifiable bindings without overwriting existing data. Completed exact duplicates remain no-ops and grant no new effects. [Version-1 history](events.md) must not be relabeled or treated as retained proof.

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

A service marks its local state ready only after committing its records, including a completed empty bundle. `CaseAccepted.state = pending` describes aggregate initialization; the selected initializer may already have committed its own ready projection.

Session marks the case ready only when all three owners report ready. During its aggregate check, an owner `404` for a case known to Session means propagation is pending. An unknown Session case remains `404`. Failed or quarantined initialization remains pending for repair.

Moderation calls Session's aggregate status before evaluating a new decision, then reads complete evidence from all three owners. The [decision readiness HTTP policy](decision-readiness.md) defines the internal actor-bound aggregate status call for Moderation and Server Rules. Readiness cannot depend on a separate client poll. Neither a failed read nor a missing projection can become a successful empty bundle or an admission result. Only the three case services read hidden initialization payloads; readiness responses and public administrative preset APIs do not expose them.
