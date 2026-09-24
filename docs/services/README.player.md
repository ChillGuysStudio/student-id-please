# Player Service integration contract

Player owns game accounts, profiles, friendships, moderation teams, and persistent XP. The [CPR communication contract](../../README.md#communication-contract) defines the shared REST and event rules. The [private Player repository](https://github.com/Tirppy/student-id-player-service) contains the implementation and its run instructions. This document describes the Lab 1 integration used by the other services.

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

## Storage and Lab 1 verification

Player uses its own PostgreSQL database. Its database and RSA signing key need persistent storage in the team deployment, which will be added in a separate PR. Redis and Session tables do not belong to Player. SQLite is available for isolated development.

The published Lab 1 review image is [`tirppy/student-id-player-service:1.0.0-rc.2`](https://hub.docker.com/r/tirppy/student-id-player-service/tags). Follow the [private run guide](https://github.com/Tirppy/student-id-player-service/blob/0ac87baa602dc0d5e3f29175cd123d7b8692f7da/docs/running.md) for standalone source or container setup. The [Player Postman collection](../../postman/player-service.json) exercises registration, friendships, teams, and progression. The private repository README gives the Lab 1 Grade 3 run instructions.

Verification should cover password privacy, token rotation, friendship and team authorization, duplicate event delivery, and XP after a completed shift. The later team deployment must verify that Player records and its public signing key survive container recreation.
