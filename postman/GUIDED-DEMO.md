# Guided demo in Postman

## Import and connect

1. Open Postman and import `postman/guided-demo.postman_collection.json` and `postman/guided-demo.postman_environment.json`.
2. Select **Local guided demo (do not share after running)** in the environment selector.
3. Set `gateway_url` to the reachable **public Gateway** address. On the machine running Compose, it is `http://127.0.0.1:8080`. If Postman is on another computer, use a secure tunnel to that port and enter the forwarded local URL. Do not target individual service ports or Gateway's private listener.
4. Expand folder **A** and click **01 — Gateway health** → **Send**. This creates three fresh disposable identities in your selected Postman environment. Continue through **02–27**, selecting each request and clicking **Send** in numeric order. Requests **30–70** follow the overload steps. Each request checks its response in the **Test Results** tab; stop if one fails. Login requests **03, 05 and 07** save each access token automatically, and **03** also saves player 0's refresh token. Nothing needs to be copied between requests.
5. Folder **A** shows valid login, protected reads and rejection of absent/forged credentials. Folder **B** creates real friendships, a team and a three-person Session lobby. Folder **C** assigns and verifies University record permissions for the two juniors.

## Show 100 simultaneous tasks and overload

6. Select **28 — Observe the 101st concurrent request (503)** in Postman and keep its **Send** button ready. From a *separate terminal on the same Compose host*, run:

   ```sh
   python3 postman/overload.py
   ```

   The helper targets `127.0.0.1:8080`. Pass `--port N` or set `GATEWAY_PORT` for another Gateway port. When the terminal prints **READY**, click **Send** in Postman promptly. The test requires HTTP **503 `TASK_LIMIT_EXCEEDED`**, a matching request ID and `Retry-After: 1`. The helper opens 100 bounded, incomplete requests to occupy the Gateway's 100 task slots. They contain no credentials, cannot complete a registration and are closed automatically. It verifies overload itself before showing READY. This is **100 concurrent tasks**, not a rate-per-second test. If you miss the short window, rerun the helper and repeat 28.
7. When the helper prints **DONE**, click **29 — Verify protected reads recover after the helper exits**. This must return **200** for the logged-in player again.

## Run a shift and the account lifecycle

8. Folder **E** starts the Session, opens one case, records a decision through Moderation and ends the shift. Starting needs a published rule version and a valid University catalog. Request **33** returns **202** while the record services initialize the case. Requests **34** and **37** poll: in Newman they repeat about once per second, up to 30 times, until the case is ready and the decision is scored. When you send them manually, an empty **Test Results** tab means the work is still pending, so send again. Requests **40–43** create, delete and confirm the removal of a separate lobby; a started or ended Session cannot be deleted.
9. Folder **F** checks the public signing keys, refreshes player 0's tokens, renames player 0, reads profiles and lists friendships. It then creates and removes a separate friendship and team, so the shared demo team and friendships stay intact. Request **65** logs player 0 out, and **66** checks that its refresh token now returns **401 `INVALID_REFRESH`**. The access token from **45** stays valid until it expires, because logout revokes only the refresh token family.
10. Folder **G** checks that `GET /api/v1/admin/logs` (67–68), `GET /api/v1/admin/broker/topics` (69–70), and `GET /api/v1/admin/broker/dead-letters` (71–72) refuse an anonymous client with **401** and an ordinary player with **403**. The demo players are not administrators. An administrator downloads the archive with `curl`, passing the token from a shell variable so it does not appear in the command:

    ```sh
    curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" -o logs.tar.gz \
      'http://127.0.0.1:8080/api/v1/admin/logs?service=gateway&service=applicant'
    tar -xzOf logs.tar.gz manifest.json
    ```

    The archive holds `<service>/<instance_id>.jsonl` files and `manifest.json`, which reports each instance as `ok`, `truncated`, `unavailable`, or `error`. The [logging contract](../docs/contracts/logging.md) defines the parameters and limits.

The collection does not include direct WebSocket frames. The helper does not configure or restart any service. Keep the populated Postman environment private: it contains the generated players' passwords and tokens. Do not export or commit it after running.

## Follow a request through the services

Every guided request enters at Gateway, which sends it to the Message Broker. The Broker dispatches it to the owning service and writes a `dispatch` record per call. Work that service does for the request, and the events it publishes, pass through the Broker too, so the Broker log shows the path.

To follow one request:

1. Copy the `X-Request-ID` header from the response in Postman.
2. From the Compose directory, read the Broker records for that ID:

   ```sh
   docker compose logs --no-log-prefix message-broker | grep <request-id>
   ```

   Each `dispatch` record names the `caller`, the `target_service` and `target_instance_id`, the `method` and `route` (or `rpc` for a gRPC call), the `status`, the `outcome`, and the `attempt`. A request that Gateway refuses itself, such as a 401 or 403, leaves no Broker record.
3. The receiving service logs the work it does for the call under its own `request_id`. To follow its peer calls, find its `http_request` record for the same route on the `target_instance_id`, then grep the Broker log for that ID:

   ```sh
   docker compose logs --no-log-prefix session | grep <target_instance_id> | grep '"http_request"' | grep '/cases"' | tail -1
   docker compose logs --no-log-prefix message-broker | grep <that-request-id>
   ```

4. Events appear as an `event_published` record followed by one `delivery` record per subscriber, with the `event_type` and `target_service`. Each event has its own `request_id`, so match it by time and event type.

The table lists what each request triggers. Peer calls read `caller` to `target_service` and the RPC name. Each row was checked by sending the request once and reading the Broker's `dispatch` records. Requests that share a route with a listed one trigger the same path.

| Requests | Gateway to Broker to | Peer calls and events that follow |
| --- | --- | --- |
| 02–07 (register, login) | Player | None |
| 08, 44, 45 | Player (`players/me`, `jwks.json`, `auth/refresh`) | None |
| 11–17 | Player (teams, friendships, members) | None |
| 18, 23, 37 | Session (list, read) | None |
| 19 | Session (`POST /sessions`) | Session to Player `GetTeam`, `GetPlayer` |
| 20, 21 | Session (`POST /sessions/{id}/participants`) | Session to Player `GetTeam`, `GetPlayer` |
| 22 | Session (`PUT /sessions/{id}/roles`) | None |
| 24 | Session `GetSessionContext` check, then University Record (`PUT .../record-permissions`) | University Record to Session `GetSessionContext` |
| 25–27 | Session `GetSessionContext` check, then University Record (`GET .../record-permissions/me`) | University Record to Session `GetSessionContext` |
| 31 | Session `GetSessionContext` check, then Session (`POST .../start`) | Session to Player `GetTeam`, `GetPlayer`; Session to University Record `GetRecordPermission` and `CreateSnapshot`; Session to Rules `GetCurrentRuleSet`; University Record to Session `GetSessionContext`, `GetAcceptedAttempt` |
| 33 | Session (`POST .../cases`) | Session to Applicant `StartCase`; Applicant to University Record `GetRetainedSnapshot`; Applicant and University Record to Session `GetAcceptedAttempt`. Then `CaseInitialized` is published and delivered to Applicant, University Record, and Credential, and Credential calls University Record `GetIdentity`, `GetRetainedSnapshot`. |
| 34 | Session (`GET .../cases/{id}/status`) | Session to Applicant, Credential, and University Record `GetCaseState`. Until `CaseInitialized` reaches Credential and University Record, they answer `404` (outcome `rejected`) and the case stays pending. |
| 36 | Session `GetSessionContext` check (twice), then Moderation (`POST .../decisions`) | Moderation to Session `GetSessionContext`, `GetCaseStatus`; Moderation to Applicant `GetApplicant`, Credential `GetCredentialResults`, University Record `GetCaseRecords`, and Rules `EvaluatePolicy`. Then `DecisionScored` is published and delivered to Session. |
| 39 | Session (`POST .../end`) | `ShiftEnded` is published and delivered to Player |
| 67, 69 as a non-administrator | None: Gateway answers 403 before the Broker | None |

Case creation shows the pattern. Request 33 produces one `dispatch` from `gateway` to `session`. Session's own record for that call has a different `request_id`, and the `StartCase` dispatch to `applicant` is under that ID. A retry shows as a higher `attempt` on the same call.

## Newman and native HTML reports

From the CPR root, run the same HTTP demo with the existing `newman-reporter-htmlextra` dashboard:

```sh
./scripts/run_newman.sh
# Include 100-slot overload and subsequent recovery (local Gateway at 127.0.0.1:8080):
./scripts/run_newman.sh --with-overload
```

The script requires Node.js/npm; overload also requires Python 3. On NixOS, run it in a Node/npm development shell if these commands are unavailable. Its pinned dependencies install locally under `tools/newman/node_modules/`, not globally. The default run covers 01–27, then 30–70. `--with-overload` starts the existing bounded helper, waits for READY, runs 28 while slots are held, runs 29 after the helper releases them, then runs 30–70. New runs create disposable accounts, friendships, teams, Sessions, cases, decisions and permissions. Folder F deletes only the friendship and team it creates; the runner does not clean up other service data or restart containers.

Open `.local/postman/newman-htmlextra.html` in a browser. All raw Newman results and populated environments remain private under ignored `.local/postman/run-*/`. The HTML uses allowlisted labels and numerical metrics: real URLs, resource IDs, headers, bodies, scripts, environments, logs and raw failure diagnostics are omitted **before** passing data to htmlextra. A second check rejects known environment secrets and JWTs. Report URLs are intentional dummy placeholders. The native dashboard may load its JavaScript/CSS from public CDNs.

To render the recorded phases of one run without sending any new requests:

```sh
./scripts/run_newman.sh \
  --from-json .local/postman/run-XXXXXX/private-01-27.json \
  --from-json .local/postman/run-XXXXXX/private-28.json \
  --from-json .local/postman/run-XXXXXX/private-29.json \
  --from-json .local/postman/run-XXXXXX/private-30-72.json
```

Repeated inputs are shown as separate recorded phases/iterations, not claimed as one uninterrupted Newman run. The dashboard timestamp is report generation time; the original start time and tested scope appear in its collection description. See `--help` for a different output path or public Gateway URL. Tests: `npm test --prefix tools/newman`. Exit status is nonzero for failed requests/assertions or report-generation errors. This collection does not prove task-timeout handling or direct WebSocket communication.
