# Server Rules service

Server Rules owns draft and published rule versions and evidence-based policy evaluation.

## Public image

The image is [`maxnoragami/server-rules-service`](https://hub.docker.com/r/maxnoragami/server-rules-service/tags). The `SERVER_RULES_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8005`.

Source code is in the [private repository](https://github.com/MaxNoragami/server-rules-service). Public images run without private-source access.

## Dependencies

The service needs postgreSQL, verified Session context, and complete case evidence from Moderation.

A published ruleset stays immutable. Session pins one published version for a shift.

Mocked Session context provides the same case, role, policy version, and reference time as the real context endpoint.

Integrated evaluation checks the pinned configuration. It does not receive generator seeds, scenarios, or expected decisions.

Static caller tokens are isolated fixture credentials, not a substitute for verified player context in an integrated game.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `RULES_DB_PASSWORD` supplies the database password.
- `RULES_ADMIN_TOKEN` and `RULES_PLAYER_TOKEN` configure fixture caller roles.
- `SESSION_SERVICE_TOKEN` and `MODERATION_SERVICE_TOKEN` configure service callers.
- `RULES_CURSOR_SECRET` signs pagination cursors.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Server Rules Postman collection](../../postman/server-rules-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
