# Verification cases

These cases cover service behavior with mocks or real images. CPR workflow checks test repository tools, not these cases.

| Case | Expected result |
| --- | --- |
| Each of three initializers and four scenarios | The two subscribers derive their own records with one shared case ID. Hidden generation data stays internal. |
| Duplicate initialization or scoring | No duplicate records, processed count, XP, or penalty. A conflicting payload goes to quarantine. |
| Delayed case consumer | Session treats a missing owner projection as pending. Moderation receives `409 CASE_NOT_READY` with `Retry-After: 1` and saves no decision. |
| Decision without frontend status polling | Moderation's aggregate Session check records readiness before evaluation and scoring delivery. |
| Internal call with service credentials but no verified initiating player | Player-action endpoints deny the request. A supplied `X-Player-Id` does not grant access. |
| Admin grant, revoke, or client-supplied privilege | Newly issued tokens reflect server-controlled authority. Registration and profile updates cannot grant admin access. |
| Expected answer before and after commitment | No preview reveals the expected action. Authorized committed-decision reads include the saved result. |
| Wrong player, shift, role, or record permission | The service denies the request without exposing restricted evidence. |
| Policy publication during a shift | The shift keeps its pinned version. A later shift can use the new version. |
| Reference or template edit during generation | Existing snapshot and selected template values remain stable. Future work can use the edit. |
| Concurrent final decisions | One decision commits. Other keys receive a conflict. A retry with the winning key returns the original result. |
| Shift end before scoring delivery | The end request returns `409`. A retry ends the shift after Session applies the result. |
| Replayed shift or discipline event | Player updates the progression ledger once, regardless of delivery order. |
| Empty outsider evidence | Completed empty documents and records can become ready. Missing delivery cannot. |
| Staff, alumni, or inactive enrollment | Null fields, courses, and group membership follow the person-field rules. A genuine document alone does not grant access. |
| Forged, expired, incomplete, or inconsistent document | Validation reports all applicable independent flags and issue codes. |
| Returning banned subject | The subject ban overrides later case IDs and policy examples. |
| Lost chat acknowledgement or reconnect | The retry does not create another message. REST history recovers missed delivery. |
| Multiple Discord DMs replicas | Each replica receives Pub/Sub notifications. Clients deduplicate by message ID. |
| Ended shift history | DMs verifies the retained roster and permissions, allows authorized history reads, and denies live chat. |
| Failed permission or periodic lifecycle check | No restricted message is saved or delivered. Invalid frames cannot postpone lifecycle and token-expiry checks. |
| Documentation-only service main update or late publishing rerun | Each new HEAD publishes an attributable public image. An older run does not replace a newer main image at `latest`. |

The [Postman collections](../postman/) provide service request fixtures. Player and Session also have runners under `tools/`. WebSocket checks need a client that supports WebSocket frames.
