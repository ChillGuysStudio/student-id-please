# Player Service integration contract

Player owns game accounts, profiles, friendships, moderation teams, and persistent XP. The [CPR communication contract](../../README.md#communication-contract) defines the shared REST and event rules. The [private Player repository](https://github.com/Tirppy/student-id-player-service) contains the implementation and source run instructions. This page describes its integration and the published image's Lab 1 deployment.

## Responsibilities and lifecycle

| Resource | Owner's operations | Boundary |
| --- | --- | --- |
| Player accounts and profiles | Register, authenticate, read, and change display names | Password hashes and email stay private; clients cannot edit XP. |
| Friendships | Request, accept, list, and remove | Only the participants may read or change a friendship. |
| Moderation teams | Create, read, change membership, and delete | Session owns the shift roster and roles, not Player. |
| Progression | Apply completed-shift awards and disciplinary deductions | Only events change XP; applicants and decisions belong to other services. |

Player does not store applicants, credentials, session scores, server rules, or chat messages. The [shared Player endpoint table](../../README.md#player-service-endpoints) is authoritative when a copied detail differs.

## Dependencies

| Interaction | Purpose |
| --- | --- |
| Session reads Player and Team | Check that a shift participant exists and belongs to its team. |
| Moderation reads Player | Check the target of a disciplinary action. |
| Session publishes `ShiftEnded` | Award XP to the shift participants. |
| Moderation publishes `DisciplinaryActionApplied` | Deduct XP for a disciplinary action. |
| Session and Moderation call the internal event adapter | Supply the same typed events when a broker producer is unavailable in Lab 1. |
| Player uses PostgreSQL | Persist accounts, teams, idempotency records, event receipts, and XP. |
| Player consumes RabbitMQ events | Apply completed-shift awards and disciplinary deductions. |

Internal HTTP callers identify themselves with `X-Service-Name` and `X-Service-Token`. Internal player and team reads also require the initiating player's Bearer token. Player verifies the caller and player identity before returning data.

## Data types

`Id` is a UUID string, `Int` is a signed 32-bit integer, and `Time` is an RFC 3339 UTC timestamp. The shared contract defines `Page<T>` and `Error`.

```text
Player = {player_id: Id, username: string, display_name: string, xp: Int, level: Int}
Tokens = {access_token: string, refresh_token: string, expires_in: Int, token_type: "Bearer"}
Team = {team_id: Id, name: string, owner_id: Id, member_ids: Id[]}
Friendship = {friendship_id: Id, requester_id: Id, recipient_id: Id,
              status: "pending" | "accepted"}
```

Registration stores a password hash and never returns the password or email in a `Player` response. Usernames and emails are unique and normalized to lowercase. Access tokens expire after 15 minutes. Refresh tokens expire after seven days, rotate on use, and are stored only as hashes. Logout revokes the refresh session.

## HTTP API

Public routes require a player Bearer token unless the caller column says anonymous or refresh-token holder. Mutations require a UUID `Idempotency-Key`. Lists use `limit` and `cursor` and return `Page<T>`.

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/players` | Anonymous | Username, email, password, display name | `201 Player` |
| `POST /api/v1/auth/login` | Anonymous | Email and password | `200 Tokens` |
| `POST /api/v1/auth/refresh` | Refresh-token holder | Refresh token | `200 Tokens` |
| `POST /api/v1/auth/logout` | Refresh-token holder | Refresh token | `204` |
| `GET /api/v1/players/me` | Player | None | `200 Player` |
| `PATCH /api/v1/players/me` | Player | Display name | `200 Player` |
| `GET /api/v1/players/{player_id}` | Player | None | `200 Player` |
| `POST /api/v1/friendships` | Player | Recipient ID | `201 Friendship` |
| `PUT /api/v1/friendships/{friendship_id}/acceptance` | Recipient | Empty object | `200 Friendship` |
| `GET /api/v1/friendships` | Player | Pagination | `200 Page<Friendship>` |
| `DELETE /api/v1/friendships/{friendship_id}` | Either participant | None | `204` |
| `POST /api/v1/teams` | Player | Team name | `201 Team` |
| `GET /api/v1/teams/{team_id}` | Team member | None | `200 Team` |
| `POST /api/v1/teams/{team_id}/members` | Team owner | Player ID | `200 Team`; the new member must be an accepted friend |
| `DELETE /api/v1/teams/{team_id}/members/{player_id}` | Owner or departing member | None | `200 Team` |
| `DELETE /api/v1/teams/{team_id}` | Owner | None | `204` |
| `GET /internal/v1/players/{player_id}` | Session or Moderation | None | `200 Player` |
| `GET /internal/v1/teams/{team_id}` | Session | None | `200 Team` |
| `POST /internal/v1/events` | Session or Moderation | Typed event | `200 {event_id: Id, applied: Bool}` |
| `GET /.well-known/jwks.json` | Anyone | None | `200` public verification keys |
| `GET /health` | Anyone | None | `200` process health |
| `GET /ready` | Anyone | None | `200` when configured dependencies are ready |

FastAPI also serves `/docs` and `/openapi.json`.

## Progression events

Player consumes `ShiftEnded` on `player.shift-ended.v1` and `DisciplinaryActionApplied` on `player.discipline-applied.v1`. Both use the durable `student-id.events.v1` exchange and schema version 1. The [shared event table](../../README.md#rabbitmq-event-contract) defines the exact envelope, routing keys, and payloads.

For each shift participant, `ShiftEnded` adds `max(0, score)` XP once per `session_id`. A disciplinary action subtracts its nonnegative `xp_penalty` once per `disciplinary_action_id`. Total XP cannot fall below zero. `level = 1 + floor(xp / 100)`. Session decision penalties are already reflected in its final score, so Player does not subtract them again.

Player records `(consumer, event_id)` and the shift or disciplinary business ID before acknowledging delivery. Replayed events cannot apply XP twice. Conflicting payloads for the same ID are rejected. The HTTP event adapter uses the same progression handler as the RabbitMQ consumers.

## Storage and Lab 1 deployment

The team deployment uses [`tirppy/student-id-player-service:latest`](https://hub.docker.com/r/tirppy/student-id-player-service/tags). The image listens on container port `8001` and runs as a non-root user. Publish the `latest` tag before pulling it. Player needs its own PostgreSQL database, a persistent RSA signing key, and RabbitMQ for shift and discipline events. SQLite and authenticated HTTP event fixtures support isolated checks. Redis and Session tables do not belong to Player.

Set these values in a local `.env`. Do not commit `.env`, service tokens, or signing keys. URL-encode reserved characters in database and broker passwords.

| Setting | Required value |
| --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://player:<password>@player-db:5432/player_db` for the shared deployment. |
| `JWT_PRIVATE_KEY_PATH` | `/app/data/player-private.pem`; keep `/app/data` on a named volume so existing tokens remain verifiable after recreation. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | `student-id-please` and `student-id-players`. Session and other token consumers must use the same values. |
| `SERVICE_TOKENS` | JSON map with distinct `session` and `moderation` credentials accepted by Player's internal endpoints. |
| `RABBITMQ_URL`, `RABBITMQ_EXCHANGE` | Reachable broker URL, for example `amqp://studentid:<password>@rabbitmq:5672/`, and `student-id.events.v1`. |

The shared Compose deployment is a separate team task. Its current Player portion uses these containers on one network:

| Container | Image and startup | Storage and access |
| --- | --- | --- |
| `player-db` | `postgres:17-alpine`; create database `player_db` and user `player`; wait for `pg_isready -U player -d player_db`. | Persist `/var/lib/postgresql/data`. Keep port `5432` private. |
| `rabbitmq` | `rabbitmq:4.1-management-alpine`; configure broker credentials and wait for `rabbitmq-diagnostics -q ping`. | Persist `/var/lib/rabbitmq`. Keep broker ports private. |
| `player` | Run the image after PostgreSQL and RabbitMQ are healthy. | Persist `/app/data` for the RSA key; bind API port `8001` to `127.0.0.1:8001` for a local check. |

To start the image against running dependencies, set `TEAM_NETWORK` to their Docker network name. Put the values above in `.env`, then run from the directory containing it in PowerShell:

```powershell
docker pull tirppy/student-id-player-service:latest
docker run --rm --network $env:TEAM_NETWORK --env-file .env -v player-keys:/app/data -p 127.0.0.1:8001:8001 tirppy/student-id-player-service:latest
```

`GET /health` checks the API process. `GET /ready` checks configured dependencies. `GET /.well-known/jwks.json` exposes the public verification key. The [private run guide](https://github.com/Tirppy/student-id-player-service/blob/dev/docs/running.md) covers source and isolated SQLite setup. The shared deployment must confirm that PostgreSQL records and the verification key survive container recreation.

The [Player Postman collection](../../postman/player-service.json) creates its test records, so it needs no seed data. Import it into Postman, set `player_url`, `session_token`, and `moderation_token` in a local environment, then run it in order. Its default URL is `http://localhost:8001`. Player's `SERVICE_TOKENS` map must contain the matching `session` and `moderation` values. The collection covers authentication, friendships, teams, XP fixtures, and duplicate event delivery.

For the Docker-based Newman runner, set `SESSION_SERVICE_TOKEN` and `MODERATION_SERVICE_TOKEN`, then run `python tools/player-service/run_postman.py` from the CPR root. It calls Player through `host.docker.internal:8001` by default. If Player is on a Docker network, set `POSTMAN_DOCKER_NETWORK` and `PLAYER_URL` to that network and Player's URL. Keep all test credentials out of Git.
