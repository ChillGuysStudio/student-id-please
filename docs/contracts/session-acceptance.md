# Session retained acceptance draft

## Status

This is a protocol proposal, not an implemented Session endpoint. It records Alexandru's lobby response 245 to Adrian's questions 239. Current Session source `ef34c02f1e33fbb514ccb16546ba75f20401b44a` retains request IDs and idempotency data but has no accepted-attempt lookup. Gateway routing must add any agreed route and caller allowlist before use.

The team needs retained business authority for deferred initialization and broker projection after the initiating Player token expires. A valid short-lived Gateway grant only proves the synchronous request. The accepted attempt must retain the identity and operation that Session authorized while the actor was valid.

## Lookup proposal

Proposed receiver path:

```text
GET /internal/v1/sessions/{session_id}/accepted-attempts/{attempt_id}
```

Call through internal Gateway with the initiating service's own credentials. Gateway issues a `gateway-workload+jwt` assertion for the exact lookup. Session authenticates Gateway's receiver credential, verifies the workload assertion, and checks signed `azp` against the attempt's permitted callers. The response is authenticated retained state; it requires no additional receipt signing key.

The response returns an immutable `acceptance` object plus a separate current `lifecycle` object. A compact JWT or original Player token must never be part of this response. The companion JSON Schema describes the proposed response shape only.

| Acceptance field | Meaning |
| --- | --- |
| `version` | Fixed integer 1 |
| `attempt_id` | Session's durable UUID request identifier |
| `operation` | `snapshot_start` or `case_initialize` |
| `session_id`, `team_id` | Original Session and team |
| `actor_id`, `actor_role`, `actor_token_id`, `actor_expires_at` | Actor proof and role that Session checked at acceptance |
| `accepted_at` | UTC timestamp of committed acceptance |
| `idempotency_key`, `normalized_body_sha256` | Same operation replay key and validated request identity |
| `entry_service` | One agreed initializer, or null for snapshot start |
| `case_id` | Proposed case ID pinned before dispatch, null for snapshot start |
| `rule_version`, `reference_at`, `snapshot_id` | Session's pinned rule and snapshot context |
| `allowed_callers`, `allowed_effects` | Named callers and exact business effects authorized for this attempt |

The receiver uses `lifecycle.session_status`, `lifecycle.attempt_status`, `lifecycle.checked_at` and `lifecycle.effects_allowed` from the current lookup. Persisted acceptance survives Player expiry. An ended Session or failed or superseded attempt must return `effects_allowed=false`; a receiver must not authorize a new effect from the historical acceptance alone. Missing attempts fail closed. Session returns 403 to a recognized caller outside the attempt's allowlist and 404 for a missing attempt. Authentication failures return 401.

This draft uses operation names as explicit business identifiers. The final caller/effect lists must agree with Applicant, Credential, University and projection owners. A lookup does not mint administrator authority or authorize unrelated routes.

## Acceptance transaction and retries

Session verifies the live actor, role, team and Session prerequisites before accepting. It records acceptance and dispatch intent in one transaction before external work. A stable UUID identifies the accepted attempt. The client idempotency key belongs to the same Session, actor and operation. A repeated key with the same validated normalized body returns the original acceptance; changed input returns 409 without rewriting it.

Normalize the validated schema representation before hashing. Owners must specify the exact canonical JSON encoding and defaults for each operation before implementation. Gateway request hashes continue to cover exact transported bytes. The normalized business hash is a different check and must not replace them.

Dispatch and projection carry `attempt_id` and pinned IDs. Initializers validate retained acceptance before reserving or writing. They retain their own same-attempt idempotency record. Consumers validate the producer's authenticated broker identity and use an atomic inbox/effect/outbox transaction, acknowledging only after commit. A lost response or broker redelivery cannot create another case or subject.

Lookup and effect application introduce a lifecycle race if Session can end or supersede acceptance between them. Owners must agree how Session leases or fences an effect, or how the operation checks a retained generation atomically. A successful GET alone cannot close this race. This draft does not claim distributed atomicity.

## ID allocation requiring owner agreement

Current Session stores its request ID before initializer dispatch, but the initializer returns the case ID afterward. The proposed change makes Session allocate and persist `case_id` before dispatch. Each initializer must honor that ID rather than creating a replacement. University reserves at most one `subject_id` for the accepted attempt and binds it once before any projection uses it.

Adrian and Alexei must confirm whether their initializers and reservation API can honor these IDs, or provide the precise existing reservation contract. The lookup shape allows a null subject before reservation; dependent effects must remain disallowed until that binding exists. The immutable acceptance must not be silently rewritten when a subject arrives. Use a separately retained, once-only reservation binding keyed by `attempt_id`, and return it as current lifecycle context or revise this proposed shape by owner agreement.

The current schema therefore exposes `subject_id` only in `lifecycle.reservation`, alongside its `bound_at`, while `acceptance.case_id` is pinned before dispatch. Case initialization requires a nonnull case ID. Snapshot start has no case or reservation. Owner review must settle this before receiver implementation.

## Verification still required

Required checks include lost dispatch responses, same-key replay, changed-body 409, original Player expiry after valid acceptance, denied callers, ended/superseded/failed attempts, reservation replay, mismatched case/subject IDs, lifecycle races, forged broker `user_id`, restart recovery, and inbox/outbox commit failures. No such real peer or broker tests have run for this proposal.

The identity and Session parent issues remain open. A focused protocol PR can complete only the draft and its agreed schema. The implementation, route activation and live acceptance evidence require separate reviewable changes.
