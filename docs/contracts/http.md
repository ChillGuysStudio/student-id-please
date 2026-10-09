# HTTP contract

These conventions apply to service calls in mocked and integrated deployments. [Integration principles](../integration.md) describe identity, compatibility, and dependency checks.

## Paths and data types

Public gateway paths start with `/api/v1`. Internal paths start with `/internal/v1`, and the public gateway listener does not expose them. In the Lab 2 target, all client-to-service REST uses the public gateway listener and all service-to-service REST uses the internal gateway listener. Each endpoint belongs to the service named in its section.

Realtime negotiation uses public gateway REST and returns a direct Discord DMs WebSocket URL. The upgrade and frames bypass the gateway, even though the path starts with `/api/v1`. Database connections also bypass the gateway. See the [request paths and interaction map](../architecture.md).

Requests and non-empty responses use `application/json`. Field names use `snake_case`. Services serialize UUIDs in canonical lowercase hyphenated form before comparison or deterministic generation.

| Notation | Meaning |
| --- | --- |
| `Id` | UUID string |
| `Time` | RFC 3339 UTC timestamp string |
| `Int` | Signed 32-bit integer |
| `Bool` | Boolean |
| `T[]` | Array of `T` |
| `T?` | Optional field |

`T | null` means that the field is required but can contain `null`. All other fields are required. Scores can be negative. Counts cannot be negative. The objects below use type notation, not JSON syntax.

## Authentication and authorization

### Lab 2 gateway mode

Clients send `Authorization: Bearer <access_token>` only to the public gateway. Player issues the tokens. The gateway validates the signature, issuer, audience, and expiry. No original `Authorization` reaches downstream services.

Every service REST call uses the private internal gateway, including calls to a peer's `/api/v1` endpoints. Services authenticate to that listener with `X-Service-Name` and `X-Service-Token`. Player actions also need verified actor authority, not a forwarded Player bearer. The existing [gateway identity module](https://github.com/ChillGuysStudio/gateway-service/blob/dev/docs/contracts/gateway-identity.md) defines request assertions, delegation, and chat capabilities. Its contract is not evidence of an assembled runtime.

Current Moderation and Discord DMs source supports `AUTH_MODE=gateway`. Receivers authenticate the gateway hop, verify `X-Gateway-Assertion`, and reject original `Authorization`. Moderation uses `X-Gateway-Delegation` for peer work. Discord DMs uses `X-Gateway-Chat-Capability` for recurring chat permission reads. Their outgoing adapters send service credentials and the grant, not the Player bearer. See the [Moderation adapter](https://github.com/andyp1xe1/pad-moderation-service/blob/dev/docs/gateway-auth.md) and [Discord DMs adapter](https://github.com/andyp1xe1/pad-discord-dms-service/blob/dev/docs/gateway-auth.md). CPR's older service pointers and current Compose settings do not establish this integration.

Receivers retain business authorization. Session owns participation, shift roles, and lifecycle. Its context query `player_id` must match the verified subject. A service credential or unsigned `X-Player-Id` does not prove player permission. Service-only readiness polls and authenticated event delivery do not substitute for player authorization.

Player access tokens carry a boolean `is_admin` derived from server-controlled account authority. Only a verified claim equal to `true` grants global admin access. Registration and profile updates cannot assign that authority. Session assigns shift roles from its stored roster, not client role claims.

Player-facing responses never contain hidden generation data or another player's restricted records. Expected actions, correctness, and per-decision score deltas are visible only in authorized committed-decision responses. No endpoint previews a case's expected action before the player's decision commits. Events authenticate the producer as a service.

### Legacy direct mode

Standalone direct mode is Lab 1 compatibility, not the Lab 2 integrated rule. In that mode, services verify Player bearer tokens themselves. Player access tokens expire after 15 minutes. Refresh tokens expire after 7 days. Player stores refresh-token hashes, rotates refresh tokens after use, and revokes the refresh session on logout.

Legacy internal calls use `X-Service-Name` and `X-Service-Token`. Receivers check `SERVICE_TOKENS` and endpoint caller allowlists. The legacy names are `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation`, and `dms`. Legacy player-action calls also forward the initiating bearer for receiver verification. This forwarding is not allowed in gateway mode. The current Discord DMs gateway adapter uses `discord-dms`, not legacy `dms`. Caller names must match the selected adapter and configured allowlists.

## Idempotency

Every REST request that changes data includes `Idempotency-Key: <UUID>`. When the same caller retries with the same key, endpoint, and body, the service returns the original status and body. Reusing the key with a different body returns `409`.

Services retain keys and results for the lifetime of the related case or shift. Authentication and administrative reference-data CRUD retain them for 24 hours. This period includes a delete result after resource removal, and clients must retry within it. Published-version commands retain results with the version. A replay still requires valid authorization. To retry a case-start request, the client uses the same entry service and key. The service rejects a retry sent to another entry service.

## Pagination

Collection endpoints accept optional `limit: Int` and `cursor: string` query parameters. The default limit is 50, and the valid range is 1 through 100. `Page<T> = {items: T[], next_cursor: string | null}`. A cursor is opaque and applies only to its caller and resource. Results sort by creation time and then by ID. An empty collection returns `200` with `items: []`.

## Errors and retries

Common error shape: `Error = {code: string, message: string, request_id: Id, details: {field: string, reason: string}[]}`. Do not include hidden facts, secrets, or stack traces.

| Status | Meaning |
| --- | --- |
| `400` | Malformed request |
| `401` | Invalid auth |
| `403` | Insufficient permission |
| `404` | Absent resource |
| `409` | State/key conflict |
| `422` | Invalid field values |
| `429` | Rate limit |
| `503` | Unavailable dependency or `TASK_LIMIT_EXCEEDED` |
| `504` | `TASK_TIMEOUT` |

The Lab 2 target requires finite task deadlines and concurrent task limits on every service and the gateway. Capacity exhaustion returns `503 TASK_LIMIT_EXCEEDED`. An HTTP task deadline returns `504 TASK_TIMEOUT`. Current Moderation and Discord DMs implementations use the shared error shape and `Retry-After: 1` for both errors. A timeout does not prove rollback. Retry a write with its original idempotency key to recover a committed result.

An existing case that is not ready returns `409 CASE_NOT_READY` with `Retry-After: 1`. It does not return an empty result that a caller could treat as an absence of facts. A rate-limit response also includes `Retry-After` in seconds. The endpoint tables list success responses. These common errors apply to every relevant endpoint.

Internal reads time out after 2 seconds. A caller can retry a safe read or a command that carries the original idempotency key. It retries at most twice with backoff. When a dependency fails, the caller returns `503` instead of inventing facts or a decision result. Services use the same pagination, timeout, and size limits.

Example error response:

```json
{
  "code": "CASE_NOT_READY",
  "message": "Case records are still being initialized.",
  "request_id": "9d1ea947-4194-4897-a8db-71698f62fd2a",
  "details": []
}
```
