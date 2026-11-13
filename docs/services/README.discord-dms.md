# Discord DMs service

Discord DMs owns chat channels, membership, stored messages, tickets, and WebSocket delivery.

## Public image

The image is [`sentientmoss/pad-discord-dms-service`](https://hub.docker.com/r/sentientmoss/pad-discord-dms-service/tags). Set `DISCORD_DMS_IMAGE` in `.env` to pin a version. The default is `latest` in [Compose](../../compose.yaml). The legacy standalone API address is `http://localhost:8009`, not client ingress.

Source code is in the [private repository](https://github.com/andyp1xe1/pad-discord-dms-service). Public images run without private-source access.

## Dependencies

The service needs PostgreSQL, Redis, verified player identity, Session roles, and University Record permissions.

`CHAT_TICKET_SECRET` is shared across replicas and retained across restarts. Tickets expire at the earlier of 30 seconds or actor expiry and can be consumed once.

Redis holds tickets and delivery notifications. PostgreSQL holds authoritative history. Clients recover missed notifications through REST.

Mocked authorization uses role and permission fixtures. Integrated authorization reads both owners and denies access when either check fails.

Clients negotiate realtime access through REST on the gateway and receive the chat URL of the DMs proxy. The proxy forwards the upgrade to one Discord DMs replica, which consumes the ticket and carries all chat frames. The gateway and the Broker do not relay the live connection. Discord DMs redacts ticket query parameters, and message persistence precedes acknowledgement and broadcast.

Ticket requests and history recovery use public gateway REST. Discord DMs reads Session and University Record with typed gRPC calls through the Message Broker, including permission reads during chat.

Current owned source supports `AUTH_MODE=gateway`. It verifies the gateway hop and request assertion, rejects original `Authorization`, and retains an encrypted chat capability for direct ticket consumption. Recurring Session and University Record reads send that capability and the service credential to the Broker. Roles, permissions, and lifecycle checks remain mandatory. The gateway caller name is `discord-dms`; legacy direct mode uses `dms`.

The [owned gateway adapter reference](https://github.com/andyp1xe1/pad-discord-dms-service/blob/dev/docs/gateway-auth.md) describes its settings. CPR Compose runs the gateway adapter with the settings that [`scripts/setup.py`](../../scripts/setup.py) generates.

HTTP capacity exhaustion returns `503 TASK_LIMIT_EXCEEDED`. A task deadline returns `504 TASK_TIMEOUT`. Both include `Retry-After: 1`. Long-lived WebSockets retain separate authorization and transport limits.

## Configuration

The shared deployment reads [`.env.example`](../../.env.example). Compose runs `discord-dms` with two replicas and no host port. Scale it with `docker compose up -d --no-deps --scale discord-dms=3 discord-dms`. The `dms-proxy` Caddy container publishes the chat port and balances WebSocket connections across the replicas by least connections. Redis carries tickets and fan-out between replicas.

- `DMS_DB_PASSWORD` supplies the database password.
- `DMS_PORT` sets the chat proxy host port, `8009` by default. Gateway returns `ws://localhost:${DMS_PORT}` as the chat URL.
- `DISCORD_DMS_SERVICE_TOKEN` is the `discord-dms` caller credential for Broker calls.
- `CHAT_TICKET_SECRET` and `REDIS_PASSWORD` configure tickets and delivery.
- Compose mounts the Gateway public key, and `.local/stack/discord-dms.env` holds the receiver-hop settings.

## Contracts and checks

[Service APIs](../contracts/api.md), [HTTP conventions](../contracts/http.md), and [event definitions](../contracts/events.md) define the shared behavior. [Integration principles](../integration.md) describe mocked and integrated deployments.

The [Discord DMs Postman collection](../../postman/discord-dms-service.json) sends this service's public requests through the Gateway. Its `gateway_url` variable defaults to `http://127.0.0.1:8080`. The [HTTP conventions](../contracts/http.md) define expected failure and retry behavior.
