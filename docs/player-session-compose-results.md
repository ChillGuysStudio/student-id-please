# Published Player and Session Compose results

This is Andrei's independent local AMD64 run for CPR #96 after the owner settings in CPR #117 merged. It is separate from Tirppy's 38-check report. [Sanitized local evidence](evidence/andrei-player-session-runtime.json) records image sources, container states, request IDs, and outcomes. It contains no passwords, bearer tokens, headers, private keys, or ticket URLs.

## Configuration and startup

Compose selects public Player `2.0.1` and Session `2.0.0`. Anonymous verification confirmed their version, `latest`, immutable source, and `lab-2` tags match each owner's expected index, AMD64/ARM64 children, and exact source labels. Both AMD64 images pulled anonymously without changing Docker credentials.

The existing generator now writes the confirmed receiver settings. `SERVICE_TOKENS.gateway` contains each receiver's own hop credential. Session uses the private `GATEWAY_URL`, its distinct initiating credential, and the mounted Player public key. There is no direct peer REST or original bearer fallback. Player and Session limits use their actual `MAX_CONCURRENT_TASKS` and `TASK_TIMEOUT_SECONDS` names.

The clean project started all 19 containers with zero restarts. Fourteen reported healthy. The four Java services and Moderation publisher have no Docker health checks. This run used published Moderation and DMs `2.0.2`, local gateway `b155070`, and the four Java source-image overrides listed in the evidence. It was not an all-public-image deployment or a native ARM64 runtime run.

## Critical requests

All client requests used the public gateway. All Session-to-Player business requests used the private gateway.

- Three real players registered with `201` and logged in with `200`.
- Protected Player `/me` returned `200`.
- Missing, forged, and correctly signed expired bearers returned `401 UNAUTHORIZED`.
- Friendship requests returned `201`. The real recipients accepted them with `200`, then joined the team through successful owner requests.
- Session list returned `200`, creation returned `201`, and both real juniors joined with `200`. Role assignment and Session read also returned `200`.
- Session creation exercised its real delegated Player team lookup. No mocked peer or database-edited participant was used.

An in-memory observer read the actual backend HTTP request for a successful protected Player `/me`. It reported a fresh gateway assertion, no `Authorization` header, and no original bearer in the headers or decoded gateway context. Only those boolean observations were saved. Raw traffic and credentials were not persisted or printed.

## Chat remains blocked

Lobby DMs channel listing and gateway negotiation returned `403 FORBIDDEN`. Session start returned `403 DEPENDENCY_REJECTED`. This first run did not assign University's six record permissions and still used the old local Rules adapter. These results do not establish the final start failure after correct permissions and reviewed Rules #24.

The next run uses the owner-provided shortest chat recipe to assign real permissions and trace the rejected start request. Reviewed Rules #24 and the reserved University snapshot route are separate owner work. This PR does not change either authorization policy.

No WebSocket URL was issued, so no direct connection or frame exchange was tested. No permission bypass, synthetic participant, database patch, or original Authorization forwarding was added. Full initialization, decision processing, and all-service limit demonstrations were not tested.

## PDF checklist result

- G2 runtime passed for the disclosed mixed-image Compose deployment.
- G6 source checks passed. The tested Player/Session client paths and real Session-to-Player flow passed at runtime. All application REST flows are not established.
- G7 failed at negotiation in this run. Direct connection and frames were not tested.
- G8 source configuration checks passed for Player and Session settings. This run did not repeat their owner-reported limit tests or demonstrate limits on every service.
- G10 runtime passed for the tested protected Player path, rejected credentials, and observed downstream bearer absence. This does not establish authorization for every application flow.
- G5 and G9 gateway publication were not tested here. Player/Session anonymous manifests and image pulls passed; native workflow provenance remains separate owner evidence.
- G1, G3, and G4 are not applicable to this configuration change.

The initial disposable project and volumes were removed after collecting this evidence. A continuing isolated run for the start dependency is separate from this saved result.
