# Set up development

CPR checks require Git, Python 3, and a shell. Docker is needed only to run service images. Private source checkout is optional.

## Clone CPR

```sh
git clone --no-recurse-submodules --branch dev https://github.com/ChillGuysStudio/student-id-please.git
cd student-id-please
```

## Run public images

Compose sends client REST through the public gateway on `127.0.0.1:8080`. Domain services use the internal gateway at `http://gateway:8083`, which has no host port. DMs exposes `127.0.0.1:8009` for the direct WebSocket returned by negotiation. Chat frames and database connections do not pass through the gateway.

Player `2.0.1` and Session `2.0.0` now use the [confirmed owner settings](player-session-runtime.md). The [current local runtime results](player-session-compose-results.md) show protected Player and Session requests passing through Gateway. Direct chat remains blocked. The [earlier disposable results](lab2-runtime.md) describe the legacy-image run, not the current images. Do not restore bearer forwarding or direct peer URLs when authorization fails.

1. Choose an explicit published gateway version or digest. Set `GATEWAY_IMAGE` to that reference. A local image is test-only, not a published release.
2. Use Python 3 and OpenSSL to generate fresh development keys and configuration:

	```sh
	python3 scripts/prepare_lab2.py --gateway-image "$GATEWAY_IMAGE"
	```

	The command creates ignored `.env` and `.local/lab2/` files without printing credentials. It refuses existing configuration. The generated Player key matches the gateway's pinned public key. Receiver-hop credentials differ from caller credentials. Keys are for local development only.

3. Select source-matched service versions in `.env`. The generator selects Player `2.0.1` and Session `2.0.0`. It pins the gateway public key and configures their receiver-hop credentials through `SERVICE_TOKENS.gateway`. Session uses `GATEWAY_URL` and its distinct initiating credential. Keep `.env` and `.local/` out of commits.
4. Validate Compose without printing resolved values:

	```sh
	docker compose config --quiet
	```

5. Pull the public images:

	```sh
	docker compose pull
	```

6. Start the deployment:

	```sh
	docker compose up -d --wait
	```

7. Inspect container status:

	```sh
	docker compose ps
	```

Service and helper containers use `pull_policy: always`, so startup refreshes the
selected image tag. Tags default to `latest`; the existing version variables can
select a lab/version tag for debugging. Docker selects the host's native platform
from each published manifest; no AMD64 platform is forced. If the image lacks a
matching platform, its owner must publish that platform rather than rely on
runtime emulation.

Java services select their current gateway adapters. Moderation and DMs use `AUTH_MODE=gateway`. Session's existing peer settings select HTTP, not mocks. `scripts/start_broker.sh` creates the two broker users required by the Applicant and Credential constructors. It does not create exchanges or queues. The default `studentid` account and existing broker volume remain.

Inspect Java startup and make protected public gateway calls after `--wait`. A running container without a health check can still restart before its API binds. Do not dump `docker compose config`, service environments, or unsanitized logs into evidence. Use `docker compose config --quiet`.

Run `docker compose down` to stop the stack and keep its data. Add `--volumes` only for a disposable project whose stored data you intend to delete. The source snapshot override used for local testing stays under ignored `.local/lab2/`; it does not change CPR's service pointers or establish public-image publication.

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
