# Logging contract

Every process writes the same structured records, retains a bounded copy, and exports it to an authorized caller. An administrator downloads a bounded archive through the gateway. This contract covers Gateway, Discovery, the Message Broker, the eight domain services, and the Moderation publisher.

## Records

Each record is one JSON object on one line, encoded as UTF-8. A process writes every record to stdout and to its rotating file. `docker compose logs` and the download archive therefore show the same records.

| Field | Type | Meaning |
| --- | --- | --- |
| `ts` | Time | UTC time the record was written, with millisecond precision and a `Z` suffix, for example `2026-11-12T18:04:05.123Z` |
| `level` | String | `DEBUG`, `INFO`, `WARN`, or `ERROR` |
| `service` | String | Registered service name, for example `applicant` or `moderation-publisher` |
| `instance_id` | Id | The process instance that wrote the record |
| `event` | String | Stable `snake_case` name, for example `http_request` |
| `request_id` | Id? | The `X-Request-ID` value of the request being handled |
| `outcome` | String? | Result of the operation, for example `ok`, `rejected`, `timeout`, or `unavailable` |
| `duration_ms` | Int? | Elapsed milliseconds of the operation |
| `message` | String? | Short human-readable text without payload data |

Records add fields for their kind:

- **HTTP request:** `event` is `http_request`. The record adds `method`, `route`, and `status`. `route` is the matched route template, such as `/api/v1/sessions/{session_id}`, or `unmatched`. It never contains a raw path value or a query string.
- **Outbound call:** `event` is `dependency_call`. The record adds `target_service`, plus `target_instance_id`, `attempt_id`, and `status` when they are known.
- **Broker dispatch:** `event` is `dispatch`. The Broker writes it for each backend attempt. The record adds `caller`, `target_service`, `target_instance_id`, `registration_id`, `attempt_id`, `route`, and `status`, so that replica selection is visible. The [Message Broker contract](broker.md#logging) defines its route values.
- **Domain event:** `event` is `event_published` or `event_consumed`. The record adds `event_type` and `event_id`. `outcome` is `published`, `processed`, `duplicate`, `retry`, or `rejected`. The Broker writes `event_published` for each publish request and a `delivery` record for each push attempt, with outcome `delivered`, `retry`, or `rejected`. The [queues and topics contract](queues.md#logging) defines their fields.
- **RPC:** `event` is `rpc_request` for an RPC the process serves. The [gRPC contract](grpc.md#logging) defines its fields and the RPC fields of `dependency_call` and `dispatch`.
- **Error:** the record adds `error_kind`, a short stable code. It never includes a stack trace at `INFO`.

One user action keeps one `request_id` across every hop. A service sends its current `request_id` as `X-Request-ID` on each outbound call it makes while handling a request. The receiver, including the Message Broker, keeps a valid UUID it receives instead of generating a new one. Work that no request triggered, such as an outbox relay or an event consumer, uses `event_id` for correlation.

A request that fails with an unexpected exception produces one `ERROR` record with `event` `unhandled_exception`, the `request_id`, the route template, and `error_kind`, in addition to its `http_request` record.

Field names never change meaning between services. A process can add other `snake_case` fields when they hold no sensitive data.

## Levels

- `INFO` records completed requests, dispatches, event outcomes, startup and shutdown, registration state changes, and breaker trips.
- `WARN` records failed dependency calls, rejected or retried events, task-limit and timeout rejections, and responses with status 500 or higher.
- `ERROR` records failures the process cannot handle, such as an unexpected exception or a failed startup.
- `DEBUG` records successful health probes, status probes, lease renewals, and successful outbound calls that do not change state. Requests to `/healthz`, `/health`, `/ready`, and `/internal/v1/status` log at `DEBUG` when they succeed.

`LOG_LEVEL` selects the minimum level. The default is `INFO`.

## Forbidden content

Records never contain bearer tokens, refresh tokens, passwords, gateway assertions, control tokens, chat tickets, query strings, request or response bodies, hidden case evidence, or webhook URLs. A route template replaces the raw path. When a value is needed for correlation, the record uses an ID that is already safe to share, such as `request_id`, `event_id`, or `case_id`.

## Retention

Each process appends its records to `$LOG_DIR/<service>.jsonl`. `LOG_DIR` defaults to `/var/log/student-id`, and the image creates that directory for its runtime user. When the file exceeds `LOG_FILE_MAX_BYTES` (default 5 MiB), the process renames it to `<service>.jsonl.1`, shifts older files up, and keeps at most `LOG_FILE_BACKUPS` files (default 3). Retention is therefore at most 20 MiB per process. A process never reads or writes log files outside `LOG_DIR`.

The Moderation publisher has no HTTP listener. It writes its file to a volume that Moderation mounts read-only, and Moderation exports it as described below.

## Instance export

Every process with an HTTP listener serves its own records on its private listener. The [gRPC contract](grpc.md#log-export) replaces this endpoint with `ControlService.ExportLogs`, with the same limits:

```text
GET /internal/v1/logs?since=Time&until=Time&max_bytes=Int
X-Control-Name: gateway
X-Control-Token: <token>
```

- The existing control-plane credentials authenticate the caller. Only the `gateway` and `operator` principals may read logs. The `discovery` principal may not. Compose adds the `gateway` entry to `CONTROL_PLANE_TOKENS` using the gateway's control token.
- `until` defaults to now. `since` defaults to 15 minutes before `until`. The range must not exceed 24 hours, and `since` must be earlier than `until`.
- `max_bytes` defaults to 1 MiB and must be between 1 and 4 MiB.
- Moderation also accepts `process=publisher`, which returns the publisher's records from the shared volume instead of its own. No other `process` value is accepted.

The response is `200` with `Content-Type: application/x-ndjson`. The body contains the raw records whose `ts` falls in `[since, until)`, oldest first, read from the rotated files and the current file. The process stops at `max_bytes` without splitting a record, or after 2 seconds, and sets `X-Log-Truncated: true`. Otherwise the header is `false`. `X-Log-Records` gives the number of returned records. Lines that are not valid records are skipped and counted in `X-Log-Skipped`.

Errors use the existing error body. A missing or wrong credential returns `401 INVALID_AUTH`. An authenticated principal without log access returns `403 FORBIDDEN`. An invalid range, size, or `process` value returns `400 INVALID_LOG_QUERY`.

## Administrator download

The gateway serves the only public log route:

```text
GET /api/v1/admin/logs?service=String&since=Time&until=Time&max_bytes=Int
Authorization: Bearer <administrator access token>
```

- Only an access token whose `is_admin` claim is true may download logs. A missing or invalid token returns `401 UNAUTHORIZED`. A non-administrator receives `403 FORBIDDEN`.
- `service` is optional and repeatable. Allowed values are `gateway`, `message-broker`, `discovery`, `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation`, `moderation-publisher`, and `discord-dms`. Omitting it selects all of them. Any other value returns `400 INVALID_LOG_QUERY`.
- `since`, `until`, and `max_bytes` follow the instance rules. `max_bytes` applies to each instance.

The gateway takes its targets from trusted sources only: its own file, Discovery's own export, the instances that the Discovery registry lists (ready and unavailable, but not removed), and the publisher through one ready Moderation instance. It never takes a host, URL, or path from the request. It calls at most 4 targets at once, gives each target 3 seconds, stops collecting after 15 seconds, and stops adding records once the archive holds 16 MiB of uncompressed data.

The response is `200` with `Content-Type: application/gzip` and `Content-Disposition: attachment; filename="student-id-logs-<YYYYMMDDTHHMMSSZ>.tar.gz"`. The archive contains:

- `<service>/<instance_id>.jsonl`: the raw records returned by each target, unchanged.
- `manifest.json`: `generated_at`, `since`, `until`, `max_bytes`, and one entry per target with `service`, `instance_id`, `status` (`ok`, `truncated`, `unavailable`, or `error`), `records`, `bytes`, and `error_kind` when the target failed.

Archive paths contain only an allowed service name and a canonical lowercase UUID, so a target cannot choose a path. An unavailable or slow target appears in the manifest with its status and does not fail the download. The route proxies only log exports and never forwards other private paths.

## Verification

Each repository tests its formatter, levels, redaction, rotation, export authorization, range and size limits, and path safety. The released stack is checked with `curl` for an administrator download, refusals for anonymous and ordinary players, a stopped replica reported as `unavailable`, and an archive without the forbidden content.
