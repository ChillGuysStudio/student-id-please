# Student ID, please

Student ID, please is a game about moderating a university Discord server. Junior Moderators inspect assigned university records and share findings in chat. The Moderator compares those findings with an applicant's claims and credentials, then accepts, rejects, flags, or bans the applicant.

The Common Project Repository, or CPR, contains the shared design, integration contracts, deployment, and service release pointers. Service implementations live in private repositories. Their container images are public.

## Architecture

Eight domain services own separate data. They communicate through REST, RabbitMQ events, and WebSocket chat. Clients reach them through the gateway, and service-to-service REST goes through the Message Broker.

The diagram below shows the gateway, Service Discovery, the domain services, and their storage. Its editable source is [`docs/architecture.drawio`](docs/architecture.drawio). Green dashed arrows are the Discovery calls: registration, lease renewal, health probes, and Gateway removal reports. Live chat uses a direct client-to-Discord DMs WebSocket. Replicas register with Discovery, and Discovery probes them. This drawing predates the Message Broker and still shows service REST through the gateway. The [architecture diagram](docs/architecture.md) shows the current Broker connections.

<img src="docs/architecture.png" alt="Architecture diagram: Gateway, Service Discovery, the Java and Python services with their databases, and RabbitMQ" width="1080"/>

[Architecture](docs/architecture.md) explains ownership and technology choices. The [demonstration guide](docs/demonstration.md) shows how to start, scale, and observe the stack. [Game flows](docs/flows.md) describe a shift. [Integration principles](docs/integration.md) explain mocked and integrated deployments.

## Gateway

The selected gateway is shared Go infrastructure, separate from the eight domain services. All client-to-service REST traffic uses its public listener. The gateway validates client identity, applies the public policy, signs the receiver assertion, bounds task duration and concurrency, and sends each request to the Message Broker with its target service. Its control listener on `:8083` serves only health, status, and log export. Domain services retain business authorization and data ownership.

Realtime negotiation uses REST through the gateway, which pins ticket issuance to one DMs replica, and returns that replica's direct WebSocket URL. Clients connect to Discord DMs for the upgrade and chat frames. The gateway does not relay frames. Chat tickets, permissions, Redis delivery, and stored history belong to Discord DMs.

RabbitMQ events and service-owned storage connections are not REST routing paths and do not pass through the gateway or the Broker.

## Message Broker

The Message Broker is shared Go infrastructure in the private `ChillGuysStudio/message-broker-service` repository, with the public image `maxnoragami/message-broker-service`. Compose runs one instance as `message-broker` on port 8080 of the container network, with no host port.

The Broker owns service-to-service dispatch, service-call authorization, replica load balancing, and backend breakers. A targeted request names its destination service. Gateway sends public requests there with an explicit target, and domain services send every peer call there. The Broker authenticates the caller, signs the receiver assertion, selects one ready replica with round-robin, and writes a `dispatch` log record for each attempt. It reports breaker trips to Discovery.

Topic events and durable queues are planned. RabbitMQ still carries the domain events. Client authentication, direct Discord DMs WebSockets, event schemas, and domain ownership stay unchanged. The [Message Broker dispatch contract](docs/contracts/broker.md) defines the credentials, assertions, attribution, and logging.

[`docs/releases/services.json`](docs/releases/services.json) records the released version, source commit, and image digest of each service. [Gateway authorization](docs/architecture.md#gateway-authorization) describes identity checks and service permissions; the [guided Postman demo](postman/GUIDED-DEMO.md) covers real Gateway HTTP flows and bounded concurrent tasks.

## Team and services

| Developer | Owned services | Stack | Source profile |
| --- | --- | --- | --- |
| Chicu Andrei | Moderation, Discord DMs | Python, FastAPI | `andrei` |
| Vremere Adrian | Applicant, Credential | Java, Spring Boot | `adrian` |
| Alexei Maxim | Server Rules, University Record | Java, Spring Boot | `alexei` |
| Cebotari Alexandru | Player, Session | Python, FastAPI | `alexandru` |

[Service references](docs/services/README.md) list public images and integration settings. The [submodule configuration](.gitmodules) lists private source repositories. The gateway is shared infrastructure, separate from each developer's two domain services.

## Run the stack

The stack runs with plain Docker Compose commands. Each domain service starts two replicas. Every replica generates its own instance ID and registers its own container address with Discovery, so scaling needs no per-replica configuration:

```sh
python3 scripts/setup.py
docker compose up -d --wait
python3 scripts/seed_university_catalog.py
docker compose up -d --no-deps --scale applicant=4 applicant
docker compose ps applicant
docker compose logs -f --tail 50 --timestamps message-broker discovery applicant
docker stop <container-id>
docker compose up -d --no-deps --scale applicant=2 applicant
```

A stopped replica deregisters itself before it exits. Discord DMs is the one exception to `--scale`. Clients connect to each DMs replica's WebSocket on its own host port, so Compose defines two services, `discord-dms-1` on port `8009` and `discord-dms-2` on port `8010`. The [demonstration guide](docs/demonstration.md) explains each command.

## Start work

Read [CONTRIBUTING.md](CONTRIBUTING.md) for CPR rules. Follow [the development guide](docs/development.md) to run public images, install hooks, or check out only your two services. The default setup does not fetch private source.

## Policy changes

Rules introduced by updates to this README or the other project documentation apply after those updates are merged. Earlier commits, branches, pull requests, merges, tags, releases, and other repository actions are judged by the rules in effect when they occurred. Actions that followed the previous README and documentation are not violations of rules introduced later. Work on an open pull request is assessed when that pull request merges. Convention breaks before merge, and anything on a pull request closed without merging, are not violations.

## Documentation

- [Demonstration guide](docs/demonstration.md)
- [HTTP conventions](docs/contracts/http.md)
- [Discovery and resilience contract](docs/contracts/resilience.md)
- [Message Broker dispatch contract](docs/contracts/broker.md)
- [Domain types](docs/contracts/domain.md)
- [Service APIs](docs/contracts/api.md)
- [Case initialization](docs/contracts/cases.md)
- [Simulation data](docs/contracts/simulation.md)
- [Domain events](docs/contracts/events.md)
- [Message Broker queues and topics](docs/contracts/queues.md)
- [Release procedure](docs/releases.md)
- [GitHub checks and permissions](docs/github.md)

The [project board](https://github.com/orgs/ChillGuysStudio/projects/2) tracks team tasks.
