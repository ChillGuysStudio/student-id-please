# Published package updates on 28 October

Four later packages extend the [27 October increment](lab3-published-increment.md). The [update inventory](releases/lab3-package-updates-20261028.json) records their exact sources, immutable images, native manifests, and official publication runs. Apply its four rows over the earlier inventory when looking up the current selection. The earlier CPR `v3.0.0` snapshot remains unchanged.

| Service | Version | Published source | Verification |
| --- | --- | --- | --- |
| Session | 3.0.8 | `1f78653e65c7bf7ffc1578d48c99cc356bbed539` | 286 PostgreSQL tests, 100 subtests, 33 repository fixtures, zero skips |
| Credential | 3.0.4 | `d576a04b0a5ef92cab156e1aa8b7b32d66af6fa3` | 177 Java tests, nine real isolated transport cases, 78 repository fixtures, zero skips |
| University Record | 3.0.4 | `594c267348dd971765cff98ec465f8d81cccd56c` | Exact-head CI passed 157 Java tests and 41 repository fixtures, zero skips |
| Moderation | 3.0.4 | `b8dfb2838f6fb9027aff76ec49c863244845a438` | 260 local PostgreSQL tests with zero skips; CI passed 255 tests with five explicit PostgreSQL skips; 85 repository fixtures |

The Gateway, Discovery, Player, Applicant, and Server Rules selections remain as recorded in the previous inventory. [compose.published.yaml](../compose.published.yaml) selects the corresponding immutable images for existing base Compose services. It remains an image-only overlay, not a complete Lab 3 bootstrap procedure.

## Credential 3.0.5 and DMs 3.0.3

Two later releases supersede the Credential 3.0.4 row above and the unchanged DMs pointer. The [release inventory](releases/lab3-credential-dms-releases-20261028.json) records both.

| Service | Version | Published source | Release |
| --- | --- | --- | --- |
| Credential | 3.0.5 | `16098bb786be189746aca7b65d5b3591e8373b35` | `mcittkmims/credential-service` pull request 46, fixing issue 45 |
| Discord DMs | 3.0.3 | `440d25b7dc7098c335a03c82fdff077aa41c12e1` | `andyp1xe1/pad-discord-dms-service` pull request 34, fixing issue 33 |

CPR's submodule pointers and [compose.published.yaml](../compose.published.yaml) now select these sources and images for both slots. Anonymous registry readback confirmed that each image's AMD64 and ARM64 config revision label equals its source. Credential also carries the repository-source label. DMs does not, and none is claimed. Both releases run on both live slots, and Discovery showed all seventeen registrants ready. The source repositories are private, so their publication run IDs are not recorded.

## Physical completion and delivery

Session and Moderation now capture actual body completion or terminal transport errors before response cleanup and recorder locking. Anchored UTC evidence and per-generation completion-time high-water marks preserve the inclusive failure window under out-of-order recording. A completed response does not become a new timeout because later cleanup crosses a deadline. Cancellation before physical completion stays suppressed.

Each of the four packages passed official native publication, anonymous source verification, its existing alias reconciliation, an annotated release, and automatic dev synchronization. Moderation still lacks repository-source image labels. Its exact revision labels and annotated immutable repository/source/index record are verified instead. No absent label is claimed as present.

Both concrete replicas of each service now run the recorded images. Their image-only rollouts preserved application environments, credentials, mounts, data, and stable slot IDs. Where three real cold-boot connection failures caused removal, the operator verified the actual cause, cooldown, current lease, and fresh ready observations before one normal re-entry call. Readiness did not automatically clear a removal.

## Restart and healthy-peer evidence

A controlled shutdown retained all 27 original containers. Restart verification checked their images, effective environments, and mounts before starting the same containers in dependency order. The original University removal survived Discovery's restart and remained excluded while its application was ready. Normal operator recovery followed fresh observations. No database restore, tombstone edit, identity rotation, or local image build supplied that result.

A separate Gateway-to-Credential demonstration used only reads of an existing case. Three distinct real connection errors completed within 0.121 seconds under `T = 2 seconds` and `W = 7 seconds`. Gateway tripped once and removed that replica's exact registration. The healthy peer continued serving identical `200` reads. A real Discovery restart preserved the removal's registration and timestamp, while the other fourteen registrants renewed and advanced probes.

Restarting the failed Credential replica did not reactivate it. Its new boot remained removed while ready and renewing. One normal operator call used the original recovery operation after the documented conditions passed. The fresh generation renewed, all fifteen registrants became ready, and eight later reads returned `200`. This proves that concrete failure path. Exact window boundaries, expiry-separated errors, and every domain caller remain separate acceptance checks.

## Bounded DMs runtime is not an official package release

The already-public DMs native image for source `474eab2233dd85641f2aedac518661a24b1edf25` passed anonymous native revision and immutable publication-record verification. The operator used it for bounded checks without claiming the blocked version or moving channels were reconciled.

Two DMs replicas now advertise separate private HTTP origins and local WebSocket ports. All seventeen registrants, including Gateway and two replicas of every domain, passed readiness, lease renewal, and advancing probes. Existing DMs business credentials, database, Redis settings, and primary port remain unchanged. The second local-only port is `18009`. The existing local and insecure WebSocket flags are enabled for this laptop demonstration, not for a remote secure deployment.

The seventeen-registrant load check reached 100 active Gateway tasks, returned `503 TASK_LIMIT_EXCEEDED` for excess admission, and recovered to zero. All registrations preserved their generations and advanced leases and probes. Actual critical and recovery Discord messages `1564905024876970017` and `1564905047026831437` each returned `200` on readback and matched their event IDs, service, instance, observed time, intended destination, and disabled mentions. The verifier sent no message and replayed no historical alert.

The canonical DMs pointer and image overlay remain unchanged because official release reconciliation is still blocked. The later DMs caller-breaker task is merged into private `dev` but is not part of this older native runtime image.

The first actual two-replica negotiation check found that both successful negotiations returned the old static port `8009`. It stopped before either socket connected or any message was sent. Gateway's instance-bound negotiation repair and actual direct frame, replay, and reconnect demonstrations remain open under [issue 163](https://github.com/ChillGuysStudio/student-id-please/issues/163). Registered replicas alone do not prove correct negotiation.

This package increment does not establish full Lab 3 completion or a cumulative grade. DMs' protected release history, remaining caller-breaker runtime cases, direct chat acceptance, and presentation gates remain open.
