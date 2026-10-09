# Guided Lab 2 demo in Postman

## Import and connect

1. Open Postman and import `postman/lab2-guided-demo.postman_collection.json` and `postman/lab2-guided-demo.postman_environment.json`.
2. Select **Lab 2 — local guided demo (do not share after running)** in the environment selector.
3. Set `gateway_url` to the reachable **public Gateway** address. On the machine running Compose, it is `http://127.0.0.1:18080`. If Postman is on another computer, use a secure tunnel to that port and enter the forwarded local URL. Do not target individual service ports or Gateway's private listener.
4. Expand folder **A** and click **01 — Gateway health** → **Send**. This creates three fresh disposable identities in your selected Postman environment. Continue through **02–27**, selecting each request and clicking **Send** in numeric order. Each request checks its response in the **Test Results** tab; stop if one fails. Login requests **03, 05 and 07** save each access token automatically. Nothing needs to be copied between requests.
5. Folder **A** shows valid login, protected reads and rejection of absent/forged credentials. Folder **B** creates real friendships, a team and a three-person Session lobby. Folder **C** assigns and verifies University record permissions for the two juniors.

## Show 100 simultaneous tasks and overload

6. Select **28 — Observe the 101st concurrent request (503)** in Postman and keep its **Send** button ready. From a *separate terminal on the same Compose host*, run:

   ```sh
   cd /mnt/shared/dev/pad-team-21-student-id
   python3 postman/lab2-overload.py
   ```

   When the terminal prints **READY**, click **Send** in Postman promptly. The test requires HTTP **503 `TASK_LIMIT_EXCEEDED`**, a matching request ID and `Retry-After: 1`. The helper opens 100 bounded, incomplete requests to occupy the Gateway's 100 task slots. They contain no credentials, cannot complete a registration and are closed automatically. It verifies overload itself before showing READY. This is **100 concurrent tasks**, not a rate-per-second test. If you miss the short window, rerun the helper and repeat 28.
7. When the helper prints **DONE**, click **29 — Verify protected reads recover after the helper exits**. This must return **200** for the logged-in player again.

The collection presents the demonstrated HTTP lobby and permission flow; it does not include Session activation or direct WebSocket frames. The helper does not configure or restart any service. Keep the populated Postman environment private: it contains the generated players' passwords and tokens. Do not export or commit it after running.

## Newman and native HTML reports

From the CPR root, run the same HTTP demo with the existing `newman-reporter-htmlextra` dashboard:

```sh
./scripts/run_lab2_newman.sh
# Include 100-slot overload and subsequent recovery (local Gateway at 127.0.0.1:18080):
./scripts/run_lab2_newman.sh --with-overload
```

The script requires Node.js/npm; overload also requires Python 3. On NixOS, run it in a Node/npm development shell if these commands are unavailable. Its pinned dependencies install locally under `tools/newman/node_modules/`, not globally. The default run covers 01–27. `--with-overload` starts the existing bounded helper, waits for READY, runs 28 while slots are held, then runs 29 after the helper releases them. New runs create disposable accounts, friendships, teams, lobbies and permissions; they do not clean up that service data or restart containers.

Open `.local/lab2-postman/newman-htmlextra.html` in a browser. All raw Newman results and populated environments remain private under ignored `.local/lab2-postman/run-*/`. The HTML uses allowlisted labels and numerical metrics: real URLs, resource IDs, headers, bodies, scripts, environments, logs and raw failure diagnostics are omitted **before** passing data to htmlextra. A second check rejects known environment secrets and JWTs. Report URLs are intentional dummy placeholders. The native dashboard may load its JavaScript/CSS from public CDNs.

To render the already recorded three phases without sending any new requests:

```sh
./scripts/run_lab2_newman.sh \
  --from-json .local/lab2-postman/private-newman.json \
  --from-json .local/lab2-postman/private-newman-28.json \
  --from-json .local/lab2-postman/private-newman-29.json
```

Repeated inputs are shown as separate recorded phases/iterations, not claimed as one uninterrupted Newman run. The dashboard timestamp is report generation time; the original start time and tested scope appear in its collection description. See `--help` for a different output path or public Gateway URL. Tests: `npm test --prefix tools/newman`. Exit status is nonzero for failed requests/assertions or report-generation errors. This collection does not prove Session activation, task-timeout handling or direct WebSocket communication.
