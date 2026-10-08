# Set up development

CPR checks require Git, Python 3, and a shell. Docker is needed only to run service images. Private source checkout is optional.

## Clone CPR

```sh
git clone --no-recurse-submodules --branch dev https://github.com/ChillGuysStudio/student-id-please.git
cd student-id-please
```

## Run public images

1. Copy the configuration template:

	```sh
	cp .env.example .env
	```

2. Fill every blank in `.env` with a distinct URL-safe value. Keep the file out of commits.
3. Validate the Compose configuration:

	```sh
	docker compose config --quiet
	```

4. Pull the public images:

	```sh
	docker compose pull
	```

5. Start the deployment:

	```sh
	docker compose up -d
	```

6. Inspect container status:

	```sh
	docker compose ps
	```

Services can run integrated or in mock mode.

Use [the service references](services/README.md) for local ports and image configuration. Run `docker compose logs <service>` to inspect a failed container. Run `docker compose down` to stop the stack and keep its data. Do not add `--volumes` unless you intend to delete the stored data.

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
