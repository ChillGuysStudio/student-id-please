# Disposable Lab 2 runtime results

> Historical source-build run. The later public-image activation and direct chat observation is [lab2-live-snapshot.md](lab2-live-snapshot.md). The failures below describe this older disposable run, not the current live stack.

This run tests CPR #96 on native Linux AMD64. It uses the merged gateway runtime from [gateway PR #10](https://github.com/ChillGuysStudio/gateway-service/pull/10), four isolated Java source snapshots, and public Moderation and DMs `2.0.2` images. Player and Session still use their legacy public images. The [sanitized results](lab2-runtime.json) record exact source references, image digests, container states, and HTTP outcomes. They contain no credentials, keys, tokens, or tickets.

## Startup

The fresh disposable project started all 19 containers with zero restarts. Fourteen containers reported healthy. Applicant, Credential, Rules, University, and the Moderation publisher have no Docker health check. The four Java startup logs confirmed application startup, and their protected catalogue reads subsequently reached live APIs.

The first Java startup attempt exposed two constructor failures. Applicant required its broker username to map to `applicant`. Credential required its username to map to `credential`. `scripts/start_broker.sh` creates only those two accounts on the existing broker. No exchanges, queues, or message protocols changed. A clean restart with fresh disposable volumes passed.

The source snapshots and the merged gateway built natively on AMD64. The Java Dockerfiles skip unit tests. These builds and this runtime are not native ARM64 runtime evidence. Moderation and DMs `2.0.2` pulled anonymously on AMD64, and their OCI source labels match the CPR pointers. Their native publication evidence is separate from this run.

## HTTP results

All client domain requests used the public gateway. No test restored direct peer URLs or forwarded the original Player bearer downstream.

| Request | Result |
| --- | --- |
| Gateway health | `200` |
| Protected Player request without bearer | `401 UNAUTHORIZED` |
| Player registration through gateway | `201` |
| Player login through gateway | `200` |
| Protected Player `/api/v1/players/me` | `401 UNAUTHENTICATED` |
| Protected Player `POST /api/v1/friendships` with a newly registered recipient | `401 UNAUTHENTICATED` |
| Protected Session list | `401 UNAUTHENTICATED` |
| Rules actor request for a missing resource | `404 NOT_FOUND` |
| DMs channel lookup with legacy Session | `403 FORBIDDEN` |
| Realtime negotiation with legacy Session | `403 FORBIDDEN` |

Controlled development admin tokens signed with the fresh development Player key produced `200` catalogue responses from Rules, Applicant, Credential, University, and Moderation. These responses test gateway and receiver proofs. They do not prove Player administrator integration or a working gameplay flow.

A private internal Rules request without delegation returned `401 UNAUTHORIZED`. A scoped development delegation reached the current Rules receiver but returned `401 UNAUTHENTICATED`. `GatewayAccess` treats `/internal/v1/rule-versions/current` as a workload-proof route. The gateway's current route table treats it as delegated actor authority. That mismatch needs owner coordination. Compose does not change either authorization policy.

## Remaining failures

[Player and Session publication and configuration](https://github.com/ChillGuysStudio/student-id-please/issues/88) still block protected Player requests and Session reads. Their receiver setting names are not confirmed here. The generator leaves those receiver settings absent instead of guessing names from legacy source.

No direct WebSocket URL was issued in this real-peer run because Session checks failed. No direct chat frames were exchanged. Initialization and other routes marked `Unagreed` remain disabled. This run does not establish full Lab 2 acceptance, public gateway publication, Java image publication, or native ARM64 runtime behavior.

## Commands used

The source override contains only image selections and pull policies. It lives under ignored `.local/lab2/`, outside committed deployment settings. Private source snapshots stayed in `/tmp`, not in CPR service folders.

```sh
python3 scripts/prepare_lab2.py --gateway-image student-id-gateway:andrei-compose --gateway-port 18080 --dms-port 18009
docker compose -p andrei-lab2-disposable -f compose.yaml -f .local/lab2/compose-source.yaml config --quiet
docker compose -p andrei-lab2-disposable -f compose.yaml -f .local/lab2/compose-source.yaml up -d --wait --wait-timeout 120
docker compose -p andrei-lab2-disposable -f compose.yaml -f .local/lab2/compose-source.yaml ps --format json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
```

Temporary HTTP probes held newly registered passwords and tokens in memory. They saved only status and error codes. The internal probe ran from the DMs container to `http://gateway:8083`. The disposable project and its volumes were removed after collecting the results.
