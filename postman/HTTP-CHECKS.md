# Check HTTP without changing registry state

The [discovery and resilience contract](../docs/contracts/resilience.md) defines expected HTTP responses. These Newman folders check only observable read-only behavior. They do not register, remove, or reactivate a service. Do not run the default guided-demo runner for this check, because its default creates players and sessions.

## Run the safe public folder

From the CPR root, run the existing pinned runner against the public Gateway:

```sh
./scripts/run_newman.sh --http --gateway-url http://127.0.0.1:8080
```

The folder sends four anonymous GET requests. It checks Gateway liveness, denial of private status and registry reads on public ingress, and denial of an unauthenticated Player read. It also checks that public responses do not expose Gateway's private attribution headers. A successful run says nothing about routing or registered replicas. The runner writes redacted HTML under ignored `.local/postman/http-checks/`, and private raw results under that directory's `run-*` subdirectory.

## Run the private Discovery health check separately

Discovery serves its registry and status only over gRPC. Its HTTP listener keeps `/healthz`, which this folder reads. Copy `postman/http-checks.postman_environment.json` into ignored `.local/postman/http-checks/` and set `discovery_url` to a reachable private Discovery listener. Compose runs Discovery on port `8081` without publishing it, so the template's `http://discovery:8081` resolves only on the Compose network, not from the host. This folder is not part of safe public smoke.

```sh
./scripts/run_newman.sh --http-private --environment .local/postman/http-checks/discovery.postman_environment.json
```

The folder sends one GET and checks that Discovery reports `ok`. It needs no credential and proves nothing about registration.

To read Discovery status or the registry, call `ControlService.GetStatus` or `DiscoveryService.ListInstances` with `grpcurl` and the checked-in protos. Set `CONTROL_TOKEN` to the operator control token in your shell first; `-e CONTROL_TOKEN` copies it into the container without putting the value in the command line:

```sh
docker run --rm --network student-id-please_default -e CONTROL_TOKEN -v "$PWD/proto:/proto:ro,z" fullstorydev/grpcurl:v1.9.1 \
	-plaintext -import-path /proto -proto student_id/discovery/v1/discovery.proto \
	-expand-headers -H 'x-control-name: operator' -H 'x-control-token: ${CONTROL_TOKEN}' \
	-d '{"include_unavailable": true}' \
	discovery:50051 student_id.discovery.v1.DiscoveryService/ListInstances
```

The network name is `<project>_default`; replace `student-id-please` with your Compose project name. A wrong credential returns `Unauthenticated`, which still confirms that the listener is reachable. The [demonstration guide](../docs/demonstration.md#call-a-service-over-grpc) has more `grpcurl` examples. Do not print or publish the populated environment, the token, or raw run files.

## Use companion runtime checks for state changes

The operator must opt in to registration or removal checks outside these read-only folders, using the private `DiscoveryService` RPCs and deployment-owned instance identity. Do not replay removal against a live replica as a default smoke test. Record sanitized instance IDs, registration generations, epoch, and elapsed times without tokens, chat tickets, or webhook URLs.

- Register distinct replicas, renew and expire a lease, and compare ready-only and unavailable-inclusive snapshots. Check that a removal excludes only its failed generation, survives Discovery restart, and needs explicit operator reactivation after the cooldown and two healthy probes.
- Send repeated authorized reads under a separate runtime demonstration. Match Broker `dispatch` logs to selected backend instance IDs to prove alternation across equally loaded replicas, and a lower share to a more loaded replica. The [load routing contract](../docs/contracts/routing.md) defines selection. Public responses intentionally omit private attribution headers; do not forge Gateway assertions to get them.
- Inject three qualifying failures across backend endpoints within `3.5 * T`. Correlate bounded caller logs and removal records; ordinary Postman response codes cannot prove the timing window or single-attempt accounting. Use a controlled task-load helper to observe the critical-load threshold and Discovery's timed health polls in logs. A failed health check alone is not a load alert.
- Negotiate chat through public Gateway REST, then open WebSocket connections through the DMs proxy and exchange frames between players on different replicas. HTTP checks cannot prove WebSocket delivery or Discord notification receipt. Live Discord delivery remains deferred pending private configuration.

Run `npm test --prefix tools/newman` for the reporter and redaction tests. Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` for the CPR collection structure and repository checks.
