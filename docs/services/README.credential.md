# Credential service

Credential owns document templates, immutable case documents, and deterministic validation results.

## Public image

The image is [`mcittkmims/credential-service`](https://hub.docker.com/r/mcittkmims/credential-service/tags). The `CREDENTIAL_SERVICE_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8082`.

Source code is in the [private repository](https://github.com/mcittkmims/credential-service). Public images run without private-source access.

## Dependencies

The service needs MongoDB with a replica set, Session context, and the pinned university snapshot.

The `credential` database belongs to this service even when MongoDB infrastructure is shared.

Validation checks document structure, authenticity, and expiry independently of admission policy.

Mocked generation uses the real generator and validator with typed source fixtures. Integrated generation consumes the real initialization event.

Expiry uses the pinned reference time. Template edits do not change documents already selected for a case.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `MONGODB_URI` identifies the service database and replica set.
- The CPR Compose file supplies the shared MongoDB address.
- Peer URLs and caller credentials follow the private service configuration.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Credential Postman collection](../../postman/credential-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
