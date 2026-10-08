# Architecture

The game separates player progression, shift coordination, evidence, admission policy, and chat. Each service owns its storage. Other services use its APIs or events instead of reading its database.

The [architecture diagram](architecture.jpg) shows the Lab 2 target connections, not a verified deployment. Its [editable source](architecture.drawio) retains the embedded Mermaid definition and the drawio layout. [Rendering instructions](architecture-rendering.md) reproduce the JPEG without the team's shared browser. [Game flows](flows.md) describe the request and event sequences. [Integration principles](integration.md) explain how mocks and real peers use these contracts.

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

The gateway is shared Go infrastructure, not a ninth domain service. In the Lab 2 target, its public listener routes client REST requests and realtime negotiation. Its internal listener routes service-to-service REST calls and is not publicly exposed. Services retain business authorization after the gateway verifies identity. Internal endpoints are not public routes.

REST negotiation returns a direct Discord DMs WebSocket URL. The client sends the upgrade and subsequent chat frames directly to Discord DMs. The gateway does not relay frames or hold the live data connection. Discord DMs owns ticket consumption, permission checks, message persistence, and live delivery.

## Gateway delivery status

[Foundation PR #2](https://github.com/ChillGuysStudio/gateway-service/pull/2) at `9d298ab9c161bb039196317466ed362e2817aafb` has MaxNoragami's formal approval and is squash-merged to gateway `dev` at `03c4dcf99b1b619f96ee52aaa6a43650cfb856c3`. It adds public and internal listeners, process health, JSON errors, request IDs, HTTP transport limits, graceful shutdown, and a static non-root container. Unknown application routes fail closed. Process health does not prove peer readiness.

The target topology still depends on separately owned work:

- Tirppy owns [identity and delegation](https://github.com/ChillGuysStudio/student-id-please/issues/88), with caller and receiver owners agreeing the exact contract before migration.
- mcittkmims is the proposed owner of the separate [routing module](https://github.com/ChillGuysStudio/student-id-please/issues/75). Owner acknowledgement is still pending.
- MaxNoragami owns [application task limits and native image publication](https://github.com/ChillGuysStudio/student-id-please/issues/87).
- andyp1xe1 owns the foundation and Discord DMs integration for [realtime negotiation](https://github.com/ChillGuysStudio/student-id-please/issues/78).

The foundation approval does not verify these integrations, a published gateway image, or a running full stack. The current [Compose configuration](../compose.yaml) still exposes localhost service APIs without gateway wiring. Existing service authentication contracts describe the direct-mode baseline. The Lab 2 target validates client tokens at the gateway and removes raw downstream `Authorization`; the exact assertion and delegation schema remains under owner coordination.

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
| Session                               | Player                                   | Check players and team membership                                                  |
| Session                               | Server Rules, University Record          | Pin policy, validate permission distribution, and create a reference snapshot      |
| Session                               | Applicant, Credential, University Record | Select one initializer and poll all three owners for readiness                     |
| Moderation                            | Session                                  | Check the active shift, assigned Moderator, current case, aggregate readiness, and pinned configuration |
| Moderation                            | Applicant, Credential, University Record | Read complete case evidence                                                        |
| Moderation                            | Server Rules                             | Evaluate evidence, existing subject bans, and prior history                        |
| Moderation                            | Player                                   | Check a disciplinary action's target                                               |
| Evidence services, Rules, Discord DMs | Session                                  | Check participation, roles, and lifecycle                                          |
| Discord DMs                           | University Record                        | Check record-derived channel access                                                |
| Applicant, Credential                 | University Record                        | Read a snapshot and reserve or read an identity                                    |
| One case initializer                  | Other case owners                        | Derive owned records from `CaseInitialized`                                        |
| Moderation                            | Session                                  | Apply `DecisionScored` once                                                        |
| Session                               | Player                                   | Apply `ShiftEnded` once                                                            |
| Moderation                            | Player                                   | Apply `DisciplinaryActionApplied` once                                             |

[HTTP conventions](contracts/http.md), [service APIs](contracts/api.md), and [RabbitMQ events](contracts/events.md) define the request and payload details.

This map describes the Lab 2 target. Every service-to-service REST row uses the internal gateway while retaining the named logical caller and receiver. The diagram's purple service REST edges use that same convention. RabbitMQ events and direct WebSocket frames do not pass through the gateway. These paths remain unverified as a complete deployment.

## Data and consistency

A `player_id` identifies a player account. A `subject_id` identifies a simulated person. A `case_id` identifies one application. Bans use `subject_id`, so returning under another case does not remove a ban.

Each service is the sole writer of its data. An event consumer's local copy does not become a new source of truth. Callers recheck authorization-sensitive data with its owner.

A producer commits a domain change and its outbox record in one local transaction. It retains the record until RabbitMQ confirms publication. A consumer commits its domain update and deduplication record before acknowledging delivery. Business-ID constraints also prevent duplicate cases, decisions, or progression awards.

The design does not use distributed transactions or claim exactly-once delivery. A partly initialized case stays pending. Missing evidence or an unavailable dependency never becomes a negative admission decision.

Reusable reference data and presets can change through administrative CRUD. Shift snapshots, case evidence, and published policy versions remain immutable. Edits affect future shifts or cases, not evidence already used for scoring.

## Technology choices

Player, Session, Moderation, and Discord DMs use Python and FastAPI. Their work is mostly HTTP, storage, or live delivery. Blocking clients must not run on the WebSocket event loop.

Applicant, Credential, Server Rules, and University Record use Java and Spring Boot. Typed models and validation fit their evidence and policy operations. Maintaining two stacks adds tooling, but the coursework requires two languages.

The shared gateway uses Go for HTTP listeners, request routing, identity verification, and task admission. It owns no domain database.

PostgreSQL fits relational state and transaction constraints. MongoDB fits the varied evidence and reference record types. Both stores still enforce the shared contract.

REST provides an immediate response to reads and commands. RabbitMQ carries results that consumers can process later and retry. Discord DMs uses WebSockets for live messages, then REST history to recover missed delivery. Redis Pub/Sub does not retain messages.
