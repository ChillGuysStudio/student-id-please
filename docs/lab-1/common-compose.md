# Common Compose deployment: Player and Session portion

This branch starts the shared Lab 1 Compose deployment. The current file contains Player, Session, their separate PostgreSQL databases, Redis, and RabbitMQ. The other service owners can add their six services and MongoDB to the same `compose.yaml`. Session uses typed mocks for those services until their containers and internal credentials are wired in.

The Compose file uses published versioned images for Player and Session. It does not build from private Dockerfiles. PostgreSQL data, RabbitMQ data, and Player's RSA signing key use named volumes. Redis is a cache and has no durable volume. Only the Player and Session HTTP ports are published, bound to the host loopback address.

## Configure and start the current portion

From the CPR root, copy `.env.example` to `.env` and fill the five blank values with distinct random URL-safe secrets. Python's `secrets.token_hex(24)` can generate each value. `.env` is ignored by Git. Do not commit it or paste its values into issues or PRs.

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose pull
docker compose up -d --wait
docker compose ps
```

Player listens on `127.0.0.1:8001`; Session listens on `127.0.0.1:8002`. Their `/health` and `/ready` endpoints should return `200`. Session uses `PLAYER_MODE=http` and calls Player by its Compose service name. `EXTERNAL_SERVICES_MODE=mock` keeps unavailable teammate dependencies contract-compatible. After the [Player and Session verification PR](https://github.com/ChillGuysStudio/student-id-please/pull/49) merges, its separate Postman collections can exercise the pair.

Run `docker compose down` to stop the containers while retaining named volumes. The complete team deployment must add the remaining services and their storage, switch Session to real external HTTP integrations, share the appropriate service credentials, and verify that durable data survives container recreation.
