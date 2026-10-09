# Player and Session runtime wiring

Owner handoff for CPR issues [#88](https://github.com/ChillGuysStudio/student-id-please/issues/88) and [#77](https://github.com/ChillGuysStudio/student-id-please/issues/77), checked on 2026-10-09. Andrei owns Compose wiring in [#96](https://github.com/ChillGuysStudio/student-id-please/issues/96), Adrian owns gateway routes in [#104](https://github.com/ChillGuysStudio/student-id-please/issues/104), and Max owns Rules and University alignment in [#94](https://github.com/ChillGuysStudio/student-id-please/issues/94).

The [Session-start follow-up](player-session-start-followup.md) records the Gateway #15 rerun, focused permission-delegation fix #16, independently reproduced public University permission failures, and exact dispatch-to-acceptance mapping for peer adapters. CPR #118 has merged the confirmed Player/Session deployment settings. Those later results do not establish Session activation or direct chat frames.

## Source and release status

| Service | Delivered source | Release |
| --- | --- | --- |
| Player | Released main and synchronized dev `cf0f7846238400ef44da4e59e6c350728aa53dfe` | [Release PR #14](https://github.com/Tirppy/student-id-player-service/pull/14) merged by rebase, [v2.0.1](https://github.com/Tirppy/student-id-player-service/releases/tag/v2.0.1), includes [deadline fix #13](https://github.com/Tirppy/student-id-player-service/pull/13) |
| Session | Released main and synchronized dev `5e59c041daee541e1697d5e745c6e26bf52e79a1`, includes [context fix #13](https://github.com/Tirppy/student-id-session-service/pull/13) | [Release PR #10](https://github.com/Tirppy/student-id-session-service/pull/10) merged by rebase, [v2.0.0](https://github.com/Tirppy/student-id-session-service/releases/tag/v2.0.0) |

Both dev histories were repaired with explicit owner authorization and preserved backups. Main protections remain intact. Sync App `5249602` alone has the permanent dev synchronization bypass. All four required Actions secret names exist. Both publication workflows and dev synchronizations succeeded. This document contains no secret values. Real gateway acceptance is separate from source and publication checks.

## Published image evidence

Anonymous registry reads verified both exact source labels and the following public indices and children. Each numeric version below, immutable `sha-<full main SHA>`, `latest` and `lab-2` resolve to the same index for that service. Player's earlier `v2.0.0` remains immutable.

| Image | Index digest | AMD64 child | ARM64 child |
| --- | --- | --- | --- |
| `tirppy/student-id-player-service:2.0.1` | `sha256:79296935ebbffd55cf1db0da10ab8509bae145c07b842fbe5f6b606c64b9fa6b` | `sha256:a650b221e454182d24d2033abc19de2d61b36401f43f53aeb3edc86f47d903db` | `sha256:6451e4a41e5091f1b25df7b2405d9650fd69022c33982aa0e74c9b09bbd18076` |
| `tirppy/student-id-session-service:2.0.0` | `sha256:d1769b4a81845af085dbbce3d104b728e3264f56b06435df31ed9593988a492c` | `sha256:3835183615f1f853fba3d4c4d32e43f7b81eca44bea98429fbd2adcd7b7e979a` | `sha256:266f820c78f411992c67762347b6ddd188b4919bb45431b86816655a249051e5` |

[Player publication run](https://github.com/Tirppy/student-id-player-service/actions/runs/37925732240) and [Session publication run](https://github.com/Tirppy/student-id-session-service/actions/runs/37923731642) passed native builds and container startup/readiness on separate `ubuntu-latest` AMD64 and `ubuntu-24.04-arm` ARM64 runners. Logs identify `x86_64` and `aarch64` respectively. Both then assembled, published and reconciled their indices. These private run links require source access; public manifests provide independently readable platform and source evidence. Dev sync ran under the installed App and left dev equal to main in both repositories.

```sh
docker pull tirppy/student-id-player-service:2.0.1
docker pull tirppy/student-id-session-service:2.0.0
docker buildx imagetools inspect tirppy/student-id-player-service:2.0.1
docker buildx imagetools inspect tirppy/student-id-session-service:2.0.0
```

## Exact receiver settings

These are the settings implemented by the owned images. The generic gateway environment names are different from the Player and Session receiver names. In particular, setting only `HTTP_MAX_CONCURRENT_TASKS` and `HTTP_TASK_TIMEOUT_SECONDS` does not configure these two services.

| Environment name | Player | Session |
| --- | --- | --- |
| `AUTH_MODE` | `gateway` | `gateway` |
| `GATEWAY_PUBLIC_KEY_FILE` | `/keys/gateway-public.pem` | `/keys/gateway-public.pem` |
| `GATEWAY_JWKS_URL` | Unset when using the mounted file | Unset when using the mounted file |
| `GATEWAY_KEY_ID` | `gateway-v1` | `gateway-v1` |
| `GATEWAY_ASSERTION_ISSUER` | `student-id-gateway` | `student-id-gateway` |
| `GATEWAY_ASSERTION_AUDIENCE` | `student-id-player-service` | `student-id-session-service` |
| `SERVICE_TOKENS` | `{"gateway":"<player receiver hop credential>"}` | `{"gateway":"<session receiver hop credential>"}` |
| `GATEWAY_ASSERTION_SECRET` | Empty | Empty |
| `DATABASE_URL` | PostgreSQL URL for the Player database | PostgreSQL URL for the Session database |
| `MAX_CONCURRENT_TASKS` | Positive integer, default `64`; set `100` to match CPR | Positive integer, default `64`; set `100` to match CPR |
| `TASK_TIMEOUT_SECONDS` | Positive seconds, default `30` | Positive seconds, default `30` |
| Container HTTP port | `8001` | `8002` |

Mount the public key read-only and readable by container UID `10001`. Configure exactly one gateway key source. Generate deployment keys outside Git and share only their public verification material. The gateway and Player private keys stay in separate persistent storage.

Player additionally needs `JWT_PRIVATE_KEY_PATH=/keys/player-private.pem`, `JWT_ISSUER=student-id-please` and `JWT_AUDIENCE=student-id-players`. Preserve this private key across recreations. Its public verification endpoint is `/.well-known/jwks.json`, with signing key ID `player-v1`. The gateway receives the matching public PEM and key ID, never the private key.

Session additionally needs:

```dotenv
GATEWAY_URL=http://gateway:8083
GATEWAY_SERVICE_TOKEN=<Session initiating service credential>
PLAYER_MODE=http
EXTERNAL_SERVICES_MODE=http
JWT_PUBLIC_KEY_PATH=/keys/player-public.pem
JWT_ISSUER=student-id-please
JWT_AUDIENCE=student-id-players
```

`PLAYER_JWKS_URL` is legacy bearer verification configuration; gateway mode verifies gateway proofs instead. Leave it unset when using the mounted `JWT_PUBLIC_KEY_PATH`. This avoids a direct REST trust bootstrap dependency. In gateway mode Session sends every peer business REST request to `GATEWAY_URL`, with its own `GATEWAY_SERVICE_TOKEN`. Direct `PLAYER_URL`, `RULES_URL`, `UNIVERSITY_RECORD_URL`, `APPLICANT_URL` and `CREDENTIAL_URL` are standalone compatibility settings and do not route gateway-mode peer calls.

Redis and the existing RabbitMQ paths remain separate infrastructure connections. RabbitMQ is Lab 4 architecture scope; its existing decision/progression dependency is disclosed separately from Lab 2 REST acceptance.

## Matching gateway configuration

The assembled gateway at `6a1a3b485e9e1ce153ef53f4eb371647cd160ad3` reads these exact JSON maps. This excerpt must be combined with all other receivers because startup requires all eight entries.

```json
{
  "GATEWAY_RECEIVERS": {
    "player": {"Target": "player", "Audience": "student-id-player-service", "HopToken": "<player receiver hop credential>"},
    "session": {"Target": "session", "Audience": "student-id-session-service", "HopToken": "<session receiver hop credential>"}
  },
  "GATEWAY_CALLER_NAMES": {"player": "player", "session": "session"},
  "GATEWAY_SERVICE_TOKENS": {"player": "<Player initiating service credential>", "session": "<Session initiating service credential>"},
  "GATEWAY_PLAYER_URL": "http://player:8001",
  "GATEWAY_SESSION_URL": "http://session:8002",
  "GATEWAY_KEY_ID": "gateway-v1",
  "GATEWAY_SIGNING_KEY_FILE": "/keys/gateway-private.pem",
  "GATEWAY_PLAYER_KEY_ID": "player-v1",
  "GATEWAY_PLAYER_PUBLIC_KEY_FILE": "/keys/player-public.pem"
}
```

The map values are JSON encoded inside environment variables. `SERVICE_TOKENS.gateway` must equal the corresponding receiver's `HopToken`. The Session initiating credential must equal `GATEWAY_SERVICE_TOKENS.session`, and must differ from every receiver hop credential. `GATEWAY_HOP_TOKENS` is not the assembled runtime's configuration interface.

Canonical initiating callers are `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation` and `discord-dms`. University routing ownership and caller are `university_record`; its receiver target is `university-record`, and its audience is `student-id-university-record-service`. Configure that distinction explicitly in the two maps.

Only publish the gateway public listener. Keep the internal listener `:8083` and all domain REST ports on the Compose network with no host port mappings. Direct WebSocket delivery is a separate DMs endpoint.

## Identity contract

The receiver trusts RS256 assertions from `student-id-gateway` under the configured key ID and exact receiver audience. Actor assertions use `typ=gateway-request+jwt`; workload assertions use `typ=gateway-workload+jwt`. Both bind the exact HTTP method, escaped path, raw query bytes, body bytes and idempotency key. Assertions last at most 30 seconds and actor assertions never extend the original actor expiry.

The hop authenticates `X-Service-Name: gateway` and the receiver's own `X-Service-Token`. Signed `azp` identifies the initiating service. Receivers reject forwarded `Authorization`; arbitrary actor/admin headers grant nothing. Resource, participation and role checks still execute at the receiver. Explicit anonymous register/login/refresh/logout routes receive anonymous gateway proofs.

Session sends `X-Service-Name: session`, its initiating credential and, for synchronous actor calls, the separate `X-Gateway-Delegation` grant to the internal gateway. The gateway exchanges that scoped grant for a fresh receiver-bound assertion. Session never forwards an inbound receiver assertion or original Player bearer token. Workload-only readiness polls carry no actor delegation.

## Peer endpoints and decisions

| Endpoint | Required authority | Receiver behavior and wiring status |
| --- | --- | --- |
| `GET /internal/v1/sessions/{sid}/context?player_id={actor}` | Receiver-bound actor proof; initiating peer caller | Query actor must match verified subject and be a Session participant. Allowed peers are Applicant, Credential, Rules, University, Moderation and DMs. Merged Session #13 also permits the gateway's own policy lookup in gateway mode. Workload identity cannot read actor context. Existing internal gateway route is delegated. |
| `GET /api/v1/sessions/{sid}/cases/{cid}/status` | Receiver-bound actor proof | Actor must participate and case must belong to that Session. Session polls initializer readiness as Session workload. Gateway currently reserves the internal route as `Unagreed` for Moderation only. Owner proposal is delegated access for `rules` and `moderation`, exact Session/case scopes, with Rules retaining its moderator/resource checks. Adrian must confirm and wire the route and the grant passed through Moderation to Rules. |
| `GET /internal/v1/{applicant,credential,university-record}/cases/{cid}/status` | Session initiating workload proof | Both foreground and background polls use workload identity. Initializers must restrict reads to retained accepted work. Gateway routes remain `Unagreed`; Adrian and initializer owners must agree this workload route. |
| `GET /internal/v1/sessions/{sid}/accepted-attempts/{attempt_id}` | Authenticated named workload proof | Session implementation exists. Wrong/missing Session-attempt pair returns 404, disallowed caller returns 403. Gateway has no route yet. Adrian must add an agreed workload route before adapters can reach it through the internal gateway. |

The last three rows are proposed peer wiring, not a claim of peer agreement. Review requests on this packet ask the owners to confirm those decisions. Player/context and Session lobby reads do not require a new retained-authority protocol.

## Existing retained acceptance

Session commits acceptance with dispatch intent before calling the initializer. It pins `attempt_id`, `session_id`, `team_id`, actor ID and role, original token ID and expiry, accepted time, original idempotency key, normalized request hash, initializer, case UUID, rules, reference time, snapshot, allowed callers and allowed effects. No compact Player JWT is durable authority.

The lookup returns `acceptance` plus current `lifecycle`, including Session and attempt status, check time and `effects_allowed`. Completed, ended, failed, superseded and noncurrent attempts cannot authorize new effects. Existing pending-case end restrictions remain. Accepted asynchronous work can outlive transient Player expiry within its retained scope; this never grants fresh synchronous actor authority.

Session allocates the case UUID before dispatch and rejects an initializer response that changes it. Same-key replay retains the attempt and case. Changed input conflicts. The normalized hash is SHA256 of the validated request model serialized as sorted compact Python JSON with default ASCII escaping. It is distinct from the gateway's hash of raw request bytes.

Snapshot acceptance allows caller `university_record` and effect `snapshot_create`. Case acceptance lists `applicant`, `credential`, `university_record` and effects `case_initialize`, `subject_reserve`, `case_project`; the pinned initializer narrows which service may initialize. Consumers must enforce the operation and initializer, not treat the caller list as permission for every effect.

University owns once-only subject allocation. Session returns `reservation: null` and does not claim a settled subject reservation protocol. Applicant/Credential's concrete retained-authority adapter and University's allocation semantics still require owner agreement. The gateway's Session acceptance schema remains a proposal where it differs from this existing implementation.

## Evidence and remaining runtime checks

Current release CI passed Player 76 and Session 91 tests. Session #13's four focused cases passed, followed by its full required CI. These include mismatched actor, nonmember denial, workload rejection on actor context and foreground readiness without delegation. Earlier Docker receiver tests used actual Go assertion issuance and real owned databases, with mocked external Session peers. They did not run the assembled gateway.

The pinned legacy Player image accepts its raw bearer but returns `401 UNAUTHENTICATED` for gateway actor proofs on `/players/me` and friendships. The rebuilt receiver accepts the same Go profile. Replacing the legacy image and using the exact settings above is required; restoring raw bearer forwarding would violate the contract.

The actual PostgreSQL-lock run on Player `2.0.0` found its async authentication dependency performed a blocking database lookup. This stalled the event loop and produced the gateway's later `DEPENDENCY_TIMEOUT` instead of Player's service timeout/capacity response. Player #13 moves that lookup to the worker pool, preserves authorization and capacity accounting, and adds a focused regression. The fix is published in `2.0.1`.

Current owned capacity code is `TASK_LIMIT_REACHED`; CPR documents `TASK_LIMIT_EXCEEDED`, an error-name alignment question for runtime owners. HTTP statuses are 503 for capacity and 504 for timeout.

### Actual assembled-gateway run

The final run passed **38 checks** through assembled gateway `6a1a3b485e9e1ce153ef53f4eb371647cd160ad3`, public Player `2.0.1`, public Session `2.0.0`, and real dedicated PostgreSQL databases. [Sanitized evidence](evidence/player-session-lab2.json) contains source/index/child references, native workflow summaries and request IDs.

- Anonymous registration/login/refresh and protected `/players/me` passed.
- Forged and expired Player bearers were rejected at the gateway.
- Friendships, recipient-only acceptance and team membership passed. Spoofed actor/admin headers did not bypass permissions.
- Session creation and joins performed actual Session-to-internal-gateway-to-Player delegated calls. Session list/read passed, and a nonparticipant was denied.
- The gateway's own Session context policy passed before reaching the intentionally unavailable DMs peer. That request returned expected `502 DEPENDENCY_UNAVAILABLE`; it is not evidence of successful chat history, negotiation or frames.
- With one task slot and a one-second receiver deadline, actual PostgreSQL table locks produced each service's `503 TASK_LIMIT_REACHED` and `504 TASK_TIMEOUT`. Capacity stayed occupied until the timed-out worker completed. Both services then returned 200 again.
- Only the gateway public listener was bound to localhost. Public access to the internal Session path was denied. Receiver ports and the gateway internal listener were not published.

The local Docker registry proxy rejected ordinary pulls even with isolated anonymous configuration. The verifier instead downloaded every original public child manifest, config and compressed layer anonymously, checked SHA256, and loaded a Docker archive. Loaded source labels, architecture and layer diff IDs matched the public config. No user Docker credentials were changed. Both native CI platforms separately started the published children through the normal release workflow.

Commands in the delivery workspace:

```powershell
.\.venv-lab2\Scripts\python.exe tmp\verify_owned_publication.py
.\.venv-lab2\Scripts\python.exe tmp\capture_owned_workflows.py
.\.venv-lab2\Scripts\python.exe docker-project-check\verify_real_gateway.py
```

Source checks are `python -m pytest -q`, `python -m ruff check app tests .github/scripts`, and `python .github/scripts/check_docs.py` in each owned repository. The runtime helper uses ignored synthetic credentials and disposable containers. Its gateway was locally compiled from the pinned source; this run does not certify a published Gateway image or native Gateway ARM64 execution.

Full gameplay and Lab 2 acceptance remain open until real peer images, route policies, delegation, receiver settings and required error/recovery checks agree. Source success alone does not close #77 or #88.
