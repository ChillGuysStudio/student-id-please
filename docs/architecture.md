# Architecture

The game separates player progression, shift coordination, evidence, admission policy, and chat. Each service owns its storage. Other services use its APIs or events instead of reading its database.

The [architecture diagram](architecture.png) and its [editable source](architecture.drawio) show the services, request paths, storage, and planned event connections. [Game flows](flows.md) describe the request and event sequences. [Integration principles](integration.md) explain how mocks and real peers use these contracts.

## Request paths

The client sends REST to the API gateway, and the gateway routes each request to one service. Ticket negotiation uses the same REST path. The client then opens a direct WebSocket to the Discord DMs service for live chat. The gateway does not relay chat frames.

All service-to-service REST passes through the gateway. Blue bidirectional arrows represent HTTP requests and responses between the gateway and each service. Route labels identify the resources and inter-service calls on those paths. The purple bidirectional arrow connects the client directly to Discord DMs for WebSocket chat. Dashed storage links connect each service to its own databases. Grey RabbitMQ links represent planned event delivery.

## Service ownership

| Service           | Owns                                                                                                      | Does not own                                                           |
| ----------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Player            | Accounts, authentication, profiles, friendships, teams, XP, and levels                                    | Shift roles, applicants, admission decisions, or shift scores          |
| Session           | Shift lifecycle, roster, roles, pinned configuration, current case, processed count, score, and penalties | Player identity, evidence, policy definitions, or individual decisions |
| Applicant         | Presented claims, profile presets, and its case initialization metadata                                   | Credentials, university truth, or admission policy                     |
| Credential        | Document templates, presented documents, and validation results                                           | Applicant claims, university truth, or access policy                   |
| Server Rules      | Draft and published rulesets, policy evaluation                                                           | Evidence, stored bans, player actions, or scoring                      |
| University Record | Reference facts, identity reservations, shift snapshots, case records, and record permissions             | Claims, document authenticity, or admission decisions                  |
| Moderation        | Final decisions, policy snapshots, subject bans, decision scores, and administrator disciplinary actions  | Source evidence, rule definitions, aggregate shift scores, or XP       |
| Discord DMs       | Channels, membership, messages, chat tickets, and live delivery                                           | Accounts, shift roles, record permissions, or the truth of a message   |

The gateway is shared Go infrastructure and owns no domain data. Its public listener routes all client-to-service REST, including realtime negotiation. Its internal listener routes all service-to-service REST and is not publicly exposed. Services retain business authorization after the gateway verifies identity. Internal endpoints are not public routes.

REST negotiation returns a direct Discord DMs WebSocket URL. The client sends the upgrade and subsequent chat frames directly to Discord DMs. The gateway does not relay frames or hold the live data connection. Discord DMs owns ticket consumption, permission checks, message persistence, and live delivery.

## Gateway authorization

The gateway validates client bearer tokens and removes the original `Authorization` header before forwarding a request. A receiving service uses verified identity to check access to its own resources. Player owns accounts and token issuance; the gateway verifies those tokens at the request boundary.

Internal requests authenticate the calling service and retain the initiating player's identity when the operation requires it. Services check participation, roles, and resource permissions. Gateway routing does not grant access to another player's records or administrator operations.

## Storage

| Service           | Durable storage                                                       | Redis use                               |
| ----------------- | --------------------------------------------------------------------- | --------------------------------------- |
| Player            | PostgreSQL                                                            | None                                    |
| Session           | PostgreSQL for state, locks, history, and event records               | Cached live views                       |
| Applicant         | MongoDB for presets and case claims                                   | None                                    |
| Credential        | MongoDB for templates, documents, and validations                     | None                                    |
| Server Rules      | PostgreSQL for drafts and immutable published versions                | None                                    |
| University Record | MongoDB for reference data, reservations, snapshots, and case records | None                                    |
| Moderation        | PostgreSQL for decisions, bans, discipline, and outbox rows           | None                                    |
| Discord DMs       | PostgreSQL for channels, membership, and history                      | Single-use tickets and Pub/Sub delivery |

A dedicated database belongs to each service. Sharing a database server in the development deployment does not allow services to use each other's collections or tables. Database foreign keys never cross service boundaries.

MongoDB case operations use local transactions and require a replica set. PostgreSQL transactions protect domain changes and event records. Session uses PostgreSQL transaction advisory locks to serialize mutations for one shift. Redis caches rebuildable Session views and is not the source of shift state, scores, locks, or chat history.

## Communication

| Caller or producer                    | Receiver or consumer                     | Purpose                                                                            |
| ------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| Client through public gateway         | Public services                          | Public REST commands and permitted reads, including Player authentication          |
| Client through public gateway         | Discord DMs                              | REST realtime negotiation, chat tickets, channels, and history                     |
| Client directly                       | Discord DMs                              | WebSocket upgrade and live chat frames after negotiation                           |
| Session through internal gateway      | Player                                   | Check players and team membership over REST                                        |
| Session through internal gateway      | Server Rules, University Record          | Pin policy, validate permission distribution, and create a reference snapshot over REST |
| Session through internal gateway      | Applicant, Credential, University Record | Select one initializer and poll all three owners for readiness over REST            |
| Moderation through internal gateway   | Session                                  | Check the active shift, assigned Moderator, current case, aggregate readiness, and pinned configuration over REST |
| Moderation through internal gateway   | Applicant, Credential, University Record | Read complete case evidence over REST                                               |
| Moderation through internal gateway   | Server Rules                             | Evaluate evidence, existing subject bans, and prior history over REST                |
| Moderation through internal gateway   | Player                                   | Check a disciplinary action's target over REST                                      |
| Evidence services, Rules, Discord DMs through internal gateway | Session                  | Check participation, roles, and lifecycle over REST                                  |
| Discord DMs through internal gateway  | University Record                        | Check record-derived channel access over REST                                       |
| Applicant, Credential through internal gateway | University Record                  | Read a snapshot and reserve or read an identity over REST                            |
| One case initializer                  | Other case owners                        | Derive owned records from `CaseInitialized`                                        |
| Moderation                            | Session                                  | Apply `DecisionScored` once                                                        |
| Session                               | Player                                   | Apply `ShiftEnded` once                                                            |
| Moderation                            | Player                                   | Apply `DisciplinaryActionApplied` once                                             |

[HTTP conventions](contracts/http.md), [service APIs](contracts/api.md), and [RabbitMQ events](contracts/events.md) define the request and payload details.

All client-to-service REST uses the public gateway, and all service-to-service REST uses the internal gateway. The final four rows describe planned RabbitMQ event delivery, shown in grey in the diagram. Broker events, service-owned storage connections, and direct WebSocket upgrades and frames do not pass through the gateway.

## Data and consistency

A `player_id` identifies a player account. A `subject_id` identifies a simulated person. A `case_id` identifies one application. Bans use `subject_id`, so returning under another case does not remove a ban.

Each service is the sole writer of its data. An event consumer's local copy does not become a new source of truth. Callers recheck authorization-sensitive data with its owner.

The planned event flow uses an outbox and consumer deduplication. A producer commits a domain change and its outbox record in one local transaction. It retains the record until RabbitMQ confirms publication. A consumer commits its domain update and deduplication record before acknowledging delivery. Business-ID constraints also prevent duplicate cases, decisions, or progression awards.

The design does not use distributed transactions or claim exactly-once delivery. A partly initialized case stays pending. Missing evidence or an unavailable dependency never becomes a negative admission decision.

Reusable reference data and presets can change through administrative CRUD. Shift snapshots, case evidence, and published policy versions remain immutable. Edits affect future shifts or cases, not evidence already used for scoring.

## Technology choices

Player, Session, Moderation, and Discord DMs use Python and FastAPI. Their work is mostly HTTP, storage, or live delivery. Blocking clients must not run on the WebSocket event loop.

Applicant, Credential, Server Rules, and University Record use Java and Spring Boot. Typed models and validation fit their evidence and policy operations.

The shared gateway uses Go for HTTP listeners, request routing, identity verification, and task admission. It owns no domain database.

PostgreSQL fits relational state and transaction constraints. MongoDB fits the varied evidence and reference record types. Both stores still enforce the shared contract.

REST provides an immediate response to reads and commands. RabbitMQ is planned for asynchronous results that consumers can process later and retry. Discord DMs uses WebSockets for live messages, then REST history to recover missed delivery. Redis Pub/Sub does not retain messages.
