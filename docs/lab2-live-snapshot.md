# Lab 2 live Gateway, snapshot, and direct chat

This is the **2026-10-09 live Compose observation**, not the older disposable-source run in [lab2-runtime.md](lab2-runtime.md). The original CPR stack `cpr-lab2-live` had 19 running containers (14 health checks healthy), with zero restarts of the paired services.

| Public AMD64 image running | Exact source label |
| --- | --- |
| `maxnoragami/gateway-service:2.0.2` | `e7c6f68c7db8daffac44b1641d7c867614c4644e` |
| `maxnoragami/university-record-service:2.0.3` | `dbd0f860db21801ca5afcec688db8752b1d64667` |
| `tirppy/student-id-session-service:2.0.0` | `5e59c041daee541e1697d5e745c6e26bf52e79a1` |
| `sentientmoss/pad-discord-dms-service:2.0.2` | `4ccd6f329341ba714f701563fe75021704bebb46` |

The first real Session start reached University and received `409 DEPENDENCY_REJECTED`: no current academic-year reference covered `reference_at`. A disposable operator was temporarily granted authority using **Player's operator CLI**. It created one academic year through the **public Gateway's admin REST endpoint**, confirmed the read-back through Gateway, and had its operator authority revoked. This was legitimate fixture provisioning, not a fake receiver, modified Session context or authorization bypass. The failed attempt's stored result was not rewritten; a **fresh real Session** supplied the later passing start.

The fresh run registered and logged in three real players through Gateway, made two accepted friendships and a team, created/joined a lobby, set owner/Moderator and two junior roles, assigned six University record kinds and read each participant's permissions. Session start then returned **200 `active`** with a pinned Rules version and University snapshot. Two real participants read DMs channels through the Gateway; separate negotiation requests returned 200. Both then connected directly to DMs WebSockets, and one real message produced the sender's `message.ack` and the recipient's matching `message.created` (same persisted message ID). The Gateway did not relay those frames.

The paired image publication runs were green and anonymous DockerHub inspection verified `2.0.2`/`2.0.3`, `latest`, source-SHA tags and Linux AMD64/ARM64 manifests with exact source labels. Public images—not local test builds—were running in the passing flow. The sanitized, local-only probe report is `.local/activation-chat-probe/sanitized-results.json`; never commit its adjacent private credentials or WebSocket tickets. Independent packet attribution for DMs's internal Session callback was **not** collected in that passing run. Prior protected Player backend observations established that the original bearer was stripped and a fresh Gateway assertion was used; this run did not re-establish packet attribution.

The [guided Postman collection](../postman/LAB2-GUIDED.md) demonstrates the real identity/lobby/permission path and Gateway's 100 concurrent-task cap with 503 rejection and 200 recovery. Its HTML reporter omits credentials and private HTTP fields. It does not simulate activation or WebSocket frames. Deployed timeout and concurrency proofs for **all nine** services, accepted case/reservation behavior, professor access, and the complete cumulative Lab 2 checklist remain separate checks; do not infer them from this successful activation and chat run.
