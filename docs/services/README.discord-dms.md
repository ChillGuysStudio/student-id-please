# Discord DMs service

Discord DMs owns chat channels, membership, stored messages, tickets, and WebSocket delivery.

## Public image

The image is [`sentientmoss/pad-discord-dms-service`](https://hub.docker.com/r/sentientmoss/pad-discord-dms-service/tags). The `DISCORD_DMS_VERSION` variable selects its tag in [Compose](../../compose.yaml). The legacy standalone API address is `http://localhost:8009`, not Lab 2 client ingress.

Source code is in the [private repository](https://github.com/andyp1xe1/pad-discord-dms-service). Public images run without private-source access.

## Dependencies

The service needs PostgreSQL, Redis, verified player identity, Session roles, and University Record permissions.

`CHAT_TICKET_SECRET` is shared across replicas and retained across restarts. Tickets expire at the earlier of 30 seconds or actor expiry and can be consumed once.

Redis holds tickets and delivery notifications. PostgreSQL holds authoritative history. Clients recover missed notifications through REST.

Mocked authorization uses role and permission fixtures. Integrated authorization reads both owners and denies access when either check fails.

In the Lab 2 target, clients negotiate realtime access through REST on the gateway and receive a direct Discord DMs WebSocket URL. Discord DMs consumes the ticket on the direct upgrade and carries all chat frames. The gateway does not relay the live connection. Discord DMs redacts ticket query parameters, and message persistence precedes acknowledgement and broadcast.

The Lab 2 target sends ticket requests and history recovery through public gateway REST. All Discord DMs service REST, including permission reads during direct chat, uses the private internal gateway.

Current owned source supports `AUTH_MODE=gateway`. It verifies the gateway hop and request assertion, rejects original `Authorization`, and retains an encrypted chat capability for direct ticket consumption. Recurring Session and University Record reads send that capability and service credentials to internal gateway route prefixes. Roles, permissions, and lifecycle checks remain mandatory. The gateway caller name is `discord-dms`; legacy direct mode uses `dms`.

The [owned gateway adapter reference](https://github.com/andyp1xe1/pad-discord-dms-service/blob/dev/docs/gateway-auth.md) describes its settings. CPR still pins an older service revision and configures direct peer URLs. Gateway-capable source does not prove Compose or real-peer integration.

HTTP capacity exhaustion returns `503 TASK_LIMIT_EXCEEDED`. A task deadline returns `504 TASK_TIMEOUT`. Both include `Retry-After: 1`. Long-lived WebSockets retain separate authorization and transport limits.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `DMS_DB_PASSWORD` supplies the database password.
- Current legacy Compose uses `DISCORD_DMS_SERVICE_TOKEN` for caller `dms`. Gateway mode uses the adapter's `discord-dms` caller and internal-ingress credentials.
- `CHAT_TICKET_SECRET` and `REDIS_PASSWORD` configure tickets and delivery.
- Current Compose uses the legacy Player public-key volume and JWT settings. Gateway mode instead needs the adapter's gateway verification and receiver-hop settings.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Discord DMs Postman collection](../../postman/discord-dms-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
