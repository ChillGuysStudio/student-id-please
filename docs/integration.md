# Integration principles

Services can run against mocks or real peers without changing the shared contracts. Mocks isolate a service for development and tests. Real integration verifies that independently built services agree.

## Use mocks at service boundaries

A mock implements a peer's documented request and response shapes. It uses valid IDs, pinned versions, reference times, and roles. It exercises the real caller or event handler rather than bypassing that code with prebuilt results.

Mock tests cover unavailable dependencies, delayed readiness, duplicate events, conflicting payloads, and denied access. A successful fixture is not evidence that the peer's public image implements the same contract.

Mocks do not decide admission policy inside Session or make missing authorization data grant access. Evidence generators do not infer expected policy outcomes from a scenario name. The service that owns the decision or evaluation still performs that work.

## Connect real services

The Lab 2 target sends every client REST request through the public gateway and every service REST request through the private internal gateway. This includes peer calls to `/api/v1` paths. The gateway validates client `Authorization` and never forwards the original header downstream. Receivers retain business checks against Session roles, participation, lifecycle, and resource permissions. A service credential does not prove the initiating player's permission.

Realtime negotiation uses public gateway REST and returns a direct service WebSocket URL. The upgrade and frames do not pass through the gateway. Ticket requests and history recovery remain public gateway REST. Database connections also bypass the gateway.

An integrated deployment supplies internal gateway route prefixes as peer URLs, service credentials, receiver-hop credentials, verification keys, and broker routing. Every caller and receiver must agree on these settings. Direct-mode bearer forwarding is legacy standalone compatibility, not the integrated rule. See [HTTP authentication and authorization](contracts/http.md#authentication-and-authorization).

Current Moderation and Discord DMs source has gateway receiver and outgoing adapters. Those adapters reject original `Authorization` and preserve domain checks. This source capability does not prove full-stack compatibility. CPR still records older service pointers, and its current Compose configuration has no gateway and uses direct peer URLs. Runtime assembly, compatible configuration, and real-peer verification remain separate work.

Integration checks use the public service images and the same request fixtures used for mock tests. They verify actual responses, gateway routing, rejected direct REST bypasses, persisted records, and delivered events. They also check `503 TASK_LIMIT_EXCEEDED` and `504 TASK_TIMEOUT` at the gateway and each service. A process health check proves only that the process responds.

Switching a mode flag does not establish compatibility. Real peers must agree on authentication headers, token issuer and audience, caller names, payload schemas, ports, and error behavior.

## Check event delivery

An outbox row proves that a service committed a pending event. It does not prove delivery. Integration verifies publisher confirms, durable subscriber queues, inbox completion, and the resulting domain update.

Transient failures retain the original IDs through retries. A replay must not create another case, decision, message, or progression award. Invalid or conflicting events go to a dead-letter queue rather than overwriting stored evidence.

## Preserve configuration and data

A shift pins its rule version, university snapshot, and reference time. Retries use those values instead of live configuration. Published evidence and policy snapshots remain readable after reusable data changes.

Database volumes preserve domain data across container recreation. Player signing keys persist so existing tokens remain verifiable. Discord DMs replicas share the ticket secret. Redis Pub/Sub is ephemeral, so clients recover chat from stored history.

## Evolve contracts

Mocks, callers, consumers, and public images use the same wire definitions. A new required field or a changed event shape is a compatibility change, even when all services are developed by one team.

Before connecting a new major event schema, verify that each producer and consumer supports it. Keep old stored messages on their original schema or migrate them explicitly. A schema version is not a label for an implementation milestone.

## Run images without private source

CPR deployment uses public images. Private repository access is needed only for source work. Each developer can initialize their two owned services and use images or mocks for the rest.

A recorded source SHA identifies a service revision. An image digest identifies the exact runnable artifact. Pin both when a deployment must be repeatable. The `latest` tag is suitable for exploratory development, but it can change without a CPR commit.
