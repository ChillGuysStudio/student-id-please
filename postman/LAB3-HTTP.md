# Check Lab 3 HTTP without changing registry state

The [Lab 3 contract](../docs/contracts/lab3.md) defines expected HTTP responses. These Newman folders check only observable read-only behavior. They do not register, remove, or reactivate a service. Do not run the Lab 2 default runner for this check, because its default creates players and sessions.

## Run the safe public folder

From the CPR root, run the existing pinned runner against the public Gateway:

```sh
./scripts/run_lab2_newman.sh --lab3-safe --gateway-url http://127.0.0.1:8080
```

The folder sends three anonymous GET requests. It checks Gateway liveness, denial of private status on public ingress, and denial of an unauthenticated Player read. It also checks that public responses do not expose Gateway's private attribution headers. A successful run says nothing about routing or registered replicas. The runner writes redacted HTML under ignored `.local/lab3-postman/`, and private raw results under that directory's `run-*` subdirectory.

## Run private operator reads separately

Copy `postman/lab3-http.postman_environment.json` into ignored `.local/lab3-postman/`. Set `discovery_url` to a reachable private Discovery listener and replace `control_token` in the copy with the operator credential. Do not put the token in shell arguments, the checked-in template, or a published report. This folder is not part of safe public smoke.

```sh
./scripts/run_lab2_newman.sh --lab3-private --environment .local/lab3-postman/operator.postman_environment.json
```

The folder reads Discovery status, a default ready-only registry snapshot, and an unavailable-inclusive snapshot. It checks instance UUIDs, boot IDs, registration IDs, lease time, readiness, load ratios, epoch, and revision where the response contains instances. An empty snapshot is valid; it does not prove successful registration or filtering. IDs saved in the private Newman environment are diagnostic only, not evidence of round-robin routing. Do not print or publish the populated environment or raw run files. The HTML reporter removes response bodies, headers, URLs, scripts, raw failures, and environment values before rendering. The runner returns a nonzero exit code on assertion or request failure.

## Use companion runtime checks for state changes

The operator must opt in to registration or removal checks outside these read-only folders, using the exact private Discovery API and deployment-owned instance identity. Do not replay removal against a live replica as a default smoke test. Record sanitized instance IDs, registration generations, epoch, and elapsed times without tokens, chat tickets, or webhook URLs.

- Register distinct replicas, renew and expire a lease, and compare ready-only and unavailable-inclusive snapshots. Check that a removal excludes only its failed generation, survives Discovery restart, and needs explicit operator reactivation after the cooldown and two healthy probes.
- Send repeated authorized reads under a separate runtime demonstration. Match Gateway logs to selected backend instance IDs to prove round-robin across replicas. Public responses intentionally omit private attribution headers; do not forge Gateway assertions to get them.
- Inject three qualifying failures across backend endpoints within `3.5 * T`. Correlate bounded caller logs and removal records; ordinary Postman response codes cannot prove the timing window or single-attempt accounting. Use a controlled task-load helper to observe the critical-load threshold and Discovery's timed health polls in logs. A failed health check alone is not a load alert.
- Negotiate chat through public Gateway REST, then open direct WebSocket connections to each advertised DMs address and exchange frames between replicas. HTTP checks cannot prove WebSocket delivery or Discord notification receipt. Live Discord delivery remains deferred pending private configuration.

Run `npm test --prefix tools/newman` for the reporter and redaction tests. Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` for the CPR collection structure and repository checks.
