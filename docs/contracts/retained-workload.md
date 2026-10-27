# Retained initialization HTTP policy

This agreement completes the contract work in [#189](https://github.com/ChillGuysStudio/student-id-please/issues/189), following [retained initialization authority](cases.md#retained-initialization-authority). It defines narrow internal Gateway policies, not route activation or runtime readiness. [HTTP conventions](http.md), [reservation types](api.md#university-record-service-endpoints), and [immutable snapshot rules](simulation.md#university-reference-data-and-snapshots) still apply.

## Status and boundary

The receiver repairs and Session pinning are merged in their service repositories. They are not deployed. Gateway currently permits the actorless accepted-attempt lookup only. Initialization and status remain `Unagreed`, reservation POST remains `Unagreed`, and snapshot and reservation GET still require delegation. This agreement does not change those policies, images, service pointers, or configuration.

Gateway authenticates a named workload and constrains its exact HTTP operation. The receiving owner checks retained business authority independently. Gateway must not query Session as if it were Applicant, Credential, or University. No new Session lookup caller, grant service, business effect, or metadata-header system is needed.

Canonical caller names are `session`, `applicant`, `credential`, and `university_record`. The University's path component is `university-record`, not a caller alias. All paths below use the private Gateway listener. Public ingress never accepts workload authority or exposes `/internal/v1`.

## Exact workload requests

The table describes only actorless requests. Every GET has zero body bytes and no `Idempotency-Key` header, including an empty header. Every POST has exactly one nonempty canonical UUID key and a JSON object with exactly the documented fields. Reject duplicate JSON members before schema validation. All IDs are canonical lowercase hyphenated UUIDs. Unknown query names, duplicate parameters, blank values, encoded name aliases, malformed escapes, and conflicting pins fail closed before forwarding or disclosure.

Query-bearing requests have exactly the listed parameters, each once. Parameter order may vary. Names and UUID values use literal ASCII without percent encoding. Gateway signs and forwards the original raw query without reordering it. Query-free routes require no query, not a placeholder parameter. GET bodies such as `{}` or `null` are not empty bodies.

| ID | Caller | Method and exact path | Query | Body | Hop key | Receiver requirement |
| --- | --- | --- | --- | --- | --- | --- |
| `W1` | `applicant`, `credential`, `university_record` | `GET /internal/v1/sessions/{session_id}/accepted-attempts/{attempt_id}` | None | None | Absent | Session verifies the attempt belongs to the path session and the caller is in its retained `allowed_callers`. |
| `W2` | `session` | `POST /internal/v1/applicant/cases` | None | `CaseStart` | `attempt_id` | Applicant is the retained selected initializer; effect `case_initialize`. |
| `W3` | `session` | `POST /internal/v1/credential/cases` | None | `CaseStart` | `attempt_id` | Credential is the retained selected initializer; effect `case_initialize`. |
| `W4` | `session` | `POST /internal/v1/university-record/cases` | None | `CaseStart` | `attempt_id` | University is the retained selected initializer; effect `case_initialize`. |
| `W5` | `session` | `GET /internal/v1/applicant/cases/{case_id}/status` | None | None | Absent | Applicant verifies its stored attempt with fresh `case_project` authority. |
| `W6` | `session` | `GET /internal/v1/credential/cases/{case_id}/status` | None | None | Absent | Credential verifies its stored attempt with fresh `case_project` authority. |
| `W7` | `session` | `GET /internal/v1/university-record/cases/{case_id}/status` | None | None | Absent | University verifies its stored attempt with fresh `case_project` authority, regardless of selected initializer. |
| `W8` | `applicant`, `credential`, `university_record` | `POST /internal/v1/university-identities/reservations` | None | `IdentityReservationInput` | `case_id` | University verifies selected caller, `subject_reserve`, and the actual subject binding. |
| `W9` | `applicant`, `credential`, `university_record` | `GET /internal/v1/university-identities/{subject_id}` | `case_id`, `session_id`, `attempt_id` | None | Absent | University verifies `case_project` and the exact persisted subject binding. |
| `W10` | `applicant`, `credential`, `university_record` | `GET /internal/v1/university-snapshots/{snapshot_id}` | `session_id`, `attempt_id` | None | Absent | University verifies the retained case effect and actual immutable snapshot as specified below. |

`CaseStart` has exactly `session_id`, `attempt_id`, `case_id`, and `scenario = random`. It has no seed, subject, actor, snapshot, or reference-time override. Session supplies its already-pinned attempt and case. `IdentityReservationInput` has exactly the ten fields in the API definition. Its nullable fields remain present, and the simulation identity constraints still apply. Gateway checks shape and key equality. Receivers check values and business authority, not just possession of a Gateway assertion.

No row authorizes a wildcard method, path prefix, initializer switch, event alias, snapshot creation, public case-status call, or unrelated evidence read. In particular, Moderation's internal call to `/api/v1/sessions/{session_id}/cases/{case_id}/status` still needs a [separate actor-bound policy](decision-readiness.md). It is not a Session workload poll.

## Proof on both hops

The caller sends its configured `X-Service-Name` and `X-Service-Token` to internal Gateway. Actorless requests carry no `Authorization`, `X-Gateway-Assertion`, `X-Gateway-Delegation`, `X-Gateway-Chat-Capability`, or caller-supplied actor identity. Duplicate credentials or authority headers fail authentication. Gateway does not turn a rejected actor request into a workload request.

Gateway replaces ingress credentials with `X-Service-Name: gateway`, the receiver-specific hop credential, and a fresh `X-Gateway-Assertion` of type `gateway-workload+jwt`. The receiver verifies both the hop and the pinned Gateway signature, issuer, audience, version, lifetime, and exact signed caller. The assertion has exactly `v`, `iss`, `aud`, `iat`, `exp`, `jti`, `azp`, `method`, `path`, `query_sha256`, `body_sha256`, and `idempotency_sha256`. It has no actor claims, `session_id` claim, delegation, or scopes. The existing Gateway identity v1 rules require `v = 1`, `iss = student-id-gateway`, `0 < iat <= now < exp`, and a lifetime of at most 30 seconds.

The hashes cover the escaped downstream path's accompanying raw query, forwarded body bytes, and exact key value under the existing identity contract. Absent query, body, or key hashes the empty byte string. Receivers compare these bytes independently. An assertion for another caller, audience, method, path, query, body, or key is invalid. No receiver manufactures a player principal from workload claims.

## Fresh retained proof

For each operation that reads hidden data or creates or resumes effects, the receiver obtains a fresh `W1` response under its own workload identity. A cached snapshot, stored binding, old acceptance response, request ID, or retry header cannot replace this check. Session returns immutable `acceptance` and current `lifecycle` separately. The lookup has no side effect and can return historical acceptance with `effects_allowed = false`.

The case checks below apply to `W2` through `W10`, not to Session's authorization of `W1`. Existing `snapshot_start` lookup and actor-bound snapshot creation remain unchanged. `W1` does not require active case scope merely to return retained history to an allowed caller.

Every receiver requires acceptance version `1`, operation `case_initialize`, exact session/attempt/case IDs, a recognized selected initializer, and its own membership in `allowed_callers`. Retained `actor_role` is `moderator`. Require a canonical `actor_id`, nonempty `actor_token_id`, positive integral epoch `actor_expires_at`, and valid UTC `accepted_at`. Retain the original actor metadata without inventing a renewed actor or administrator privilege. A synchronous actor proof must have the retained `actor_id` as its subject and satisfy its existing token-chain checks. It does not replace the original retained token metadata.

`idempotency_key` is the original player key. `normalized_body_sha256` is SHA-256 of UTF-8 `json.dumps({"entry_service": entry_service}, sort_keys=True, separators=(",", ":"))` with Python's default ASCII escaping. Neither value becomes the initializer key, reservation key, or transport hash. Retried stored proofs must compare all immutable pins, including original key/hash and actor metadata. The snapshot ID and reference time come from this acceptance, never a current-session search or caller assertion.

Require `lifecycle.session_status = active`, `attempt_status` in `accepted`, `pending`, or `ready`, and boolean `effects_allowed = true`. `checked_at` must be a valid current UTC timestamp from this bounded lookup. Do not reuse a response from an earlier operation or retry. Failed, superseded, completed, noncurrent, ended, missing, malformed, or contradictory scope authorizes no new read or effect. A task may continue past original actor expiry only while these current checks permit it. Never store or replay a bearer JWT.

An initialization POST additionally requires the owner equal `entry_service` and effect `case_initialize`. Reservation POST requires the caller equal `entry_service`, both caller and University in `allowed_callers`, and effects `case_initialize` and `subject_reserve`. Reservation GET requires the subscriber and University in `allowed_callers` and effect `case_project`. Workload identity is necessary but is never the business authorization by itself.

## Minimal retained snapshot context

`W10` adds only `session_id` and `attempt_id` to the existing snapshot path. Together they address the existing retained lookup. A case ID, effect name, actor, snapshot metadata, and original key/hash need not be repeated on the wire because acceptance already pins them. `snapshot_id` alone does not identify an accepted operation. Session must not infer an attempt from mutable latest state, and University must not search for any attempt that permits the requested snapshot.

For the selected initializer, require retained effect `case_initialize`. For either other case service, require `case_project`. This dependency read needs no new `snapshot_read` business effect. University also requires itself and the requesting caller in `allowed_callers`. `session` is not an actorless snapshot reader. University applies equivalent checks when it reads locally, without a self-HTTP call.

Before serializing any entries, University independently performs the following checks:

1. Verify the exact `W10` workload request and parse both explicit query IDs.
2. Fetch `W1` as `university_record` for those IDs and apply the fresh retained checks above. Resolve the case only from this acceptance.
3. Load the actual immutable local snapshot named in the path. Require its ID to equal `acceptance.snapshot_id`, its `session_id` to equal the explicit session and acceptance, and its `reference_at` to equal acceptance's reference instant.
4. Return only that snapshot. Missing local data, mismatched pins, or dependency failure discloses no entries. Do not substitute current editable data, another snapshot from the same session, or a successful empty result.

The caller independently compares the response's snapshot/session/reference with its retained command or version-2 event context, including the pinned case. A subscriber must also verify University's real subject reservation before deriving non-null-subject records. Snapshot access does not prove a subject binding. Requiring a reservation before an initializer reads reference data would be circular, so `W10` neither creates nor requires that binding. Outsiders skip subject reservation, not retained checks.

### Existing synchronous snapshot reads

The existing actor-bound snapshot GET keeps an empty query and requires a valid delegation from an allowed existing caller, including Session. University checks the verified Moderator, active Session, and actual snapshot against the live Session pins. It keeps the original actor expiry and chain deadline.

The exact two-parameter query selects the retained workload mode. An empty query never selects that mode. Partial context, extra context, a delegation combined with retained query context, or an invalid actor proof fails without trying the other mode. Receivers choose the trusted route/profile combination before verification, not by catching a verification failure and trying a weaker profile. Existing valid synchronous initialization semantics remain actor-bound and must also agree with retained acceptance. This agreement grants no new synchronous delegation scopes.

## Status, subject binding, and replay

`W5` through `W7` return only local readiness for Session. A known local case supplies its immutable session/attempt pins, not a mutable latest attempt. The owner verifies `case_project`, retained initializer, snapshot/reference, original key/hash, and stored actor context before returning the matching `LocalCaseStateResponse`. All three owners can be subscribers. University must not restrict status to cases it initialized. An unknown local case returns `404`; Session treats that as pending only for a case Session already knows. A status read cannot allocate, regenerate, publish, or reveal hidden generation data.

On `W8`, University commits identity and immutable per-case provenance atomically before `CaseAccepted`. The real record fixes session, attempt, case, subject, initializer, actor, snapshot/reference, original player key/hash, and effect `subject_reserve`. It preserves reference facts and existing identifiers. On `W9`, University reads fresh Session proof and compares every binding field with its existing local record before disclosure. A null `lifecycle.reservation` is neither evidence of a University binding nor evidence that no binding exists. An identity-only hit cannot authorize a case. One case cannot bind two subjects, including concurrent requests. Reads never allocate or backfill provenance.

Stored cases, snapshots, version-1 event history, and identity allocations remain intact when current authority ends. Completed exact duplicates may return their stored result or be acknowledged as no-ops under existing replay rules. They create no new effects and do not authorize a fresh snapshot or reservation read after scope ends. A replay still authenticates the caller and compares the original key, request, pins, and stored provenance. Changed data conflicts rather than overwriting history. Pending work requires fresh authority before resumption. Other events remain v1; `CaseInitialized` remains v2.

Fresh lookup is not a distributed lock. Session's current-case serialization and readiness/scoring rules must prevent a stale attempt from producing new effects after transition. Owners must verify delayed responses and concurrent lifecycle transitions before activation. No lease API or distributed-atomicity claim is introduced here.

## Errors and bounded calls

Use the existing `Error` response from the HTTP contract. Invalid hop/signature/profile uses `401` with the adapter's existing auth code. Gateway rejects an authenticated but out-of-policy caller or request with `403 FORBIDDEN`. University rejects retained proof failures with `403 RETAINED_ATTEMPT_FORBIDDEN`; Applicant and Credential retain their existing `403 INITIALIZATION_AUTHORITY_DENIED`. Malformed syntax uses `400`; invalid typed field values use `422`. Duplicate or unknown context is rejected, never silently ignored.

Session's lookup returns `403 SERVICE_FORBIDDEN` for a recognized but disallowed caller and `404 ATTEMPT_NOT_FOUND` for an absent or cross-session attempt. University returns `404` for a missing snapshot, identity, or exact binding only after the required authorization checks. Changed immutable reservation inputs return `409 IDENTITY_CONFLICT`; changed command/key input returns `409` under existing idempotency conventions. No error response contains snapshot entries, hidden scenario data, credentials, or proof tokens.

An unavailable or malformed dependency is not an empty proof. Use existing `503` dependency errors, `504 TASK_TIMEOUT` for task deadlines, and `503 TASK_LIMIT_EXCEEDED` for capacity. Preserve Gateway's existing internal `503 DEPENDENCY_TIMEOUT` mapping and bounded retries. Each lookup, original send, and explicit retry has separate [Lab 3 transport accounting](lab3.md#bounded-calls-and-failure-accounting). The retained `attempt_id`, player key, reservation key, request ID, and event ID are not outbound transport-attempt identities. Gateway accounts for its backend hop and the service accounts for its Gateway hop. No automatic replay of business writes is added.

## Contract fixtures and owner checks

The [wire fixtures](retained-workload-v1/fixtures.json) contain synthetic requests, pinned acceptance, local metadata, and negative cases. Request examples show wire shapes, not permissions under a single acceptance. `W3` and `W4` require their own matching selected-owner acceptance and normalized hash. The empty snapshot entries test metadata comparisons, not simulation-data validity. The [CPR fixture tests](../../tests/test_retained_workload_contract.py) check shape, cross-references, and exact-byte hashes. They do not implement authorization, exercise receivers, or prove runtime security. The following cases are receiver and Gateway acceptance requirements, not passing runtime results.

| Fixture | Required result |
| --- | --- |
| `initializer` | The selected owner accepts the exact pinned command with `attempt_id` as its key. |
| `subscriber` | A different case owner reads only the pinned snapshot under `case_project`. |
| `expired-actor` | Fresh current retained scope permits the dependency read after actor expiry without a JWT replay. |
| `synchronous` | Empty-query actor-bound snapshot reads keep their existing Moderator, pin, and expiry checks. |
| `completed-duplicate` | Exact stored completion is a no-op, not authority for another read or effect. |
| `missing-context` | Actorless snapshot GET without both context IDs fails closed. |
| `duplicate-context` | Repeating a parameter, even with the same value, fails closed. |
| `unknown-query` | Adding `case_id`, an effect selector, or any other snapshot query name fails closed. |
| `conflicting-context` | Mixing actor delegation with retained query context fails without fallback. |
| `cross-session` | An attempt from another session grants no access. |
| `wrong-snapshot` | A different path snapshot grants no access, even within the same session. |
| `local-snapshot-mismatch` | A local snapshot with different session or reference time discloses no entries. |
| `forged-proof` | A forged assertion or a valid assertion replayed for different bytes fails authentication. |
| `wrong-caller-effect` | A disallowed caller, nonselected initializer, or missing required effect grants no access. |
| `stale-scope` | Ended, failed, superseded, completed, noncurrent, or false-effect scope grants no new read or effect. |
| `dependency-failure` | Timeout or malformed acceptance fails closed, without fallback facts. |
| `wrong-key-hash` | A downstream key or digest cannot replace the original player key/hash in retained provenance. |
| `missing-binding` | A non-null subject without the exact University binding cannot produce a projection. |
| `null-session-reservation` | A real matching University binding remains usable when Session returns null reservation. |
| `changed-binding` | Changed subject or provenance returns conflict without overwriting the existing record. |
| `subscriber-status` | Session can poll University's projection when Applicant or Credential initialized the case. |
| `transport-retry` | Two sends for the same retained operation have distinct transport-attempt IDs and one accounting owner per hop. |

## Receiver-before-policy rollout

These are owner follow-ups after this contract merges, not work performed by this PR.

1. `mcittkmims` updates Applicant and Credential snapshot clients to pass their already-retained session/attempt context and use the workload client only for retained work. Keep synchronous actor-bound callers separate. Add actual HTTP boundary tests for the wire fixtures and original-key/hash preservation.
2. `MaxNoragami` adds University's retained snapshot GET verification, strict query/profile selection, and independent local snapshot comparison. Align University status with `case_project` for all selected producers. Test missing, duplicate, unknown, conflicting, cross-session, and stale context, plus real reservation comparisons and synchronous regression cases.
3. `Tirppy` verifies Session dispatch and readiness against these receiver contracts, including current lifecycle transitions, delayed responses, and a non-University initializer. Session keeps its existing acceptance API and caller/effect lists. It does not mirror University's subject binding.
4. The shared Gateway owner, explicitly `mcittkmims` for this policy follow-up, adds only the exact workload rows after receiver tests pass. Keep actor-bound snapshot GET separate, enforce exact query/body/key shapes, and test denied routes and raw-byte proof mutation. Unrelated `Unagreed` routes stay disabled.
5. The coordinator arranges source-matched publication and receiver-before-Gateway deployment, then bounded real-peer and broker verification. Until compatible receivers are deployed, the new workload policies stay disabled. No image or runtime change belongs to this contract PR.
