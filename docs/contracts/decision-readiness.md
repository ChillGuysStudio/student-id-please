# Decision readiness HTTP policy

This agreement completes the contract work in [#207](https://github.com/ChillGuysStudio/student-id-please/issues/207), following normal case initialization in [#199](https://github.com/ChillGuysStudio/student-id-please/issues/199). It defines the narrow internal actor-bound policy for aggregate case-readiness reads by Moderation and Server Rules. [HTTP conventions](http.md), [case initialization](cases.md), [Session and Moderation APIs](api.md#server-moderation-session-service-endpoints), and the [retained initialization HTTP policy](retained-workload.md) still apply.

## Status and boundary

Retained workload routes `W1` through `W10` are merged and deployed. Normal case initialization and the public aggregate `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` return `200` with `state = ready` and all three case owners verified. The internal actor-bound `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` route remains `Unagreed` in Gateway policy for Moderation. The Server Rules business adapter also requires that internal actor-bound readiness read and is absent from its caller allowlist. Existing delivery scopes neither grant the exact readiness read to Moderation nor pin a narrow readiness grant for Rules policy evaluation.

This agreement defines the shared wire and authorization contract. It is not route activation, container publication, or delivery evidence. No other `Unagreed` route alias, event policy, token profile, header format, compatibility mode, case-generation rule, scoring calculation, policy fact, or progression rule changes here.

Canonical caller names for this policy are `moderation` and `rules`. The target receiver is `session` with audience `student-id-session-service`. Both routes below use the private internal Gateway listener. Public participant reads on `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` keep their existing participation semantics on the public Gateway listener.

## Exact actor-bound requests

The table below defines the internal actor-bound Session reads used during decision submission and policy evaluation. Both routes require zero body bytes and no `Idempotency-Key` header, including an empty header. All path and query identifiers are canonical lowercase hyphenated UUIDs. Unknown query names, duplicate parameters, blank values, encoded aliases, malformed escapes, and non-empty GET bodies such as `{}` or `null` fail closed before forwarding.

| ID | Caller | Method and exact path | Query | Body | Hop key | Receiver requirement |
| --- | --- | --- | --- | --- | --- | --- |
| `R1` | `moderation`, `rules` | `GET /internal/v1/sessions/{session_id}/context` | `player_id` | None | Absent | Session verifies that `player_id` equals the verified actor `sub` and returns fresh participant and shift state. |
| `R2` | `moderation`, `rules` | `GET /api/v1/sessions/{session_id}/cases/{case_id}/status` | None | None | Absent | Session verifies the active shift, assigned Moderator actor, and known current case before polling `W5` through `W7` under its own workload identity. |

`R1` requires the single literal ASCII query parameter `player_id={sub}` without percent encoding. `R2` requires an empty query string with no `?` or placeholder parameter. Neither route accepts an actorless `gateway-workload+jwt` token, an initializer workload proof, or a Session status poll as a substitute for Moderator delegation.

## Proof on both hops

The caller sends its configured `X-Service-Name` and `X-Service-Token` to the internal Gateway listener together with `X-Gateway-Delegation` of type `gateway-delegation+jwt`. The request carries no `Authorization`, `X-Gateway-Assertion`, `X-Gateway-Chat-Capability`, or caller-supplied actor headers. Duplicate credential headers or mixed grant headers fail authentication. Gateway never converts a missing or rejected actor delegation into a workload request.

Gateway verifies that the authenticated service caller equals the delegation's `azp` claim and that a signed scope entry matches the exact target, method, path, and query. Gateway replaces ingress headers with `X-Service-Name: gateway`, the Session hop credential, and a fresh `X-Gateway-Assertion` of type `gateway-request+jwt`.

The downstream assertion carries `v = 1`, `iss = student-id-gateway`, `aud = student-id-session-service`, `iat`, `exp`, `jti`, `azp` set to `moderation` or `rules`, `sub`, `actor_jti`, `actor_exp`, `is_admin = false`, `session_id`, `method`, `path`, `query_sha256`, `body_sha256`, and `idempotency_sha256`. On `R2`, `query_sha256`, `body_sha256`, and `idempotency_sha256` all equal the SHA-256 digest of the empty byte string. Every exchange obeys `0 < iat <= now < exp <= parent.exp <= actor_exp` and `exp - iat <= 30`.

## Grant issuance and policy hop narrowing

Grant issuance at Gateway and fresh business checks at receivers are distinct steps. Gateway derives signed scope boundaries from the verified request structure and parent grant containment. It does not invent facts or proofs from an unverified user body, and a signed scope alone does not prove current shift state.

### Public Moderation decision ingress

When a player calls `POST /api/v1/sessions/{session_id}/decisions` on the public Gateway listener with `{case_id, action, reason}` and a canonical UUID `Idempotency-Key`, Gateway verifies the Player bearer token, current Session participation, and assigned Moderator role. Administrator privilege and Session ownership do not replace that role. Gateway issues fresh decision dependencies only when the shift is active and this case is current. Otherwise it uses the context-only boundary below.

That delegation derives its Session and evidence scopes from the accepted path `session_id` and decision body `case_id`:

1. Exact Session context read: `target = session`, `method = GET`, `path = /internal/v1/sessions/{session_id}/context`, `exact_path = true`, and `query = "player_id={sub}"`.
2. Exact Session readiness read: `target = session`, `method = GET`, `path = /api/v1/sessions/{session_id}/cases/{case_id}/status`, `exact_path = true`, and `query = ""`.
3. Existing Moderation evidence reads for `applicant`, `credential`, and `university-record` pinned to the same `case_id` and `session_id`, plus `POST /internal/v1/policy/evaluations` on `target = rules` with `exact_path = true` and `query = ""`.

### Completed results without fresh case authority

This boundary preserves [business idempotency](http.md#idempotency) after scoring clears the current case, a later case starts, or the shift ends. It does not authorize another decision. The request shape, bearer verification, assigned Moderator role, and exact path and body pins remain mandatory.

If the Session is not active or the requested case is not current, Gateway forwards the decision POST to Moderation with only the exact `R1` context scope for this Session and actor. The delegation has `azp = moderation`, the same verified actor, and the existing bounded lifetime. It contains no `R2`, evidence, Rules evaluation, snapshot, initialization, event, prefix, or wildcard scope. A context-only delegation cannot be narrowed into any of those permissions.

Gateway does not know whether the request matches a committed decision. It neither queries Moderation's idempotency store nor caches a result. Moderation independently reads current Session context and verifies the actor's assigned Moderator role. It may then return its durable result only when the caller, original key, endpoint, and request fingerprint match. A changed body under the same key returns `409`. A new key or missing result cannot bypass the receiver's active-shift and current-case checks, call evidence or policy dependencies, or commit a decision or outbox row.

The context read remains available for this narrow result lookup in `lobby`, `ending`, or `ended` state and after the current case changes. Those states still authorize no new decision readiness or evaluation. Wrong actors, expired credentials, malformed requests, and cross-session grants remain denied. No new proof type, header, replay flag, or compatibility mode is introduced. The [synthetic result fixtures](decision-replay-v1/fixtures.json) describe this boundary without claiming production persistence or runtime delivery.

### Moderation-to-Rules policy hop narrowing

When `moderation` calls `POST /internal/v1/policy/evaluations` through the internal Gateway listener with its parent `X-Gateway-Delegation`, canonical `Idempotency-Key`, and `PolicyInput` body, Gateway authenticates `moderation` and verifies parent grant containment. Existing `POST /internal/v1/policy/evaluations` body, query, and grant containment requirements remain mandatory and do not weaken. The `session_id` and `case_id` in `PolicyInput` must match the parent delegation's pinned session and case and the active Session's current case.

Gateway narrows the parent grant with `NarrowDelegation` to mint a child `gateway-delegation+jwt` for `azp = rules`:

1. The child grant keeps the exact `sub`, `actor_jti`, `actor_exp`, and `is_admin = false` from the parent grant.
2. The child deadline is `min(now + 30, parent.exp, actor_exp)`. The hop never extends the parent grant lifetime or the original Player token expiry.
3. The `rules` recipient receives only the two exact `session` dependency scopes for that same `session_id` and `case_id`: `R1` with `query = "player_id={sub}"` and `R2` with `query = ""`.
4. The child grant excludes Applicant, Credential, and University Record evidence scopes, initialization or reservation scopes, administrator authority, and further policy-evaluation scopes.

Every scope in both delegations requires `exact_path = true` and an explicit `query` string. In the Gateway identity module, an omitted `query` field means unconstrained query parameters, whereas `query = ""` requires an empty query. Prefix scopes, wildcard paths, omitted query constraints, and re-scoping from an untrusted callback request are forbidden.

## Independent receiver and Session checks

Possession of a valid delegation or request assertion does not replace receiver business checks. Both `moderation` and `rules` call `R1` and `R2` through the internal Gateway listener before evaluating a new case decision. Returning a matching committed result uses only the context read and durable lookup described above. It never evaluates the case again.

From the fresh `R1` `SessionContext` response, the caller verifies all of the following conditions:

1. `session.session_id` equals the pinned `session_id`.
2. `session.status` is `active`. Shifts in `lobby`, `ending`, or `ended` state are rejected.
3. `session.current_case_id` is non-null and equals the pinned `case_id`. Prior, superseded, or unknown cases are rejected.
4. `player.player_id` equals the verified actor `sub`, and `player.role` is `moderator`. Decision submission and policy evaluation require the assigned Moderator role, not `session.owner_id == sub`, because the Session owner may assign the Moderator role to another participant before shift start.
5. For `rules`, `session.rule_version` equals `PolicyInput.rule_version` and `session.started_at` equals `PolicyInput.reference_at`.

On `R2`, Session independently verifies the Gateway hop, the `gateway-request+jwt` signature and lifetime, `azp` in `{"moderation", "rules"}`, active shift status, `sub` as the shift's assigned Moderator, and `case_id` as the known current case.

Session then polls `W5`, `W6`, and `W7` under its own actorless workload identity as defined in the [retained initialization HTTP policy](retained-workload.md). Session never forwards the Moderator's delegation to Applicant, Credential, or University Record. Neither `moderation` nor `rules` may call `W5` through `W7`.

## Aggregate readiness and bounded errors

`R2` returns only the existing `CaseStatus` schema:

```text
CaseStatus = {case_id: Id, session_id: Id, state: "pending" | "ready",
              ready_services: ("applicant" | "credential" | "university_record")[]}
```

The response never exposes hidden scenarios, seeds, presets, private authenticity flags, or case evidence. Session reports `state = ready` only when all three case owners report local `ready` and `ready_services` contains `applicant`, `credential`, and `university_record`. If any owner reports local `pending` or returns `404` for a case known to Session, Session returns `200` with `state = pending`. An unknown Session case returns `404`.

Callers verify that the returned `case_id` and `session_id` match their pinned values. When `state` is `pending`, `moderation` returns `409 CASE_NOT_READY` with `Retry-After: 1` and neither fetches policy evaluation nor commits a decision. When `rules` observes `state = pending`, it rejects evaluation with `409 CASE_NOT_READY` instead of evaluating partial facts.

If `R2` returns `state = ready` without all three canonical owner names in `ready_services`, returns mismatched identifiers, times out, or fails with `503` or `504`, the caller fails closed with `503` or `504`. Pending responses, `404` responses, timeouts, and malformed payloads never become an empty-ready result or a negative admission decision.

Invalid hop credentials, bad signatures, expired grants, or mixed token profiles return `401`. Disallowed callers, wrong actor roles, cross-session or wrong-case scopes, and prefix or wildcard grants return `403`. Noncurrent cases and `lobby`, `ending`, or `ended` shifts return `409` or `403` under the receiver's existing domain rules. Each outbound call on `R1`, `R2`, `POST /internal/v1/policy/evaluations`, and `W5` through `W7` uses a separate [transport attempt](resilience.md#bounded-calls-and-failure-accounting).

## Contract fixtures and owner checks

The [synthetic wire fixtures](decision-readiness-v1/fixtures.json) contain the active Session context, Moderator actor metadata, both delegation origins, exact `R1` and `R2` requests, separate `W5` through `W7` workload polls, aggregate status payloads, and negative test cases. The [CPR fixture tests](../../tests/test_decision_readiness_contract.py) verify structural consistency, scope containment, deadline bounds, and exact SHA-256 request hashes. They do not implement authorization, exercise live services, or prove runtime activation.

| Fixture | Required result |
| --- | --- |
| `moderation-readiness` | Moderation reads `R2` under the decision-ingress delegation for the active assigned Moderator and current case. |
| `rules-readiness` | Rules reads `R2` under the narrowed policy-hop delegation for the same Moderator, session, and current case. |
| `non-owner-moderator` | An assigned Moderator who is not `session.owner_id` passes fresh Session context and readiness checks. |
| `session-owner-polls-separate` | Session polls `W5` through `W7` with its own workload identity rather than Moderator delegation. |
| `wrong-caller` | An authenticated caller outside `moderation` and `rules` is denied on internal `R2`. |
| `missing-proof` | Internal `R2` without `X-Gateway-Delegation` or `X-Gateway-Assertion` fails closed without workload fallback. |
| `expired-proof` | An expired delegation, expired Player token, or child grant exceeding parent expiry fails authentication. |
| `mixed-proof` | Combining delegation with chat capability, raw bearer headers, or a workload assertion fails authentication. |
| `wrong-actor` | A Junior Moderator, including the Session owner after role reassignment, or a non-participant is denied. |
| `wrong-session` | A request path `session_id` outside the pinned delegation scope and active Session context is denied. |
| `wrong-case` | A request path `case_id` outside the pinned delegation scope and decision or policy body is denied. |
| `noncurrent-case` | A case that does not match `session.current_case_id` is rejected before readiness or evaluation succeeds. |
| `lobby-session` | A session in `lobby` status authorizes no decision readiness or policy evaluation. |
| `ended-session` | A session in `ending` or `ended` status authorizes no decision readiness or policy evaluation. |
| `extra-query` | Adding any query parameter to `R2` changes `query_sha256` and violates the empty-query scope. |
| `extra-body` | A non-empty GET body such as `{}` changes `body_sha256` and is rejected. |
| `extra-key` | Sending `Idempotency-Key` on `R2` violates the key-free GET rule and is rejected. |
| `scope-prefix` | A delegation scope with `exact_path = false` or a path prefix is rejected. |
| `scope-wildcard` | A delegation scope with a wildcard path or an omitted unconstrained `query` field is rejected. |
| `callback-rescope` | Narrowing or re-issuing a readiness scope for a different callback `case_id` is rejected. |
| `pending-status` | Aggregate `state = pending` returns `409 CASE_NOT_READY` and prevents policy evaluation or scoring. |
| `malformed-status` | `state = ready` with missing owners or mismatched case or session pins fails closed with `503`. |
| `unavailable-status` | Upstream `503` or `504` on Session readiness fails closed without inventing empty evidence. |

## Receiver and Gateway follow-up

These steps occur in dependent tasks after this contract PR merges, not in this PR:

1. `Tirppy` verifies that Session accepts internal `R2` from `moderation` and `rules` with `gateway-request+jwt`, enforces active shift, assigned Moderator, and current-case checks, and keeps `W5` through `W7` on Session's workload client.
2. `MaxNoragami` aligns Server Rules to call `R1` and `R2` with the narrowed delegation and reject pending, mismatched, or unavailable readiness before policy evaluation.
3. `andyp1xe1` verifies that Moderation calls `R1` and `R2` under the decision delegation, preserves `409 CASE_NOT_READY` with `Retry-After: 1` for pending cases, and forwards the delegation on `POST /internal/v1/policy/evaluations`.
4. The assigned Gateway maintainer activates the exact `R2` scope on decision ingress and the narrow `R1` and `R2` child scopes on the Rules policy hop after receiver checks pass.
