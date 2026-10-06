# Game flows

These sequences explain the shared architecture. [Integration principles](integration.md) describe how mocks and real peers exercise the same flows.

## Start a shift

A player creates a lobby for a team. The lobby starts with one Moderator. Other team members join as Junior Moderators.

Before start, Session verifies team membership, exactly one Moderator, and at least two Junior Moderators. University Record permissions must cover every record kind. No single Junior Moderator may receive every kind.

Session pins the published rule version and an immutable university snapshot. It reserves the start time and request key once so retries use the same reference time. If a dependency fails, the shift stays in the lobby. Starting freezes the roster, roles, and record permissions.

## Initialize a case

The Moderator asks Session to start a case through Applicant, Credential, or University Record. Session reserves the current-case slot and one initializer request key before the call.

The selected initializer creates the `case_id`. It stores its own evidence and publishes one `CaseInitialized` event. That event contains the initializer's domain section, not a complete prebuilt case for every service.

The other owners derive their records from the received fields and pinned snapshot. They reuse the case ID. They do not republish the initialization event or write another service's storage.

Session marks the case ready only when all three owners report readiness. A completed empty outsider bundle is valid evidence. A missing delivery is not. Duplicate matching events are no-ops, while conflicting events go to quarantine.

The [case contract](contracts/cases.md) specifies deterministic generation, scenario differences, retries, and readiness.

## Inspect evidence and decide

The Moderator reads applicant claims and credentials. Junior Moderators read only their assigned university record kinds. Discord DMs checks shift roles and record permissions before granting channel access.

Moderation accepts a decision only from the assigned Moderator for the current case in an active shift. It reads complete evidence from its owners and asks Server Rules to evaluate it against the pinned policy.

Server Rules uses university facts, credential validations, and existing subject bans. It does not receive a generator seed or scenario. The expected action stays hidden until the player commits a decision.

Moderation stores the decision, policy snapshot, optional subject ban, and `DecisionScored` outbox entry in one transaction. One final decision is allowed for each case in a shift.

A correct action adds 10 points. An incorrect action adds -5 points and records 5 penalty points. A `flag` ends the case. A `ban` needs a known subject. The ban created by this decision does not change the evidence used to score that decision.

## End a shift and award progression

Session applies `DecisionScored` once, updates the aggregate score, and releases the current-case slot. A new case cannot start before that result arrives.

Ending a shift returns `409` while a case or scoring event remains unfinished. Once the shift is complete, Session commits its final state and a `ShiftEnded` outbox entry, then returns `200`. The synchronous end operation does not use `ending`.

Player applies `max(0, score)` XP to each participant once per shift. Administrator disciplinary deductions are separate events. A progression ledger makes event order irrelevant and prevents decision penalties from being deducted twice.

## Recover chat

Discord DMs issues a single-use chat ticket with a 30-second lifetime. It stores each message before acknowledgement and broadcast. A retry with the same author and client message ID returns the original acknowledgement.

Redis Pub/Sub delivers committed messages to connected replicas. It does not replay missed messages. After reconnecting with a new ticket, the client reads REST history and deduplicates by message ID.

[Verification cases](verification.md) list the expected results for failures, retries, and concurrency.
