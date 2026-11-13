# Demonstrate the stack

This guide starts the stack on a laptop, scales a domain service with Compose, and follows the logs while replicas join and leave. Every step uses plain `docker` and `docker compose` commands.

The diagram in [architecture](architecture.md) shows the replicated topology.

## Start the stack

1. Generate the ignored `.env` and `.local/stack/` files. The command refuses to overwrite existing configuration and prints no credentials:

	```sh
	python3 scripts/setup.py
	```

2. To receive Discord alerts, set `DISCOVERY_DISCORD_WEBHOOK_URL` in `.env`. Leave it empty to send none.
3. Start the stack and wait until every container is healthy:

	```sh
	docker compose up -d --wait
	```

	The command returns when every container is running and every container with a health check reports healthy. Each domain service starts two replicas.

4. Seed the University Record catalog once. Without it, starting a session returns `409 DEPENDENCY_REJECTED`:

	```sh
	python3 scripts/seed_university_catalog.py
	```

	On a fresh stack the script prints `University catalog: 69 created, 0 already present, 0 failed (of 69)`. Later runs print `0 created, 69 already present`.

To stop the stack and keep its data, run `docker compose down`. Never add `--volumes` to a stack you want to keep.

## Scale a service

The domain services are `player`, `session`, `applicant`, `credential`, `university-record`, `server-rules`, and `moderation`. Each one scales with `--scale`. A new container generates its own instance ID, registers its own container address with Discovery, and receives traffic after its first ready probe. The [resilience contract](contracts/resilience.md) defines this identity.

1. Raise Applicant to four replicas. `--no-deps` leaves the other services untouched:

	```sh
	docker compose up -d --no-deps --scale applicant=4 applicant
	```

2. List the Applicant containers and their health:

	```sh
	docker compose ps applicant
	```

3. In a second terminal, follow Gateway, Discovery, and Applicant:

	```sh
	docker compose logs -f --tail 50 --timestamps gateway discovery applicant
	```

	Discovery logs each new registration. Gateway's `dispatch` records name the `target_instance_id`, so you can see requests spread across the four replicas. To follow one replica, pass its index, for example `docker compose logs -f --index 2 applicant`.

4. Stop one replica. Copy a container ID from the `docker compose ps applicant` output, then run:

	```sh
	docker stop <container-id>
	```

	The replica removes its own instance with reason `shutdown` before its listener closes. Discovery stops routing to it at once, and the instance never needs reactivation. A container that dies without a graceful stop leaves routing when its lease expires.

5. Return Applicant to two replicas:

	```sh
	docker compose up -d --no-deps --scale applicant=2 applicant
	```

	Compose removes the extra containers. Each one deregisters on its way out.

The same commands work for every domain service listed above. Gateway, Discovery, and the Moderation outbox publisher run as one instance each.

## Use the two Discord DMs services

Clients open the chat WebSocket directly on a host port that the DMs replica advertises. Scaled replicas cannot share one host port, so DMs runs as two explicit services instead of a scaled one:

| Service | Host port | Advertised WebSocket |
| --- | --- | --- |
| `discord-dms-1` | `DMS_PORT`, default `8009` | `ws://localhost:8009` |
| `discord-dms-2` | `DMS_PORT_2`, default `8010` | `ws://localhost:8010` |

Gateway picks a ready DMs instance for each negotiation and returns that instance's WebSocket URL. Both services share the ticket secret, PostgreSQL history, and Redis delivery, so players connected to different replicas exchange messages. To take one out of new negotiations, run `docker compose stop discord-dms-2`. Start it again with `docker compose start discord-dms-2`.

## Run the HTTP checks

The Postman collections run through the public Gateway. The [guided demo](../postman/GUIDED-DEMO.md) walks through registration, a shift, overload, and the log download, in Postman or with Newman:

```sh
./scripts/run_newman.sh
./scripts/run_newman.sh --with-overload
```

[HTTP checks](../postman/HTTP-CHECKS.md) describes the read-only public and operator folders.

## Check the repository

These checks cover the repository tools and links. They do not need a running stack:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
docker compose config --quiet
```

Pass `--quiet` to `docker compose config`. Without it, the command prints resolved credentials.

Read the contracts for the behavior behind each grade: [resilience](contracts/resilience.md) for Discovery, replicas, breakers, and alerts, and [HTTP conventions](contracts/http.md) for idempotency, retries, and task limits.
