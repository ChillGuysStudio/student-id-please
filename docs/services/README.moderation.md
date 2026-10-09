# Moderation service

Moderation owns final admission decisions, subject bans, policy snapshots, and disciplinary actions.

## Public image

The image is [`sentientmoss/pad-moderation-service`](https://hub.docker.com/r/sentientmoss/pad-moderation-service/tags). The `MODERATION_VERSION` variable selects its tag in [Compose](../../compose.yaml). The legacy standalone API address is `http://localhost:8008`, not Lab 2 client ingress.

Source code is in the [private repository](https://github.com/andyp1xe1/pad-moderation-service). Public images run without private-source access.

## Dependencies

The service needs PostgreSQL, the evidence and policy services, verified player identity, and RabbitMQ.

The API and `moderation-publisher` share the same database. The publisher runs `python -m moderation.publisher` from the same image.

A decision, its optional ban, and its event outbox record commit in one local transaction.

When `MOCK_CONTRACT_FILE` supplies fixtures, the real adapters and decision code still validate them. Integrated runs leave that setting empty.

Current owned source supports `AUTH_MODE=gateway`. It authenticates the gateway hop, verifies the request assertion, and rejects original `Authorization`. Peer calls use delegation and service credentials through private internal gateway route prefixes. Moderation retains Session role, lifecycle, readiness, and policy checks. Missing or rejected context cannot become a policy result.

The [owned gateway adapter reference](https://github.com/andyp1xe1/pad-moderation-service/blob/dev/docs/gateway-auth.md) describes its settings. CPR still pins an older service revision and configures direct peer URLs. Gateway-capable source does not prove Compose or real-peer integration.

HTTP capacity exhaustion returns `503 TASK_LIMIT_EXCEEDED`. A task deadline returns `504 TASK_TIMEOUT`. Both include `Retry-After: 1`.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `MODERATION_DB_PASSWORD` supplies the database password.
- `MODERATION_SERVICE_TOKEN` identifies the caller to peers.
- Current Compose uses the legacy Player public-key volume and JWT settings. Gateway mode instead needs the adapter's gateway verification and receiver-hop settings.
- `RABBITMQ_PASSWORD` configures event publication.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Moderation Postman collection](../../postman/moderation-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
