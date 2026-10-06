# Verification cases

These cases describe expected behavior from the shared contracts. Mock tests exercise individual boundaries. Integrated tests verify the same results against real service images.

| Case | Expected result |
| --- | --- |
| Each of three initializers and four scenarios | The two subscribers derive their own records with one shared case ID. Hidden generation data stays internal. |
| Duplicate initialization or scoring | No duplicate records, processed count, XP, or penalty. A conflicting payload goes to quarantine. |
| Delayed case consumer | The case stays pending. Moderation cannot score incomplete evidence. |
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

The [Postman collections](../postman/) provide service request fixtures. Player and Session also have runners under `tools/`. WebSocket checks need a client that supports WebSocket frames.
