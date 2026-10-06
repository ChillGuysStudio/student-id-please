# Moderation service

Moderation owns final admission decisions, subject bans, policy snapshots, and disciplinary actions.

## Public image

The image is [`sentientmoss/pad-moderation-service`](https://hub.docker.com/r/sentientmoss/pad-moderation-service/tags). The `MODERATION_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8008`.

Source code is in the [private repository](https://github.com/andyp1xe1/pad-moderation-service). Public images run without private-source access.

## Dependencies

The service needs postgreSQL, the evidence and policy services, verified Player tokens, and RabbitMQ.

The API and `moderation-publisher` share the same database. The publisher runs `python -m moderation.publisher` from the same image.

A decision, its optional ban, and its event outbox record commit in one local transaction.

When `MOCK_CONTRACT_FILE` supplies fixtures, the real adapters and decision code still validate them. Integrated runs leave that setting empty.

Upstream calls need compatible service authentication and verified player context. Missing or rejected context is a dependency error, not a policy result.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `MODERATION_DB_PASSWORD` supplies the database password.
- `MODERATION_SERVICE_TOKEN` identifies the caller to peers.
- The read-only public-key volume and JWT settings must match Player.
- `RABBITMQ_PASSWORD` configures event publication.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Moderation Postman collection](../../postman/moderation-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
