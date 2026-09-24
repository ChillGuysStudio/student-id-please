# Verify the Lab 1 Player and Session services

This CPR branch contains separate Postman collections for Player and Session. The common Compose deployment and its database volumes will be delivered in a separate team PR. To start a service now, follow its private repository run guide: [Player](https://github.com/Tirppy/student-id-player-service/blob/feat/lab-1/player-service/docs/running.md) or [Session](https://github.com/Tirppy/student-id-session-service/blob/feat/lab-1/session-service/docs/running.md).

## Prerequisites

- Start Player on port `8001`. The Player collection uses authenticated internal event fixtures, so configure Player's `SERVICE_TOKENS` JSON map with `session` and `moderation` entries.
- Start Session on port `8002` with `PLAYER_MODE=http`, `PLAYER_URL` pointing to Player, and `EXTERNAL_SERVICES_MODE=mock`. Configure Session's `SERVICE_TOKENS` JSON map with a `moderation` entry. Session's outgoing token must match Player's `session` token.
- Give the test runner the matching `SESSION_SERVICE_TOKEN` and `MODERATION_SERVICE_TOKEN`. Set them as environment variables or in an ignored CPR `.env`. Never commit their values or a populated Postman environment.
- For the Docker-based Newman runners, have a working Docker Engine. The Python helpers use Python 3.12. The two collections can also be imported directly into Postman.

Each service can use SQLite for an isolated check. PostgreSQL persistence, RabbitMQ delivery, and the common eight-service deployment belong to the later team deployment PR. The Session collection works with its typed external mocks. The optional concurrency script also verifies Player XP through RabbitMQ, so that script requires a running broker shared by Player and Session.

## Player collection

Import [`postman/player-service.json`](../postman/player-service.json) into Postman. Set `player_url`, `session_token`, and `moderation_token` in a local environment. The default `player_url` is `http://localhost:8001`. Run the whole collection in order.

It creates three players, tests authentication, friendships and team membership, applies a synthetic `ShiftEnded` event, verifies that a replay adds no extra XP, applies and replays a disciplinary event, then tests the cleanup and refresh-token endpoints. It calls only Player endpoints. The event fixtures use the documented internal adapter and service credentials.

To run it through Docker without installing Postman, set `SESSION_SERVICE_TOKEN` and `MODERATION_SERVICE_TOKEN` and run:

```powershell
python tools/player-service/run_postman.py
```

The runner sends tokens through standard input to a temporary Newman environment inside its container. By default, the container calls Player through `host.docker.internal:8001`. If Player runs on a Docker network, set `POSTMAN_DOCKER_NETWORK` to that network's name and `PLAYER_URL` to Player's URL on it, such as `http://player:8001`.

## Session collection

Import [`postman/session-service.json`](../postman/session-service.json) into Postman. Set `session_url`, `moderation_token`, `team_id`, `moderator_id`, `junior1_id`, `junior2_id`, `moderator_token`, `junior1_token`, and `junior2_token` in a local environment. Create that three-player team through Player first, or use the runner below to do the setup automatically. The collection's default `session_url` is `http://localhost:8002`.

The collection contains only Session endpoints. It tests lobby creation and deletion, joining and roles, start checks, the pinned university snapshot, a pending case, readiness, context, duplicate scoring, and shift end. It does not require the Player collection to run first. The scoring event is an explicit Moderation fixture because that service is not connected in this Lab 1 check.

To run it through Docker:

```powershell
python tools/session-service/run_postman.py
```

The runner needs `MODERATION_SERVICE_TOKEN`. It first calls Player from the host to create three players, friendships, and a team, then sends their IDs and access tokens through standard input to Newman. Set `PLAYER_SETUP_URL` if Player is not reachable from the host at `http://localhost:8001`. Set `POSTMAN_DOCKER_NETWORK` and `SESSION_URL` if Session is on a Docker network instead of reachable through `host.docker.internal`.

## Concurrent Session requests

With Player, Session, and RabbitMQ running together, set `MODERATION_SERVICE_TOKEN` and run:

```powershell
python tools/session-service/check_concurrency.py
```

The script creates a separate team and shift. It sends eight simultaneous retries for one case, eight copies of one scoring event, and eight end requests. It expects one case, one counted decision, and one 10-XP award through RabbitMQ. `PLAYER_URL` and `SESSION_URL` can override its host-side defaults of `http://localhost:8001` and `http://localhost:8002`.

These checks create test records. The later team deployment PR will supply image-based startup and container-recreation checks for persistent database volumes and the Player signing key.
