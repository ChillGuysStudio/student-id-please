# Student ID, please

Student ID, please is a game about moderating a university Discord server. Junior Moderators inspect assigned university records and share findings in chat. The Moderator compares those findings with an applicant's claims and credentials, then accepts, rejects, flags, or bans the applicant.

The Common Project Repository, or CPR, contains the shared design, integration contracts, deployment, and service release pointers. Service implementations live in private repositories. Their container images are public.

## Architecture

Eight domain services own separate data. Clients reach them with REST through the gateway, and the gateway sends each client request to the Message Broker over REST. Service-to-service calls and topic events are typed gRPC on port `50051`, and they also go through the Broker. Chat uses WebSockets through the Discord DMs proxy.

The diagram below shows the client paths, the gateway, the Message Broker, Service Discovery, the domain services, their storage, and monitoring. Its editable source is [`docs/architecture.drawio`](docs/architecture.drawio). Blue arrows are client REST: the gateway sends each targeted request to the Broker, which forwards it to one replica of the owning service. Green arrows are gRPC peer calls and dispatch. Orange and purple arrows are gRPC topic publish and delivery, with accepted messages stored in `broker-db`. Gray dashed arrows are gRPC Discovery calls: registration, topic subscriptions, lease renewal, status and load probes, and Broker-hop failure reports. Live chat uses a WebSocket through the DMs proxy and bypasses the gateway and the Broker. Prometheus finds replicas through Discovery, and Grafana shows metrics and Loki logs on `localhost` only.

<img src="docs/architecture.png" alt="Architecture diagram: client, API Gateway, Message Broker with broker-db, Service Discovery, DMs proxy, the Java and Python services with their databases, and Prometheus, Grafana, and Loki monitoring" width="1080"/>

[Architecture](docs/architecture.md) explains ownership and technology choices. The [demonstration guide](docs/demonstration.md) shows how to start, scale, and observe the stack. [Game flows](docs/flows.md) describe a shift. [Integration principles](docs/integration.md) explain mocked and integrated deployments.

## Gateway

The selected gateway is shared Go infrastructure, separate from the eight domain services. All client-to-service REST traffic uses its public listener. The gateway validates client identity, applies the public policy, signs the receiver assertion, bounds task duration and concurrency, and sends each request to the Message Broker with its target service. Its control listener on `:8083` serves only `/healthz`. Status and log export use its gRPC `ControlService` on `:50051`. Domain services retain business authorization and data ownership.

Realtime negotiation uses REST through the gateway, which returns one configured chat URL, the DMs proxy on port `8009`. The proxy is Caddy. It balances WebSocket upgrades across the `discord-dms` replicas by least connections. The gateway and the Broker do not relay frames. Chat tickets, permissions, Redis delivery, and stored history belong to Discord DMs.

Service-owned storage connections do not pass through the gateway or the Broker.

## Monitoring

Prometheus and Grafana start with the stack and publish only to `127.0.0.1`, on ports `9090` and `3000`. Prometheus scrapes the private `/metrics` port of every replica that Discovery lists, so scaled replicas appear without configuration. Grafana provisions the `Student ID services` and `Student ID broker` dashboards. Promtail and Loki collect the service logs from Docker's log files, with 72 hours of retention, and the `Student ID logs` dashboard shows them next to the metrics. Sign in as `admin` with `GRAFANA_ADMIN_PASSWORD` from `.env`. The [demonstration guide](docs/demonstration.md#monitor-the-stack) shows the dashboards, how to query Prometheus, and how to follow one request ID through the logs, and the [metrics contract](docs/contracts/metrics.md) defines the metrics.

## Message Broker

The Message Broker is shared Go infrastructure in the private `ChillGuysStudio/message-broker-service` repository, with the public image `maxnoragami/message-broker-service`. Compose runs one instance as `message-broker`, with REST for Gateway dispatch on port `8080` and gRPC on port `50051` of the container network, and no host port.

The Broker owns service-to-service dispatch, service-call authorization, replica load balancing, backend breakers, and topic event delivery. A targeted request names its destination service. Gateway sends public requests there over REST with an explicit target. Domain services send every peer call there as a typed gRPC call with the `x-broker-target` metadata key. The Broker authenticates the caller, signs the receiver assertion, selects the ready replica with the lowest load, and writes a `dispatch` log record for each attempt. After a failed attempt, it can reroute an eligible request to another replica within the same budget, as the [load routing contract](docs/contracts/routing.md) defines. It reports breaker trips to Discovery.

Producers publish domain events to the Broker by topic. The Broker stores each event and one delivery per subscribing service in its own PostgreSQL, `broker-db`, and retries each delivery a bounded number of times. A delivery that the subscriber rejects, or that fails every attempt, moves to a dead-letter table that administrators can list. The [queues and topics contract](docs/contracts/queues.md) defines targeted queues and topic delivery, and the [dead-letter contract](docs/contracts/dead-letters.md) defines the retry limit and the dead-letter listing. The [service-to-service gRPC contract](docs/contracts/grpc.md) defines the RPCs, metadata, and status mapping. Client authentication, Discord DMs WebSockets, event schemas, and domain ownership stay unchanged. The [Message Broker dispatch contract](docs/contracts/broker.md) defines the credentials, assertions, attribution, and logging.

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

A stopped replica deregisters itself before it exits. Discord DMs scales the same way, for example with `--scale discord-dms=3`. Clients open chat on the `dms-proxy` port `8009`, which balances the replicas, so no replica has a host port. The [demonstration guide](docs/demonstration.md) explains each command.

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
- [Durable delivery and dead letters](docs/contracts/dead-letters.md)
- [Service-to-service gRPC](docs/contracts/grpc.md)
- [Load routing and rerouting](docs/contracts/routing.md)
- [Service metrics and monitoring](docs/contracts/metrics.md)
- [Release procedure](docs/releases.md)
- [GitHub checks and permissions](docs/github.md)

The [project board](https://github.com/orgs/ChillGuysStudio/projects/2) tracks team tasks.
