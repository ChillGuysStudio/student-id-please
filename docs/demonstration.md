# Demonstrate and verify the stack

This guide starts the two-replica stack on a laptop and runs the verification suite against it. Each suite maps to one or more course grades from 3 to 10.

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

	The command returns when every container is running, and those with a health check report healthy.

4. Seed the University Record catalog once. Without it, starting a session returns `409 DEPENDENCY_REJECTED`:

	```sh
	python3 scripts/seed_university_catalog.py
	```

	On a fresh stack the script prints `University catalog: 69 created, 0 already present, 0 failed (of 69)`. Later runs print `0 created, 69 already present`.

To stop the stack and keep its data, run `docker compose down`. Never add `--volumes` to a stack you want to keep.

## Run the verification suite

Install [uv](https://docs.astral.sh/uv/). The script lists its own dependencies, so `uv run` fetches `rich` and `websockets` for the run and installs nothing globally.

```sh
uv run scripts/verify.py
```

With no arguments, the script prints a menu of suites with their grade, description, and expected duration. Choose a suite, then one case or all of its cases. The same runs work without the menu:

```sh
uv run scripts/verify.py list
uv run scripts/verify.py status
uv run scripts/verify.py scaling up-down
uv run scripts/verify.py all --yes
```

A passing `all` run ends with a summary table in which every suite shows `pass`. The `breaker` suite takes about two minutes for each caller, so `all` takes about 15 minutes.

| Option | Effect |
| --- | --- |
| `--yes` | Run cases that change the stack without asking. |
| `--verbose` | Print every captured log line. Without it, each step shows at most four lines, and lines that differ only in numbers or IDs merge into one line with a `×N` count. The JSON and Markdown reports keep every line. |
| `--quiet` | Print failures and the summary table only. |
| `--root DIR` | Read `.env`, `.local/stack/`, and `.local/postman/` from `DIR`. The default is this repository. |

Before it runs anything, the script prints the Compose project, the Gateway URL, how many instances are ready, and a run ID. If the stack is down, it prints the command that starts it instead.

Each step prints a check mark or a cross with its duration. Below the step, the script prints the container log lines from the step's time window. Each line names the service and the replica, so you can see which replica served each request.

A case that changes the stack prints one line that says what it changes and how it restores the stack, then asks `Run? [Y/n]`. The restore runs when the case ends, including after Ctrl-C.

A run writes `report.json` and `report.md` to `.local/verify/<run-id>/`. The run ID labels all test data and derives every idempotency key. The suite never deletes test data and never prints a secret.

### Demo players

The suites sign in as the three demo players from the newest `.local/postman/run-*/private-environment.json`. If none exists, the script runs `./scripts/run_newman.sh` first, which registers three players. The `gameplay guided` case registers a new set on every run.

### Watch the logs

Follow the stack logs, filtered to requests, breaker events, removals, alerts, and Discord receipts, with the Compose colors:

```sh
scripts/watch-logs.sh
```

To see the suite and the logs side by side, install `tmux` first, for example with `sudo apt install tmux`. The script opens tmux with the suite on the left and the logs on the right. Pass the same arguments you would give `verify.py`:

```sh
scripts/verify-demo.sh scaling --yes
```

## What each suite shows

| Suite | Grade | What it shows | Changes the stack |
| --- | --- | --- | --- |
| `http` | 3 | Four anonymous requests through Newman. Gateway is live, the private routes are hidden, and a protected Player read needs a token. | No |
| `status` | 3 | Every instance returns 200 for its authenticated status and 401 for a wrong token. Logs exist, none floods, and none holds a secret. | No |
| `registry` | 4 | Every instance is registered and ready, leases and health checks keep advancing, and the running images match `docker compose config --images`. | No |
| `scaling` | 5 | Raising `SESSION_REPLICAS` to 3 starts a third replica that registers and serves. Returning to 2 removes it from routing. | Yes. It edits `.env` and restores it. |
| `gameplay` | 6 | The guided Newman requests 01 to 27, a whole shift served by both Session and Moderation replicas, and chat between two Discord DMs replicas. | No fault. It creates labelled test data. |
| `round-robin` | 6 | Twelve reads alternate between the two replicas, six each, read from the access logs. | No |
| `race` | 6 | The same first write sent to both replicas at once leaves one durable record and one idempotency record. | The Applicant and Credential cases grant admin to a demo player and revoke it. |
| `breaker` | 7 and 10 | A caller opens its breaker after three failed Gateway hops inside the window. Discovery removes the Gateway, and recovery reactivates it. | Yes. It blocks one caller from the Gateway and restores it. |
| `alerts` | 8 and 9 | Real load makes the Gateway critical and refuse the next request with `503 TASK_LIMIT_EXCEEDED`. Discovery logs `critical_load` and `load_recovered`, and Discord receives both. | Yes. It holds connections open and closes them. |

The grades come from the course requirements. Grades 1 and 2 cover the architecture, contracts, and flows in [architecture](architecture.md), [flows](flows.md), and the [contracts](contracts/api.md).

To see what the suite cannot prove, read [verification limits](architecture.md#verification-limits).

## Check the repository

These checks cover the repository tools and links. They do not need a running stack:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 .github/scripts/check_docs.py
docker compose config --quiet
```

Pass `--quiet` to `docker compose config`. Without it, the command prints resolved credentials.

Read the contracts for the behavior behind each grade: [resilience](contracts/resilience.md) for Discovery, replicas, breakers, and alerts, and [HTTP conventions](contracts/http.md) for idempotency, retries, and task limits.
