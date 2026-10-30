# Set up development

CPR checks require Git, Python 3, and a shell. Docker is needed only to run service images. Private source checkout is optional.

The [discovery and resilience contract](contracts/resilience.md) defines configuration names and service acceptance cases for replicas and Discovery. The [demonstration guide](demonstration.md) shows how to start the stack and run the verification suite on a prepared laptop.

## Clone CPR

```sh
git clone --no-recurse-submodules --branch dev https://github.com/ChillGuysStudio/student-id-please.git
cd student-id-please
```

## Run public images

Compose sends client REST through the public gateway on `127.0.0.1:8080`. Domain services use the internal gateway at `http://gateway:8083`, which has no host port. DMs exposes `127.0.0.1:8009` for the direct WebSocket returned by negotiation. Chat frames and database connections do not pass through the gateway.

The stack runs Discovery, Gateway, and `REPLICAS` replicas (default 2) of each domain service. Every service image defaults to `latest` in `compose.yaml`, for example `${PLAYER_IMAGE:-tirppy/student-id-player-service:latest}`. To pin a version, set the matching `*_IMAGE` key in `.env` to `owner/repo:version`, for example `PLAYER_IMAGE=tirppy/student-id-player-service:3.0.0`. An unset or empty key means `latest`. [`releases/services.json`](releases/services.json) lists the released versions. `scripts/replicas.py` turns `REPLICAS` into the ignored `compose.replicas.yaml`, and `.env` loads it through `COMPOSE_FILE`. The Compose project is `student-id-please`.

1. Use Python 3 and OpenSSL to generate fresh development keys and configuration:

	```sh
	python3 scripts/setup.py
	```

	The command creates ignored `.env` and `.local/stack/` files without printing credentials. It refuses existing configuration. The generated Player key matches the gateway's pinned public key. Receiver-hop credentials differ from caller credentials. Keys are for local development only.

2. Review the generated `.env`. To pin an image version, add the matching `*_IMAGE` key. To change replica counts, set `REPLICAS` or `<SERVICE>_REPLICAS`, then run `python3 scripts/replicas.py`. The generator also pins the gateway public key and configures receiver-hop credentials through `SERVICE_TOKENS.gateway`. Copy your Discord webhook into `DISCOVERY_DISCORD_WEBHOOK_URL` if you want real alerts. Keep `.env` and `.local/` out of commits.
3. Validate Compose without printing resolved values. `scripts/setup.py` also generates the instance IDs and control tokens that `.env.example` lists:

	```sh
	docker compose config --quiet
	```

4. Pull the public images:

	```sh
	docker compose pull
	```

5. Start the deployment:

	```sh
	docker compose up -d --wait
	```

6. Seed the University Record reference catalog. Without it, starting a session fails with `409 DEPENDENCY_REJECTED`. Run the command once on a fresh stack:

	```sh
	python3 scripts/seed_university_catalog.py
	```

	The script registers a local seed player, stores its credentials in `.local/stack/seed-admin.json`, grants it admin for the import, and revokes admin afterwards. It prints the number of created, already present, and failed entries. Running it again is safe.

7. Inspect container status:

	```sh
	docker compose ps
	```

Service and helper containers use `pull_policy: always`. Docker selects the host's native platform
from each published manifest; no AMD64 platform is forced. If the image lacks a
matching platform, its owner must publish that platform rather than rely on
runtime emulation.

Each bind mount ends in `:ro,z`. On an SELinux host such as Fedora, `z` makes Docker relabel the file so containers can read it. Hosts without SELinux ignore the option. Use lowercase `z`, because several services mount the same key files.

Java services select their current gateway adapters. Moderation and DMs use `AUTH_MODE=gateway`. Session's existing peer settings select HTTP, not mocks. `scripts/start_broker.sh` creates the two broker users required by the Applicant and Credential constructors. It does not create exchanges or queues. The default `studentid` account and existing broker volume remain.

Inspect Java startup and make protected public gateway calls after `--wait`. A running container without a health check can still restart before its API binds. Do not dump `docker compose config`, service environments, or unsanitized logs into evidence. Use `docker compose config --quiet`.

Run `docker compose down` to stop the stack and keep its data. Add `--volumes` only for a disposable project whose stored data you intend to delete.

## Verify the stack

With the stack running, open the menu of checks for the course grades. It needs [uv](https://docs.astral.sh/uv/), which loads `rich` and `websockets` for the run without installing anything globally:

```sh
uv run scripts/verify.py
```

To run every suite without prompts, use `uv run scripts/verify.py all --yes`. Cases that change the stack warn you first and always restore it. Reports go to `.local/verify/<run-id>/`. The [demonstration guide](demonstration.md) explains each suite.

## Install CPR hooks

Python 3 and Git are required. Run:

```sh
sh scripts/install-hooks.sh
```

The installer sets this clone's `core.hooksPath` to `.githooks`. If you already use another hook directory, inspect it before running the installer with `--force`.

Run the local repository checks with the commands below. They test CPR workflow tools, not service code or APIs.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
```

To check the commits on your task branch, fetch CPR without submodules, then run:

```sh
git fetch --no-recurse-submodules origin dev
python3 .github/scripts/check_commits.py origin/dev HEAD
```

## Check out your two services

Replace `PROFILE` with `andrei`, `adrian`, `alexei`, or `alexandru` from the [team table](../README.md#team-and-services):

```sh
python3 scripts/services.py init PROFILE
```

The profile settings are stored in this clone's `.git/config`. They do not change other clones, `.gitmodules`, or CPR's recorded service commits. People using the same clone share these settings.

The command disables recursive Git operations, marks other submodules inactive, and checks out only your two services at the commits recorded by CPR. It does not contact the other private repositories or delete their existing checkouts.

To make those two local checkouts match updated CPR pins, run:

```sh
python3 scripts/services.py update PROFILE
```

The command refuses dirty service worktrees. It also refuses to detach a service task branch when the requested pin differs. Finish that work or switch the service to a detached checkout before updating.

Read each private repository's own workflow before starting implementation work. CPR submodules normally have detached HEADs. Do not assume a CPR branch also creates a service branch.

For a manual update, specify both paths and omit `--recursive`:

```sh
git -c submodule.recurse=false -c fetch.recurseSubmodules=false submodule update --init -- moderation-service discord-dms-service
```

Avoid bare `git submodule update --init`, recursive cloning, and `--remote` updates. An ordinary CPR fetch or pull must not require access to every service.
