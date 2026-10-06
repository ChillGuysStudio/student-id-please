# Session service

Session owns shift lifecycle, roster, roles, current case references, and aggregate scoring.

## Public image

The image is [`tirppy/student-id-session-service`](https://hub.docker.com/r/tirppy/student-id-session-service/tags). The `SESSION_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8002`.

Source code is in the [private repository](https://github.com/Tirppy/student-id-session-service). Public images run without private-source access.

## Dependencies

The service needs postgreSQL, Player identity, Redis caching, and decision/result event delivery.

PostgreSQL is the source of roles, state, and scores. Redis caches rebuildable views.

`EXTERNAL_SERVICES_MODE=mock` replaces evidence and policy dependencies with contract fixtures. Those fixtures do not generate applicant facts or choose admission outcomes.

Integrated mode uses real Rules, University Record, Applicant, and Credential URLs. Snapshot creation, permission checks, and readiness polling must reach those owners.

Internal player-context requests need both service authentication and the initiating player identity.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `SESSION_DB_PASSWORD` supplies the database password.
- `SESSION_SERVICE_TOKEN` identifies Session to its peers.
- `MODERATION_SERVICE_TOKEN` and `DISCORD_DMS_SERVICE_TOKEN` configure accepted internal callers.
- `REDIS_PASSWORD` and `RABBITMQ_PASSWORD` configure shared infrastructure.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Session Postman collection](../../postman/session-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
