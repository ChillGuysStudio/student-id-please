# Gateway identity v1 candidate

## Status and ownership

This document describes the `internal/identity` module and proposes the adapter contract for routing and receivers. The module is source code with synthetic checks. Gateway configuration, HTTP routing and receiver middleware have not activated this contract. No live peer, container image or ARM runtime evidence comes from these fixtures.

The module branch starts at merged Gateway `dev` revision `03c4dcf99b1b619f96ee52aaa6a43650cfb856c3`. It carries the owned identity extension originally published at `cb02d97e00c27f505c881928669db952c4576751`, plus the separate workload profile and deadline checks. Routing was inspected at `bae4bec8aff921c6218a035ab1a996bd4554e67b`. Session was inspected at `ef34c02f1e33fbb514ccb16546ba75f20401b44a`. Those source reads establish the proposed interfaces only.

Alexandru owns this module and Player/Session alignment. Adrian owns the route table and Applicant/Credential adapters. Andrei owns Moderation/Discord DMs. Alexei owns shared Gateway configuration, limits and Java adapters. Owners must agree the route mapping and policy before receiver migration. The identity parent and receiver alignment issue remain open until their full acceptance is met.

## Four token profiles

Every Gateway token has exactly `alg`, `kid` and `typ` in its protected header. `alg` is `RS256`. Receivers pin trusted keys by `kid`; they never fetch a key from token headers. RSA keys require at least 2048 bits and exponent 65537. Reject unknown header fields, duplicate JSON keys, noncanonical base64url, unknown Gateway claims, case aliases and scalar nulls.

| JWT `typ` | Audience | Meaning | Lifetime |
| --- | --- | --- | --- |
| `gateway-request+jwt` | One receiver audience | Exact request with Player actor, or explicitly anonymous route | At most 30 seconds and original actor expiry |
| `gateway-workload+jwt` | One receiver audience | Exact operation initiated by an authenticated service | At most 30 seconds |
| `gateway-delegation+jwt` | `student-id-gateway` | Signed scope bound to the service allowed to exchange it | At most 30 seconds and original actor expiry |
| `gateway-chat+jwt` | `student-id-gateway` | Session and Player bound chat reads by Discord DMs | Until original Player expiry; each exchanged request remains capped at 30 seconds |

Common claims are `v=1`, `iss=student-id-gateway`, a single string `aud`, integral epoch seconds `iat` and `exp`, nonempty `jti`, and `azp`. Require `0 < iat <= now < exp`. There is no clock leeway. Non-chat profiles require `exp-iat <= 30`.

Actor profiles also carry `actor_exp`, `sub`, `actor_jti`, and optional boolean `is_admin`. `sub` is a canonical lower-case UUID. `actor_exp` remains the original Player expiry through every exchange. `actor_jti` remains the original Player token identifier. An absent `is_admin` means false. Receivers must reject string or number versions of this claim.

An anonymous request has `azp=gateway`, no actor subject or token identifier, no administrator privilege, and `actor_exp=exp`. Trusted routing permits this profile only on its explicit anonymous routes. It cannot mint a delegation.

A workload token requires the authenticated initiating service as `azp`. It excludes `sub`, `actor_exp`, `actor_jti`, `is_admin`, `session_id` and `scopes`, including explicit null or false forms. Receivers select a separate workload verification entry point. A workload token cannot pass actor verification or impersonate an anonymous public request. Durable business acceptance must authorize deferred effects separately.

## Player verification

Player currently issues `RS256`, `kid=player-v1`, `typ=JWT`, `iss=student-id-please`, `aud=student-id-players`, canonical UUID `sub`, and integral timestamps. Its JWKS endpoint is `GET /.well-known/jwks.json`. The module accepts the registered JWT audience representation as a string or nonempty string array containing the configured Player audience. Gateway-issued audiences are strings only.

`VerifyPlayerBearer` requires a pinned Player key, valid issuer and audience, valid nonexpired `exp`, optional positive `iat` no later than now and before expiry, optional positive `nbf` no later than now, and strict boolean `is_admin`. If `jti` is absent, the module uses `sha256:<hash of compact Player token>` as the audit identifier. A present malformed or empty `jti` fails verification. Extra Player application claims may exist; aliases of recognized fields fail verification.

JWKS fetching, cache refresh and signing-key rotation are integration work. Publish only public keys. Never serialize signing keys, caller tokens or retained compact JWTs into logs or public artifacts.

## Exact downstream request binding

Routing selects the static destination and rewrites the path before minting. `Binding` includes the target, its configured audience, HTTP method, escaped rewritten path, raw query bytes, raw body bytes and the exact `Idempotency-Key` value. The signed request contains `method`, `path`, and lower-case hexadecimal SHA-256 claims `query_sha256`, `body_sha256`, `idempotency_sha256`.

Hash the raw query without its leading `?`. Preserve parameter order, duplicates, percent-escape spelling and empty values. Hash the body bytes that the proxy will forward. Do not parse and reserialize JSON after signing. The absent and empty idempotency key both hash the empty byte string; business routes may require a nonempty key independently.

The module bounds compact tokens at 16 KiB, escaped paths at 2048 UTF-8 bytes, raw queries at 8192 bytes, bodies at 16 MiB, and idempotency values at 1024 ASCII bytes. The adapter supplies a positive body bound no greater than 16 MiB. Path checks reject encoded separators, backslashes, dot segments, invalid escapes, invalid UTF-8 and controls. Queries reject controls, spaces, non-ASCII characters and malformed query encoding. Idempotency values reject whitespace, controls, commas and duplicate header values. Limits and route allowlists may be stricter.

`BindRequest` buffers under the supplied bound, checks declared content length and restores those same bytes for forwarding. `VerifyRequest` and `VerifyWorkloadRequest` independently compare every signed component. A valid token for another path, method, query, body or idempotency value fails verification.

## Authentication on both HTTP hops

Internal ingress authenticates `X-Service-Name` and `X-Service-Token` as a configured pair. `ReadServiceCaller` produces an opaque `Caller` bound to that Engine. A header name supplied by an HTTP client is insufficient. Inbound service credentials must be distinct, at least 32 bytes, and provisioned outside source control.

The receiver hop uses `X-Service-Name: gateway` and a receiver-specific Gateway token. The adapter sets `X-Gateway-Assertion` to a fresh request or workload JWT. The hop credential authenticates Gateway; the signed `azp` preserves the initiating caller. The receiver checks both and applies its allowlist. Inbound caller credentials and outbound Gateway credentials are separate configuration maps.

The proposal deliberately uses the existing assertion header for the distinct workload JWT. Routing's required assertion header therefore remains present. The receiver chooses the expected JWT profile from its trusted route policy, then verifies it. It must not retry another profile after a failed verification to obtain access.

For actor delegation, a receiving service sends its own internal-ingress credentials and `X-Gateway-Delegation` to Gateway. Discord DMs uses `X-Gateway-Chat-Capability`. `ReadGrant` rejects both grant headers together and checks the header's expected JWT type. Incoming request assertions and raw Player bearer tokens cannot be exchanged as grants.

Authenticate ingress before calling `StripUntrustedHeaders`. Strip caller-supplied identity, target selection and transport headers before creating the receiver hop. Select a static target, never a client URL. Strip private identity headers from public responses and prevent private grants or hop credentials from leaking in response bodies. Preserve the intentional Player access-token response and ordinary cookies and content headers.

## Route identifiers requiring owner agreement

Routing revision `bae4bec` uses `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation` and `discord-dms`. The identity fixtures use `university-record` as a binding target and `discord-dms` as a caller. Session's earlier adapters use additional target aliases. These names are not interchangeable authentication identities.

The proposed adapter maps `routing.University` to binding target `university-record`, and `routing.Rules` to binding target `rules`. Other routing service names map unchanged. Configure one distinct receiver audience per binding target. The proposed deployment audiences are `student-id-player-service`, `student-id-session-service`, `student-id-applicant-service`, `student-id-credential-service`, `student-id-rules-service`, `student-id-university-record-service`, `student-id-moderation-service` and `student-id-discord-dms-service`, respectively. Lobby response 250 provided these exact defaults to the runtime owners. Owners must configure the same audiences and inbound caller names before activation. Do not accept several credential aliases as a migration shortcut.

`TargetCallers` identifies the actual receiving service for a delegation. It does not change the assertion's `azp`. Configure this map explicitly and validate every recipient has its own inbound credential.

## Trusted APIs and current policy

`IssueRequest`, `IssueDelivery`, `IssueDelegation` and `IssueChatCapability` are trusted Gateway minting APIs. The caller must first verify the Player actor and approve the selected route and business policy. Their exported `Actor` structure is not an HTTP authentication result by itself. Never construct it from client JSON or identity headers.

`IssueDelivery` returns an assertion and optional recipient delegation with the same chain deadline. Its scopes come from trusted route policy. An error returns no usable partial delivery. Route ownership, caller allowlists and current Session/role/resource state must bound every scope.

`IssueWorkloadRequest` requires an authenticated opaque `Caller`, exact `Binding`, and nonnil `WorkloadAuthorizer`. It retains the caller in signed `azp` and grants no Player privilege. The authorizer must approve the named service's exact operation. Initializer and asynchronous routes also need the retained acceptance lookup described in the separate draft.

`Exchange` verifies the authenticated caller equals the grant's `azp`, checks exact signed scope containment, and requires a nonnil live `Authorizer`. The authorizer receives the verified grant, actor, caller and binding. It must check current role, Session, resource and operation rules. The child deadline is the minimum of current time plus 30 seconds, parent grant expiry and original Player expiry.

`NarrowDelegation` additionally requires `DelegationAuthorizer` approval for every child scope and recipient. It rejects widening, changing a constrained query or body, and conversion of chat capability to general delegation. Prefix scopes match complete path segments. `exact_path` is mandatory; absent `query` means unconstrained, while an explicit empty query means exactly no query.

Synchronous authorization and forwarding use the remaining parent deadline. The adapter must bound its policy calls and downstream request context by that deadline and its dependency budget. The module rejects issuance if policy evaluation consumed the parent lifetime. It does not cancel an arbitrary policy callback; callback cancellation and HTTP context propagation remain adapter responsibilities.

Chat issuance removes administrator privilege and pins the original Player and Session. Allowed reads are exact `GET /internal/v1/sessions/{session_id}/context?player_id={sub}` and `GET /internal/v1/sessions/{session_id}/record-permissions/{sub}` with an empty query. Every exchange still checks current participant state and policy. No chat write, initializer, scoring or administrator scope is allowed.

`jti` provides an audit identifier. Verification does not consume it. Receivers must implement business idempotency, replay controls and inbox/outbox transactions for repeated writes. No short-lived grant is durable authority for deferred effects.

## Artifacts and checks

`gateway-identity-v1/schema.json` describes decoded header and claim shape for all four Gateway profiles. Schema validation alone does not verify signatures, duplicate JSON keys, lifetime relationships, escaped paths, route policy or caller credentials. Protocol limits use UTF-8 bytes; JSON Schema string lengths count characters.

`gateway-identity-v1/vectors.json` contains 43 synthetic cases and public verification keys. The generator creates temporary signing keys in memory and writes no private keys. Tests cover actor/admin typing, exact request mutation, grant expiry, caller mismatch, delegation containment, chat restrictions and workload separation. These are fixtures with stubbed permitting policy, not deployed service compatibility checks.

Run from the Gateway repository:

```text
go test -count=1 ./...
go vet ./...
python docs/contracts/gateway-identity-v1/check_vectors.py
python docs/contracts/gateway-identity-v1/check_vectors.py --export-java-crypto <temporary-tsv>
java docs/contracts/gateway-identity-v1/check_crypto_java.java <temporary-tsv>
```

Python requires `cryptography` and independently checks RSA signatures, profiles and request hashes for all 43 cases. The JDK 17 checker validates 43 RSA signatures and 114 exact-byte hashes. It does not implement Java JWT claim validation or receiver middleware. Go tests, race checks and vet passed on Windows AMD64 for the candidate changes. Native Linux binaries, Docker images, platform manifests, deployed peers, broker effects and end-to-end authorization remain unrun in this evidence set.

The package currently has no production signing configuration, JWKS publisher, routing adapter or Python/Java receiver integration. Merge and release approval must keep these limits visible. Required checks and independent peer review still apply.
