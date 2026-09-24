# Discord DMs Service integration contract

Discord DMs stores moderation chat and delivers messages to shift participants. Channel access follows Session roles and University Record permissions. The [CPR communication contract](../../README.md#communication-contract) defines the shared types and transports. This page lists the information needed to deploy the published service image.

## Responsibilities and lifecycle

| Resource | Operations | Boundary |
| --- | --- | --- |
| Shift channels and membership | Create channels on first access and list the caller's channels | Session owns roles; University Record owns record permissions. |
| Messages | Commit, read, and paginate channel history | PostgreSQL is the record of messages. Discord DMs does not own university facts or decisions. |
| Chat tickets | Issue a 30-second, single-use WebSocket ticket | Redis holds short-lived ticket state, not message history. |
| Live delivery | Acknowledge persisted messages and notify connected members | Redis Pub/Sub reaches other replicas; REST history recovers missed notifications. |

A Moderator can use all four channels. Junior Moderators can use `#general-mod-chat` and channels allowed by their record permissions. Enrollment or academic-year access permits `#enrollment-check`; Outlook group or FCIM message access permits `#faculty-check`; course or schedule access permits `#course-registration`. Chat permission never grants direct access to University Record data.

## Dependencies

| Interaction | Purpose |
| --- | --- |
| Discord DMs reads Session context | Verify the player, assigned role, and active shift. |
| Discord DMs reads University Record permissions | Restrict channel lists, history, connections, and sends. |
| Discord DMs uses PostgreSQL | Store channels, memberships, messages, and ticket-request idempotency records. |
| Discord DMs uses Redis | Consume tickets once and broadcast committed messages to WebSocket replicas. |

The service verifies Player RS256 tokens locally. Internal calls send `X-Service-Name: dms`, `X-Service-Token`, and the initiating player's Bearer token. Session also receives `player_id` as a query parameter. Confirm that University Record accepts these headers before connecting the full team stack. An unavailable Session or University Record service returns `503` instead of granting access.

## HTTP and WebSocket API

REST routes require a player Bearer token. The ticket request also requires a UUID `Idempotency-Key` and an empty JSON object. History accepts `limit` from 1 to 100 and an opaque `cursor`.

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `GET /api/v1/sessions/{session_id}/channels` | Shift participant | None | `200 {channels: Channel[]}` |
| `GET /api/v1/channels/{channel_id}/messages` | Authorized channel member | Pagination | `200 Page<Message>` in chronological order |
| `POST /api/v1/sessions/{session_id}/chat-tickets` | Participant in an active shift | `{}` | `201 {ticket, expires_at}` |
| `GET /api/v1/sessions/{session_id}/ws?ticket=...` | Ticket holder | WebSocket upgrade | `101 Switching Protocols` |
| `GET /healthz` | Anyone | None | `200 {status: "ok"}` |

A client sends `{type: "message.send", client_message_id, channel_id, text}` over the WebSocket. The server sends `message.ack` after the PostgreSQL commit and publishes `message.created` to authorized connections. Retrying an identical `client_message_id` returns the original acknowledgement without inserting another message. Reusing that ID with different text returns an error. A consumed or expired ticket cannot reconnect; request a new ticket and read missed messages through REST history. The [shared WebSocket contract](../../README.md#discord-dms-service-endpoints-and-websocket-frames) defines the complete frame shapes and close behavior.

## Storage and Lab 1 deployment

The public, versioned image is [`sentientmoss/pad-discord-dms-service:0.1.1`](https://hub.docker.com/r/sentientmoss/pad-discord-dms-service/tags). It serves container port `8000`; bind it to `127.0.0.1:8009` for a local check. Persist PostgreSQL's data directory. Redis tickets expire in 30 seconds and Pub/Sub retains no messages, so Redis does not need a disk volume for chat history. After Redis restarts, clients must request new tickets. Keep `CHAT_TICKET_SECRET` stable across API replicas and restarts so they can validate each other's tickets.

Set these values in a local `.env`. Do not commit `.env`, tokens, or keys.

| Setting | Required value |
| --- | --- |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | Database password and `postgresql+asyncpg://discord_dms:<password>@postgres:5432/discord_dms`. |
| `REDIS_PASSWORD`, `REDIS_URL` | Redis password and `redis://:<password>@redis:6379/0`. URL-encode reserved password characters. |
| `CHAT_TICKET_SECRET` | Long random secret shared across API replicas; preserve it across restarts. |
| `JWT_PUBLIC_KEY_FILE`, `JWT_ISSUER`, `JWT_AUDIENCE` | Path to the mounted Player RS256 public key and values that match Player's issued access tokens. Set the file path to `/run/secrets/player-public.pem` for the command below. |
| `SESSION_URL`, `UNIVERSITY_URL` | Reachable service base URLs on the deployment network. |
| `SESSION_SERVICE_TOKEN`, `UNIVERSITY_SERVICE_TOKEN` | Credentials accepted by the receiving services for their internal endpoints. |
| `MOCK_CONTRACT_FILE` | Empty when connecting real services. Set it only for a local test fixture. |

The later shared deployment needs these containers on one network. The listed names match the hosts in `DATABASE_URL` and `REDIS_URL` above.

| Container | Image and startup | Storage and access |
| --- | --- | --- |
| `postgres` | `postgres:17-alpine`; create database and user `discord_dms`; wait for `pg_isready -U discord_dms -d discord_dms`. | Persist `/var/lib/postgresql/data` in a named volume such as `dms_pg`. Do not publish port `5432` to clients. |
| `redis` | `redis:7-alpine`; start with `redis-server --requirepass <REDIS_PASSWORD>`; wait for an authenticated `redis-cli ping` to return `PONG`. | Ticket keys and Pub/Sub state are ephemeral. Keep port `6379` private. |
| `discord-dms` | Run the versioned image after PostgreSQL and Redis are healthy. The default command starts the API and creates its tables. | Container port `8000`, optionally bound to `127.0.0.1:8009`. Mount the Player public key read-only. |

To start the published image against running dependencies, set `TEAM_NETWORK` to their Docker network name. Put `.env` and `player-public.pem` in the current directory. Make the public key readable by the image's non-root user, UID `65532`. Set `MOCK_CONTRACT_FILE` to an empty value for real upstreams.

```sh
docker pull sentientmoss/pad-discord-dms-service:0.1.1
docker run --rm --network "$TEAM_NETWORK" --env-file .env \
  -e JWT_PUBLIC_KEY_FILE=/run/secrets/player-public.pem \
  -e MOCK_CONTRACT_FILE= \
  -v "$PWD/player-public.pem:/run/secrets/player-public.pem:ro" \
  -p 127.0.0.1:8009:8000 sentientmoss/pad-discord-dms-service:0.1.1
```

`curl -fsS http://127.0.0.1:8009/healthz` checks the API process, not access to Session or University Record. A gateway must forward WebSocket upgrades, allow long-lived connections, and redact ticket query values in its logs. Keep the PostgreSQL and Redis ports off the public network. The shared Compose file is a separate team task.

To seed an empty Discord DMs database, run the seed module shipped in the public image on the same network:

```sh
docker run --rm --network "$TEAM_NETWORK" --env-file .env \
  sentientmoss/pad-discord-dms-service:0.1.1 python -m discord_dms.seed
```

The seed command adds a demo session, channels, and one message. It leaves existing data unchanged. Session and University Record still need matching roles and permissions for players to read those records. The [Discord DMs Postman collection](../../postman/discord-dms-service.json) tests channels, history, tickets, and errors. Set its IDs and Bearer tokens to match your deployment. It also lists manual WebSocket checks that Newman cannot run.
