# Run the Lab 1 pair

## Start the deployment

Use Docker Desktop in Linux-container mode or Docker Engine with Compose. Install Python 3.12 for the local configuration and verification helpers. Keep ports `8001` and `8002` free.

Run these commands from the common repository:

```powershell
python tools/configure_demo.py
docker compose pull
docker compose up -d --wait --wait-timeout 180
docker compose ps
```

The helper creates `.env` with random database, broker, and service credentials. It refuses to overwrite an existing file. Git ignores this file. Keep the same credentials when restarting an existing database volume.

All six containers must become healthy. Open Player at `http://localhost:8001/docs` and Session at `http://localhost:8002/docs`. Player and Session use separate PostgreSQL containers. Session uses real Player calls, Redis, RabbitMQ, and explicit mocks for the missing teammate services.

`compose.yaml` uses versioned Docker Hub images. It has no `build:` entries and does not need access to private source repositories. The first download may take several minutes.

## Test with Postman

Import `postman/lab1.postman_collection.json` into Postman. Create a local environment with `moderation_token` set to `MODERATION_SERVICE_TOKEN` from your ignored `.env`. Keep the default Player and Session URLs. Run the whole collection with a 100 ms delay between requests.

The collection creates three players, forms a team, completes a shift, verifies RabbitMQ progression, applies a disciplinary fixture, and exercises cleanup operations. The negative requests verify authorization and state rules. Each run uses fresh account names. Do not commit an export containing populated tokens or passwords.

To run the same collection through Docker without installing Postman:

```powershell
python tools/run_postman.py
```

The helper passes local credentials to Newman through standard input. Newman prints request statuses and assertion results. A successful run reports zero failures.

## Verify concurrent requests

```powershell
python tools/check_concurrency.py
```

The script creates a separate demo team. It sends eight concurrent retries for a case, eight copies of a scoring event, and eight end-shift requests. It verifies one case, one counted decision, and one 10-XP award through RabbitMQ.

## Verify persistence

Run the Postman collection before this check so both databases contain records:

```powershell
python tools/check_persistence.py
```

This check stops and removes this Compose project's containers, then recreates them. It compares player IDs and XP, session states and totals, and the public signing key before and after recreation. It leaves the named volumes intact.

To stop the demonstration yourself, run `docker compose down`. Do not add `--volumes` unless you intend to delete the demo databases and signing key.

## Connect the rest of the team

The six teammate images and their runtime settings are not available yet. Ask each owner for their versioned public Docker Hub image, container port, required environment variables, and persistent storage requirements.

1. Add the six image variables and four dependency port variables required by `compose.team.yaml` to your local `.env`.
2. Create the six ignored `team-env/*.env` files named in that override.
3. Configure each teammate service's storage and broker access according to its owner's instructions. Add the required database services and volumes to the team deployment when those settings are known.
4. Set `TEAM_SESSION_SERVICE_TOKENS` to a JSON map with distinct tokens for the authorized service callers. Match the outgoing tokens configured by each owner.
5. Run the full configuration:

```powershell
docker compose -f compose.yaml -f compose.team.yaml config --quiet
docker compose -f compose.yaml -f compose.team.yaml up -d --wait
```

The override switches Session's external adapters to HTTP. Do not use the fixture-driven Postman outcome as proof of complete eight-service integration. The team must run and verify the real services together after supplying their configuration.

## Grading and review notes

The professor waived the build/run script, seed script, and 80% unit-test coverage criteria. The helpers here support configuration and verification. The collection creates demonstration data through the APIs, and no automatic database seed is required.

Source changes go through task PRs into `dev`. Peer approval takes place in the common repository. After the private service PRs merge, update the common submodule pointers to the merged commits. Release PRs go from `dev` to `main`; create the final lab tag only on `main`.
