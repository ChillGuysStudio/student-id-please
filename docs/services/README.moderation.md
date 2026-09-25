# Moderation Service integration contract

Moderation records admission decisions, subject bans, and administrator disciplinary actions. It asks Server Rules to evaluate complete case evidence before it scores a decision. The [CPR communication contract](../../README.md#communication-contract) defines the shared REST and event types. This page lists the information needed to deploy the published service image.

## Responsibilities and lifecycle

| Resource | Operations | Boundary |
| --- | --- | --- |
| Decisions | Submit and read one final action per case | Session owns the current case and aggregate score. Server Rules owns the expected action. |
| Subject bans | Create with a ban decision; list by subject | University Record supplies the actual subject ID. A case ID does not identify a person. |
| Disciplinary actions | Admin creates a player XP deduction | Player owns the account and applies the deduction. |
| Event outbox | Store and publish scoring and discipline events | Consumers apply each event once. Moderation does not update their databases. |

Moderation stores immutable policy results with decisions. It does not own applicant claims, credentials, university records, rulesets, or player XP.

## Dependencies

| Interaction | Purpose |
| --- | --- |
| Moderation reads Session context | Check the player's shift role, active status, current case, and pinned rule version. |
| Moderation reads Applicant, Credential, and University Record | Collect claims, validated documents, and authoritative records for the current case. |
| Moderation calls Server Rules | Evaluate the complete evidence against the pinned rule version and existing bans. |
| Moderation reads Player | Validate a disciplinary action's target. |
| Moderation publishes `DecisionScored` | Let Session apply the score and penalty once. |
| Moderation publishes `DisciplinaryActionApplied` | Let Player deduct XP once. |

The service requires PostgreSQL for decisions, bans, idempotency records, and outbox rows. Its separate publisher process requires RabbitMQ. Both processes use the same PostgreSQL database. If a required upstream is unavailable, the API returns `503` rather than guessing an expected action. The current Moderation implementation sends `X-Service-Token` and `X-Player-Id` to internal services; confirm the receiving services' authentication headers before connecting the full team stack.

## HTTP API

Player-facing routes require an RS256 Bearer token. Mutations require a UUID `Idempotency-Key`. List routes accept `limit` from 1 to 100 and an opaque `cursor`.

| Method and path | Caller | Request | Success |
| --- | --- | --- | --- |
| `POST /api/v1/sessions/{session_id}/decisions` | Assigned Moderator | `{case_id, action, reason}` | `201 Decision` |
| `GET /api/v1/sessions/{session_id}/decisions` | Shift participant | Pagination | `200 Page<Decision>` |
| `GET /api/v1/sessions/{session_id}/decisions/{decision_id}` | Shift participant | None | `200 Decision` |
| `GET /api/v1/bans` | Global admin | Optional subject ID and pagination | `200 Page<Ban>` |
| `POST /api/v1/disciplinary-actions` | Global admin | `{player_id, reason, xp_penalty}` | `201 Discipline` |
| `GET /healthz` | Anyone | None | `200 {status: "ok"}` |

`action` is `accept`, `reject`, `flag`, or `ban`. A ban requires the actual subject ID from University Record. A correct action adds 10 points; an incorrect one adds -5 points and 5 penalty points. Moderation commits the decision, optional ban, idempotency result, and `DecisionScored` outbox row in one PostgreSQL transaction. The publisher sends persistent events to the durable `student-id.events.v1` RabbitMQ exchange and marks each row delivered after broker confirmation. See the [shared event contract](../../README.md#rabbitmq-event-contract) for payloads and routing keys.

## Storage and Lab 1 deployment

The public image is `sentientmoss/pad-moderation-service:<version>` ([published tags](https://hub.docker.com/r/sentientmoss/pad-moderation-service/tags)). To pin a release, set `IMAGE_TAG` in each terminal, for example `export IMAGE_TAG=0.1.2`. Leave `IMAGE_TAG` unset to use `latest`, which changes with new releases.

The API listens on container port `8000`. Keep PostgreSQL data in a named volume. Add a broker volume in the shared deployment if confirmed events must survive broker recreation. PostgreSQL outbox rows remain pending until the broker confirms them. The API creates its tables on startup; the publisher must run as a separate process from the same image.

Set these values in a local `.env`. Do not commit `.env`, tokens, or keys.

| Setting | Required value |
| --- | --- |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | Database password and `postgresql+psycopg://moderation:<password>@postgres:5432/moderation`. |
| `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_URL` | Broker credentials and `amqp://<user>:<password>@rabbitmq:5672/%2F`. URL-encode reserved password characters. |
| `JWT_PUBLIC_KEY_FILE`, `JWT_ISSUER`, `JWT_AUDIENCE` | Path to the mounted Player RS256 public key and values that match Player's issued access tokens. The command below mounts the key at `/run/secrets/player-public.pem`. |
| `SESSION_URL`, `APPLICANT_URL`, `CREDENTIAL_URL`, `UNIVERSITY_URL`, `RULES_URL`, `PLAYER_URL` | Reachable service base URLs on the deployment network. |
| `SESSION_SERVICE_TOKEN`, `APPLICANT_SERVICE_TOKEN`, `CREDENTIAL_SERVICE_TOKEN`, `UNIVERSITY_SERVICE_TOKEN`, `RULES_SERVICE_TOKEN`, `PLAYER_SERVICE_TOKEN` | Credentials accepted by each receiving service for its internal endpoint. |
| `MOCK_CONTRACT_FILE` | Empty when connecting real services. Set it only for a local test fixture. |

Set `JWT_ISSUER` and `JWT_AUDIENCE` to the claims in Player's issued access tokens. The later shared deployment needs these containers on one network. The listed names match the hosts in `DATABASE_URL` and `RABBITMQ_URL` above.

| Container | Image and startup | Storage and access |
| --- | --- | --- |
| `postgres` | `postgres:17-alpine`; create database and user `moderation`; wait for `pg_isready -U moderation -d moderation`. | Persist `/var/lib/postgresql/data` in a named volume such as `moderation_pg`. Do not publish port `5432` to clients. |
| `rabbitmq` | `rabbitmq:4-management-alpine`; set `RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS`; wait for `rabbitmq-diagnostics -q ping`. | Persist `/var/lib/rabbitmq` if confirmed messages must survive broker recreation. Keep AMQP port `5672` and the management port private. |
| `moderation` | Run the versioned image after PostgreSQL is healthy. The image's default command starts the API and creates its tables. | Container port `8000`; bind it to `127.0.0.1:8008` for a local check. Mount the Player public key read-only. |
| `publisher` | Run the same image with command `python -m moderation.publisher` after PostgreSQL and RabbitMQ are healthy. | Use the same `DATABASE_URL` and `RABBITMQ_URL` as the API. No public port. |

To start the published API against running dependencies, set `TEAM_NETWORK` to their Docker network name. Put `.env` and `player-public.pem` in the current directory. Make the public key readable by the image's non-root user, UID `65532`. Set `MOCK_CONTRACT_FILE` to an empty value for real upstreams.

```sh
docker pull "sentientmoss/pad-moderation-service:${IMAGE_TAG:-latest}"
docker run --rm --network "$TEAM_NETWORK" --env-file .env \
  -e JWT_PUBLIC_KEY_FILE=/run/secrets/player-public.pem \
  -v "$PWD/player-public.pem:/run/secrets/player-public.pem:ro" \
  -p 127.0.0.1:8008:8000 "sentientmoss/pad-moderation-service:${IMAGE_TAG:-latest}"
```

Run the publisher in another terminal with the same `.env` and network:

```sh
docker run --rm --network "$TEAM_NETWORK" --env-file .env \
  "sentientmoss/pad-moderation-service:${IMAGE_TAG:-latest}" python -m moderation.publisher
```

`curl -fsS http://127.0.0.1:8008/healthz` checks the API process, not upstream access or event consumption. Configure the six upstreams and RabbitMQ consumers before testing a live decision. The shared Compose file is a separate team task.

To seed an empty Moderation database, run the seed module shipped in the public image on the same network:

```sh
docker run --rm --network "$TEAM_NETWORK" --env-file .env \
  "sentientmoss/pad-moderation-service:${IMAGE_TAG:-latest}" python -m moderation.seed
```

The seed command inserts one sample ban and leaves existing data unchanged. The [Moderation Postman collection](../../postman/moderation-service.json) tests decisions, bans, discipline, idempotency, and dependency failures. Supply valid local Bearer tokens in Postman; the collection contains none.
