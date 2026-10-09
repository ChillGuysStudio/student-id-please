# Player and Session start follow-up

Checked on 2026-10-09 for CPR [#88](https://github.com/ChillGuysStudio/student-id-please/issues/88), [#77](https://github.com/ChillGuysStudio/student-id-please/issues/77) and [#114](https://github.com/ChillGuysStudio/student-id-please/issues/114). The [runtime packet](player-session-runtime.md) remains the configuration reference. CPR [#118](https://github.com/ChillGuysStudio/student-id-please/pull/118) merged that configuration and published Player `2.0.1` and Session `2.0.0` into Compose.

## Reproduced Gateway defect

Gateway [#15](https://github.com/ChillGuysStudio/gateway-service/pull/15), source `4a5c6e9ce1b417b28c048d02a8d58214896addeb`, fixes the start-only Player roster reads. A fresh run with published Player and Session confirms the team and all three Player lookups return 200. The next request is Session's read of its first junior's University permissions. Gateway rejects that request with 403 because its permission policy permits only the initiating actor's own assignment.

Gateway [#16](https://github.com/ChillGuysStudio/gateway-service/pull/16), source `09d13880a4eff283e16c6754ae130b9b51597e22`, fixes that specific delegation failure. It grants Session exact empty-query GETs for the stored lobby juniors during owner/Moderator start. Every cross-player exchange checks the authenticated Session caller, exact signed grant, current owner, Moderator role, lobby state and junior membership. DMs and generic grants remain actor-only. University retains its domain authorization.

The regression failed before the fix and passed afterward. The runtime comparison against a deliberately unavailable University destination changed the permission result from authorization 403 to dependency-unavailable 503. That verifies forwarding after authorization, not successful University behavior. No Player or Session implementation change was needed.

## Separate published University blocker

A second run used public University `2.0.0`, source `eb1f91573dee425f3f03707a68274b2ba942dc3a`, alongside the fixed local Gateway, published Player/Session, real PostgreSQL and a fresh authenticated Mongo replica set. Its anonymous public index is `sha256:b3dd337e998e543c0d598dcad7742dd1b1ced8904aad826dd2e214d69b4b77b7`; AMD64 child is `sha256:be4a12f215be47db2b61797ee0c5fbdd87c91a3b8fe511635589fa51b6de6a81`. ARM64 is present in the same index but was not executed locally.

All 22 expected observations matched, including the remaining failures:

- Owner `PUT /api/v1/sessions/{sid}/record-permissions` returned `403 FORBIDDEN` for a complete six-kind assignment split across the two real juniors.
- Each participant's `GET /api/v1/sessions/{sid}/record-permissions/me` returned `403 FORBIDDEN`.
- After all four Player reads passed, Session's first `GET /internal/v1/sessions/{sid}/record-permissions/{junior_id}` returned 403. Public start returned `403 DEPENDENCY_REJECTED`.

The public image's `/app/app.jar` was inspected without private repository access. `GatewayAuthorizationFilter` verifies the hop/proof first, returning 401 on failure. Its subsequent explicit operation allowlist contains no permission routes and returns the observed 403 for an unlisted operation. No `record-permissions` path string or permission controller was found among its application classes. The packaged gateway settings match the tested environment names, including `GATEWAY_AUDIENCE`, `GATEWAY_PUBLIC_KEY_FILE`, `GATEWAY_HOP_TOKEN`, `GATEWAY_INTERNAL_URL` and `GATEWAY_CALLER_TOKEN`.

This identifies a problem in that published artifact's allowed operations. It is not a claim about inaccessible current private University source. Merely changing credentials or allowing arbitrary actor headers will not supply the missing operation. Max must supply the existing permission implementation and reviewed receiver policy in a compatible public release, or identify a newer already-published compatible artifact.

## Exact dispatch mapping for retained adapters

These are facts from released Session `5e59c041daee541e1697d5e745c6e26bf52e79a1`. They clarify consumer wiring without changing the existing protocol.

| Operation | Outgoing request | Accepted-attempt identity |
| --- | --- | --- |
| Snapshot start | `POST /internal/v1/university-snapshots` with `{session_id, reference_at}` | The outgoing `Idempotency-Key` is Session's durable `attempt_id`. The body has no separate `attempt_id` field. |
| Case initialization | `POST /internal/v1/{initializer}/cases` with `{session_id, attempt_id, case_id, scenario:"random"}` | The outgoing `Idempotency-Key` equals the body's `attempt_id`. Session allocates and commits `case_id` before dispatch. |
| Retained lookup | `GET /internal/v1/sessions/{sid}/accepted-attempts/{attempt_id}` | Consumer authenticates as its own named workload through internal Gateway. Session verifies the exact receiver proof and the attempt's allowed caller. |

`acceptance.idempotency_key` is the original public client's operation key. It is different from the outgoing hop's `Idempotency-Key`, which is the generated attempt UUID. Consumers must not reject a valid dispatch by requiring those two distinct values to match.

`acceptance.normalized_body_sha256` hashes the validated public request. Snapshot start hashes `{}`. Case initialization hashes `{"entry_service":"<selected initializer>"}`. The encoding is Python `json.dumps(value, sort_keys=True, separators=(",", ":"))`, with default ASCII escaping, then UTF-8 and SHA256. It does not hash the expanded initializer dispatch payload. Gateway proof binding separately hashes the exact transported bytes.

Lookup returns immutable `acceptance` plus current `lifecycle`. Snapshot acceptance permits only `university_record` and `snapshot_create`. Case acceptance names `applicant`, `credential`, `university_record` and `case_initialize`, `subject_reserve`, `case_project`; consumers must also check the pinned operation, initializer, case, Session and context. The caller list alone does not authorize every effect.

Completed, ended, failed, superseded and noncurrent attempts return `effects_allowed=false`. `lifecycle.reservation` is currently null. University owns once-only subject reservation; the packet does not claim an implemented cross-service reservation binding or distributed atomicity. Accepted asynchronous work may survive original Player expiry only within its retained scope. The original compact Player token is never retained.

The Gateway acceptance document is an older proposal where it says Session has no lookup or allocates its case ID after dispatch. The released implementation and this owner packet supersede those historical implementation statements. Consumer compatibility and reservation enforcement still require Adrian/Max confirmation.

## Peer work needed

- Adrian: review Gateway #16 and agree the minimal snapshot and accepted-attempt routes with Max. Readiness and case-status wiring remain separate existing endpoints; enable them only with the matching receiver/consumer semantics.
- Max: deliver or identify a public University image implementing the documented permission routes, retaining owner/lobby, participation and initiating-caller checks. Confirm how the snapshot consumes the attempt identity above and how University retains its once-only subject reservation.
- Adrian and Max: confirm their consumers honor Session's pinned case UUID, the dispatch mapping, replay/idempotency behavior and current lifecycle denial. Applicant/Credential's concrete retained-authority adapters remain owner work. Do not add a new orchestration framework to resolve these existing contracts.
- Andrei: rerun the real-peer recipe after the reviewed fix and compatible University release. Then record Session activation, required DMs-to-Session reads, negotiation and actual direct frames with exact deployed versions in #114.

## Verification scope

[Sanitized runtime evidence](evidence/tirppy-session-start-followup.json) contains the baseline, forwarding comparison and published-University run. It records method/path/status and sanitized request IDs, never headers, request bodies, credentials or JWTs. Player/Session public image identities are unchanged from the runtime packet.

The local checks passed `go test -short -count=1 ./...`, `go test -race -short -count=1 ./...`, `go vet ./...`, 14 Python publication/release tests, focused regressions, formatting and diff checks. The Windows full executable smoke cannot launch its extensionless fixture binary. The [Linux CI run](https://github.com/ChillGuysStudio/gateway-service/actions/runs/37934148917) passed the full race suite, executable smoke, vet, Python tests and both cross-builds on retry. Its first attempt passed the modified runtime package and executable smoke but hit an unrelated limits socket-recovery timing failure; no patch change was made for the retry. All required PR checks are green on `09d13880`.

The Gateway runtime image was compiled locally for AMD64 from the named source and is not a published Gateway image or native ARM64 proof. Published service artifacts were anonymously SHA256-verified and loaded through the existing local Docker registry workaround. SQL databases and containers were disposable; only their sanitized observations were retained.

G6/G10 source and the disclosed Player/Session paths pass. University permission requests fail. Session activation, full real-peer G6/G10, negotiation and direct frames remain incomplete. This run adds no all-service G8 or Gateway G9 publication claim. #88 and #77 remain open.
