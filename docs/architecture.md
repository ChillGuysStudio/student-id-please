# Architecture

The game separates player progression, shift coordination, evidence, admission policy, and chat. Each service owns its storage. Other services use its APIs or events instead of reading its database.

The [architecture diagram](architecture.jpg) shows the main connections. [Game flows](flows.md) describe the request and event sequences. [Integration principles](integration.md) explain how mocks and real peers use these contracts.

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

The gateway routes public REST requests and WebSocket upgrades. It is infrastructure, not a ninth domain service. Services still authorize requests after the gateway checks authentication. Internal endpoints are not public routes.

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

MongoDB case operations use local transactions and require a replica set. PostgreSQL transactions protect domain changes and event records. Redis is not the source of shift scores or chat history.

## Communication

| Caller or producer                    | Receiver or consumer                     | Purpose                                                                            |
| ------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| Client through gateway                | Public services                          | Authenticated commands and permitted reads over REST                               |
| Client through gateway                | Discord DMs                              | WebSocket chat                                                                     |
| Session                               | Player                                   | Check players and team membership                                                  |
| Session                               | Server Rules, University Record          | Pin policy, validate permission distribution, and create a reference snapshot      |
| Session                               | Applicant, Credential, University Record | Select one initializer and poll all three owners for readiness                     |
| Moderation                            | Session                                  | Check the active shift, assigned Moderator, current case, and pinned configuration |
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

## Data and consistency

A `player_id` identifies a player account. A `subject_id` identifies a simulated person. A `case_id` identifies one application. Bans use `subject_id`, so returning under another case does not remove a ban.

Each service is the sole writer of its data. An event consumer's local copy does not become a new source of truth. Callers recheck authorization-sensitive data with its owner.

A producer commits a domain change and its outbox record in one local transaction. It retains the record until RabbitMQ confirms publication. A consumer commits its domain update and deduplication record before acknowledging delivery. Business-ID constraints also prevent duplicate cases, decisions, or progression awards.

The design does not use distributed transactions or claim exactly-once delivery. A partly initialized case stays pending. Missing evidence or an unavailable dependency never becomes a negative admission decision.

Reusable reference data and presets can change through administrative CRUD. Shift snapshots, case evidence, and published policy versions remain immutable. Edits affect future shifts or cases, not evidence already used for scoring.

## Technology choices

Player, Session, Moderation, and Discord DMs use Python and FastAPI. Their work is mostly HTTP, storage, or live delivery. Blocking clients must not run on the WebSocket event loop.

Applicant, Credential, Server Rules, and University Record use Java and Spring Boot. Typed models and validation fit their evidence and policy operations. Maintaining two stacks adds tooling, but the coursework requires two languages.

PostgreSQL fits relational state and transaction constraints. MongoDB fits the varied evidence and reference record types. Both stores still enforce the shared contract.

REST provides an immediate response to reads and commands. RabbitMQ carries results that consumers can process later and retry. Discord DMs uses WebSockets for live messages, then REST history to recover missed delivery. Redis Pub/Sub does not retain messages.

