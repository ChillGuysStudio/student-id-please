# HTTP contract

These conventions apply to service calls in mocked and integrated deployments. [Integration principles](../integration.md) describe identity, compatibility, and dependency checks.

## Paths and data types

Public gateway paths start with `/api/v1`. Internal paths start with `/internal/v1`, and the public gateway listener does not expose them. In the Lab 2 target, all client-to-service REST uses the public gateway listener and all service-to-service REST uses the internal gateway listener. Each endpoint belongs to the service named in its section.

Realtime negotiation uses gateway REST. The returned direct Discord DMs URL carries the WebSocket upgrade and frames, even though its path starts with `/api/v1`. See the [target interaction map and delivery status](../architecture.md).

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

The authentication details below describe the direct-mode baseline. The Lab 2 target verifies client identity at the gateway and removes raw downstream `Authorization`. Tirppy and the caller and receiver owners are coordinating the exact assertion and delegation contract. The [gateway foundation approval](../architecture.md#gateway-delivery-status) does not establish receiver compatibility with that target.

Clients authenticate with `Authorization: Bearer <access_token>`. The Player Service issues tokens. Each service verifies the token signature, issuer, audience, and expiry. Access tokens expire after 15 minutes. Refresh tokens expire after 7 days. The Player Service stores refresh-token hashes, rotates refresh tokens after use, and revokes the refresh session on logout.

Player access tokens carry a boolean `is_admin` derived from server-controlled account authority. Only a verified claim equal to `true` grants global admin access. Registration and profile updates cannot assign that authority. The Server Moderation Session Service assigns shift roles from its stored roster, not client role claims.

Internal HTTP calls use `X-Service-Name` and `X-Service-Token`. Each receiver checks the named caller against its `SERVICE_TOKENS` map and the endpoint's allowed callers. Caller names are `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation`, and `dms`.

A service credential alone does not authorize a player action. Calls representing a player action also forward the initiating player's `Authorization: Bearer` access token. Receivers verify it and obtain participation, shift role, and lifecycle from Session. Session's context query `player_id` must match the verified subject. `X-Player-Id` alone is not identity proof. Service-only readiness polls and authenticated event delivery do not substitute for player authorization.

Player-facing responses never contain hidden generation data or another player's restricted records. Expected actions, correctness, and per-decision score deltas are visible only in authorized committed-decision responses. No endpoint previews a case's expected action before the player's decision commits. Events authenticate the producer as a service.

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
| `503` | Unavailable dependency |

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
