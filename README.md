# Student ID, please

Student ID, please is a game about moderating a university Discord server. Junior Moderators inspect assigned university records and share findings in chat. The Moderator compares those findings with an applicant's claims and credentials, then accepts, rejects, flags, or bans the applicant.

The Common Project Repository, or CPR, contains the shared design, integration contracts, deployment, and service release pointers. Service implementations live in private repositories. Their container images are public.

## Architecture

Eight domain services own separate data. They communicate through REST, RabbitMQ events, and WebSocket chat. The gateway and Message Broker sections below describe the current topology and the planned change.

The diagram below shows the gateway, Service Discovery, the domain services, and their storage. Its editable source is [`docs/architecture.drawio`](docs/architecture.drawio). Green dashed arrows are the Discovery calls: registration, lease renewal, health probes, and Gateway removal reports. Client and service REST pass through the gateway. Live chat uses a direct client-to-Discord DMs WebSocket. Replicas register with Discovery, and Discovery probes them. This drawing does not show the Message Broker yet. The [architecture diagram](docs/architecture.md) shows the Broker and its planned connections.

<img src="docs/architecture.png" alt="Architecture diagram: Gateway, Service Discovery, the Java and Python services with their databases, and RabbitMQ" width="1080"/>

[Architecture](docs/architecture.md) explains ownership and technology choices. The [demonstration guide](docs/demonstration.md) shows how to start the stack and run the verification suite. [Game flows](docs/flows.md) describe a shift. [Integration principles](docs/integration.md) explain mocked and integrated deployments.

## Gateway

The selected gateway is shared Go infrastructure, separate from the eight domain services. All client-to-service REST traffic uses its public listener. All service-to-service REST traffic uses its internal listener, which is not publicly exposed. The gateway validates client identity, routes requests, and bounds task duration and concurrency. Domain services retain business authorization and data ownership.

Realtime negotiation uses REST through the gateway and returns a direct Discord DMs WebSocket URL. Clients connect to Discord DMs for the upgrade and chat frames. The gateway does not relay frames. Chat tickets, permissions, Redis delivery, and stored history belong to Discord DMs.

RabbitMQ events and service-owned storage connections are not REST routing paths and do not pass through the gateway.

## Message Broker

The Message Broker is shared Go infrastructure in the private `ChillGuysStudio/message-broker-service` repository. Its released image, `maxnoragami/message-broker-service:4.0.0`, serves only `GET /health` on port 8080. The current Compose configuration does not run it, and it handles no traffic yet.

The Broker will take over service-to-service dispatch, replica load balancing, and breakers from the gateway. A targeted request names its destination service. The gateway forwards it to the Broker, which delivers it to one ready replica of that service. A topic event names a topic, not its recipients. The publisher sends it without knowing who subscribes, and each subscribing service receives one copy. Services declare their topics when they register with Discovery.

Client authentication, direct Discord DMs WebSockets, event schemas, and domain ownership stay unchanged. [Message Broker boundaries](docs/architecture.md#message-broker) define the private listener, request correlation, deadlines, and authentication.

[`docs/releases/services.json`](docs/releases/services.json) records the released version, source commit, and image digest of each service. [Gateway authorization](docs/architecture.md#gateway-authorization) describes identity checks and service permissions; the [guided Postman demo](postman/GUIDED-DEMO.md) covers real Gateway HTTP flows and bounded concurrent tasks.

## Team and services

| Developer | Owned services | Stack | Source profile |
| --- | --- | --- | --- |
| Chicu Andrei | Moderation, Discord DMs | Python, FastAPI | `andrei` |
| Vremere Adrian | Applicant, Credential | Java, Spring Boot | `adrian` |
| Alexei Maxim | Server Rules, University Record | Java, Spring Boot | `alexei` |
| Cebotari Alexandru | Player, Session | Python, FastAPI | `alexandru` |

[Service references](docs/services/README.md) list public images and integration settings. The [submodule configuration](.gitmodules) lists private source repositories. The gateway is shared infrastructure, separate from each developer's two domain services.

## Start work

Read [CONTRIBUTING.md](CONTRIBUTING.md) for CPR rules. Follow [the development guide](docs/development.md) to run public images, install hooks, or check out only your two services. The default setup does not fetch private source.

## Policy changes

Rules introduced by updates to this README or the other project documentation apply after those updates are merged. Earlier commits, branches, pull requests, merges, tags, releases, and other repository actions are judged by the rules in effect when they occurred. Actions that followed the previous README and documentation are not violations of rules introduced later. Work on an open pull request is assessed when that pull request merges. Convention breaks before merge, and anything on a pull request closed without merging, are not violations.

## Documentation

- [Demonstration guide](docs/demonstration.md)
- [HTTP conventions](docs/contracts/http.md)
- [Discovery and resilience contract](docs/contracts/resilience.md)
- [Domain types](docs/contracts/domain.md)
- [Service APIs](docs/contracts/api.md)
- [Case initialization](docs/contracts/cases.md)
- [Simulation data](docs/contracts/simulation.md)
- [RabbitMQ events](docs/contracts/events.md)
- [Release procedure](docs/releases.md)
- [GitHub checks and permissions](docs/github.md)

The [project board](https://github.com/orgs/ChillGuysStudio/projects/2) tracks team tasks.
