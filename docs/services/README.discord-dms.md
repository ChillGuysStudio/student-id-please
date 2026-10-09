# Discord DMs service

Discord DMs owns chat channels, membership, stored messages, tickets, and WebSocket delivery.

## Public image

The image is [`sentientmoss/pad-discord-dms-service`](https://hub.docker.com/r/sentientmoss/pad-discord-dms-service/tags). The `DISCORD_DMS_VERSION` variable selects its tag in [Compose](../../compose.yaml). The local API address is `http://localhost:8009`.

Source code is in the [private repository](https://github.com/andyp1xe1/pad-discord-dms-service). Public images run without private-source access.

## Dependencies

The service needs PostgreSQL, Redis, verified Player tokens, Session roles, and University Record permissions.

`CHAT_TICKET_SECRET` is shared across replicas and retained across restarts. Tickets expire after 30 seconds and can be consumed once.

Redis holds tickets and delivery notifications. PostgreSQL holds authoritative history. Clients recover missed notifications through REST.

Mocked authorization uses role and permission fixtures. Integrated authorization reads both owners and denies access when either check fails.

In the Lab 2 target, clients negotiate realtime access through REST on the gateway and receive a direct Discord DMs WebSocket URL. Discord DMs consumes the ticket on the direct upgrade and carries all chat frames. The gateway does not relay the live connection. Discord DMs redacts ticket query parameters, and message persistence precedes acknowledgement and broadcast.

Clients request new tickets and recover history through public gateway REST routes. All Discord DMs service-to-service REST, including Session role and University Record permission checks, uses the internal gateway. [Gateway authorization](../architecture.md#gateway-authorization) describes identity checks and service permissions. Current direct-mode service behavior does not prove that integration.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example).

- `DMS_DB_PASSWORD` supplies the database password.
- `DISCORD_DMS_SERVICE_TOKEN` identifies the `dms` caller to peers.
- `CHAT_TICKET_SECRET` and `REDIS_PASSWORD` configure tickets and delivery.
- The read-only public-key volume and JWT settings must match Player.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Discord DMs Postman collection](../../postman/discord-dms-service.json) provides request fixtures. [Verification cases](../verification.md) describe expected failure and retry behavior.
