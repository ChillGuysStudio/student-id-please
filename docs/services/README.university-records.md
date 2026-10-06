# University Record service

University Record owns university reference data, stable identities, snapshots, case facts, and record permissions.

## Public image

The image is [`maxnoragami/university-record-service`](https://hub.docker.com/r/maxnoragami/university-record-service/tags). The `UNIVERSITY_RECORD_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8006`.

Source code is in the [private repository](https://github.com/MaxNoragami/university-record-service). Public images run without private-source access.

## Dependencies

The service needs mongoDB with a replica set, verified Session context, and initialization event delivery.

Reference CRUD changes future snapshots. Case records and pinned snapshots remain immutable.

Stable student IDs and university mailboxes commit through one identity reservation operation. Failed propagation does not free an identity.

Mocked generation and authorization still exercise the real case handler and permission checks.

Integrated checks verify Session, all permitted service callers, and actual event delivery. An outbox entry alone does not prove that subscribers applied it.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `UNIVERSITY_MONGO_PASSWORD` supplies database credentials.
- `UNIVERSITY_ADMIN_TOKEN` configures administrative access.
- `SESSION_SERVICE_TOKEN`, `MODERATION_SERVICE_TOKEN`, and the DMs caller credential must agree with the accepted caller configuration.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [University Record Postman collection](../../postman/university-record-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
