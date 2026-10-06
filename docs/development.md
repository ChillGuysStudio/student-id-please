# Set up development

## Run public images

1. Clone CPR without private source:

	```sh
	git clone --no-recurse-submodules git@github.com:ChillGuysStudio/student-id-please.git
	cd student-id-please
	```

2. Copy the configuration template:

	```sh
	cp .env.example .env
	```

3. Fill every blank in `.env` with a distinct URL-safe value. Keep the file out of commits.
4. Validate the Compose configuration:

	```sh
	docker compose config --quiet
	```

5. Pull the public images:

	```sh
	docker compose pull
	```

6. Start the deployment:

	```sh
	docker compose up -d
	```

7. Inspect container status:

	```sh
	docker compose ps
	```

When using mocks, test each real caller and handler with contract fixtures. When connecting real peers, verify credentials, payloads, and event delivery as described in [integration principles](integration.md).

Use [the service references](services/README.md) for local ports and image configuration. Run `docker compose logs <service>` to inspect a failed container. Run `docker compose down` to stop the stack and keep its data. Do not add `--volumes` unless you intend to delete the stored data.

## Install CPR hooks

Python 3 and Git are required. Run:

```sh
sh scripts/install-hooks.sh
```

The installer sets this clone's `core.hooksPath` to `.githooks`. If you already use another hook directory, inspect it before running the installer with `--force`.

Run the local repository checks with:

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

Choose your profile from the [team table](../README.md#team-and-services). For Andrei's services, run:

```sh
python3 scripts/services.py init andrei
```

The command disables recursive submodule operations in this clone, marks other submodules inactive, and initializes only Moderation and Discord DMs. It checks out the SHAs recorded by CPR. It does not probe the other private repositories or the gateway.

To update the same two checkouts after a CPR pointer change, run:

```sh
python3 scripts/services.py update andrei
```

The command refuses dirty service worktrees. It also refuses to detach a service task branch when the requested pin differs. Finish that work or switch the service to a detached checkout before updating.

Read each private repository's own workflow before starting implementation work. CPR submodules normally have detached HEADs. Do not assume a CPR branch also creates a service branch.

For a manual update, specify both paths and omit `--recursive`:

```sh
git -c submodule.recurse=false -c fetch.recurseSubmodules=false submodule update --init -- moderation-service discord-dms-service
```

Avoid bare `git submodule update --init`, recursive cloning, and `--remote` updates. An ordinary CPR fetch or pull must not require access to every service.
