# Player service

Player owns accounts, authentication, friendships, teams, and persistent progression.

## Public image

The image is [`tirppy/student-id-player-service`](https://hub.docker.com/r/tirppy/student-id-player-service/tags). The `PLAYER_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8001`.

Source code is in the [private repository](https://github.com/Tirppy/student-id-player-service). Public images run without private-source access.

## Dependencies

The service needs PostgreSQL, a persistent RSA signing key, and progression event consumers.

Player issues the access tokens that peer services verify. The public key endpoint is `/.well-known/jwks.json`.

A signing-key volume preserves token verification across container recreation. Token issuer and audience must match the peer configuration.

When event fixtures replace RabbitMQ, they use the same typed progression handler and authenticated producer identity. Integrated checks verify actual broker delivery and one progression update.

## Configuration

For gateway mode, use the confirmed receiver names and published image evidence in the [Player and Session runtime packet](../player-session-runtime.md). The settings below describe the existing standalone Compose configuration.

The shared deployment reads [`.env.example`](../../.env.example).

- `PLAYER_DB_PASSWORD` supplies the database password.
- `SESSION_SERVICE_TOKEN` and `MODERATION_SERVICE_TOKEN` identify the accepted internal callers.
- `RABBITMQ_PASSWORD` configures the shared event broker.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Player Postman collection](../../postman/player-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
