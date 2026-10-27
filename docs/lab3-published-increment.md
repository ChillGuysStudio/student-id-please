# Published Lab 3 increment on 27 October

This snapshot records tested intermediate packages under [issue 178](https://github.com/ChillGuysStudio/student-id-please/issues/178). It does not establish a cumulative grade or complete the lab. The [machine-readable inventory](releases/lab3-increment-20261027.json) records each selected source, immutable image index, native child manifest, and official publication run. CPR's corresponding private submodule pointers match those published sources.

## Selected packages

| Service | Version | Published source |
| --- | --- | --- |
| Player | 3.0.0 | `f02dd7d6e058b05e8d83d3ebc944d15ad8fa8537` |
| Session | 3.0.7 | `4fd6fcfbf3975a04bcc329051625099d96e73717` |
| Moderation | 3.0.3 | `50dd11a1ac6b158c29bce8b48101db22a6a76c0e` |
| Applicant | 3.0.3 | `828716f1c96fcaee8fadfa6484f5e2bf6778bd20` |
| Credential | 3.0.3 | `22fecb559be35efad875ee4d57327b19629952d7` |
| Server Rules | 3.0.4 | `9f553ea9431bfb260afe46618eae807fa5462277` |
| University Record | 3.0.3 | `1d67a781e9225a9f035b8423ebc9784767e8562b` |
| Gateway | 3.0.5 | `58ded57773b85b836e37bc517585f5e88a62a541` |
| Discovery | 3.0.6 | `100839c77173d992bc2f444ff4821727cd4a9c68` |

Each selected package passed official native AMD64 and ARM64 publication, anonymous manifest and revision verification, annotated release verification, and its existing moving-alias reconciliation. Existing aliases differ between services and were not normalized. Moderation's runtime images lack repository-source labels. Its annotated `image-records/<source>` record binds the actual repository, revision, native manifests, and index instead. That missing label is not claimed as verified.

## Image selection is not bootstrap configuration

[compose.published.yaml](../compose.published.yaml) selects immutable images for services already defined in the base Compose file. It also keeps Moderation's API and publisher on one source. Apply it after the deployment's required configuration files. It contains no credentials, replica identities, port changes, registration settings, or database edits.

The base Compose file does not define Discovery. Its exact image is recorded in the inventory, but this image-only overlay does not create an unconfigured Discovery process. The operator still needs a valid Lab 3 deployment with concrete replica origins, unique stable identities, existing authenticated control settings, and durable removal storage. The historical [Lab 2 preparation](development.md) is not a complete Lab 3 bootstrap procedure.

## Runtime observations

All three selected initializer flows passed normal public readiness. Non-outsider flows also passed exact retained University binding and 69-entry snapshot checks. Source fixes preserve Session-pinned IDs, original keys, reference times, and the distinction between actor-bound and retained workload authority.

The original normal decision first failed at Session's signed non-admin readiness check. Read-only persistence confirmed that no decision, key result, or scoring event had committed. After the published receiver repair, the same case, body, and original key returned `201` through real Rules evaluation. One actual scoring outbox event reached Session once, producing one processed case and a score of 10.

The same key returned the original decision after scoring cleared the current case and again after shift end. A changed body returned `409`. Normal shift end and its same-key repeat returned `200`. One real shift-end event reached Player, which recorded one consumer inbox receipt, one business receipt, and three participant progression entries. The Moderator gained 10 XP. No account creation, scenario override, injected broker message, or direct business database write supplied this result.

Discovery's fixed HTTP/1 client sent real critical-load and recovery alerts. Actual Discord messages `1564734662708953219` and `1564734687446966475` each returned `200` on readback and matched their real transitions and intended destination. A later real readiness-loss alert also passed readback as message `1564745443735371977`. Earlier failed deliveries remain unverified and were not replayed.

## Unfinished acceptance

- Discord DMs remains on its historical pointer. Its protected main branch rejected the release rebase, and its existing rules also rejected normal merge. No rule bypass or source rewrite is part of this increment. Publication and Lab 3 registration remain open under [issue 198](https://github.com/ChillGuysStudio/student-id-please/issues/198).
- Two replicas of the other seven domain services registered with distinct stable identities. All 15 registrants, including Gateway, passed readiness, renewal, and advancing probes. Twelve real public Player reads split six per receiver with identical shared state. This does not establish complete eight-domain scaling or all membership-change cases.
- Rules, Applicant, and Session caller breakers are published. Exact deployed timing, healthy-replica continuity, removal propagation, and explicit recovery across all callers remain open. Local deterministic tests alone do not establish those claims.
- Direct DMs WebSocket demonstrations, the remaining integrated demonstrations, presentation gates, and the final CPR release remain separate tasks.

Failed publisher attempts, local verifier failures, original operations, and rollback snapshots remain in protected local evidence. They are not committed because those records can contain deployment-specific data. Public issue records state the bounded results and remaining gates.
