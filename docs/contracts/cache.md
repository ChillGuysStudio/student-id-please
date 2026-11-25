# Cache contract

Services cache common reads and authentication data in Redis. The cache is a copy that can disappear at any time. The owner's datastore stays the source of every value, and every service works without the cache.

The cache nodes are separate from the `redis` service, which holds chat tickets and delivery notifications.

## What each service caches

Request counts of a complete regression and gameplay run chose these reads. Session context, record permissions, players, teams, and rule versions were the most frequent business reads.

| Service | Value | Read by | Time to live |
| --- | --- | --- | --- |
| Session | The session record behind the context | `GetSessionContext` | 5 s |
| Session | Session views | `GET /api/v1/sessions/{session_id}` | 30 s |
| Player | Player account, without email and password hash | `GET /api/v1/players/{player_id}`, `GetPlayer`, and the profile part of `GET /api/v1/players/me` | 30 s |
| Player | Team and its members | `GET /api/v1/teams/{team_id}`, `GetTeam` | 30 s |
| Player | A refresh token hash that is used or revoked | `POST /api/v1/auth/refresh` | Until the token expires, at most 7 days |
| University Record | The permission record of a session | `GetRecordPermission`, `GET /api/v1/sessions/{session_id}/record-permissions/me` | 5 s |
| University Record | Reference data of the kinds `program`, `course`, `academic_year`, and `schedule` | `GET /api/v1/admin/university-data/{reference_id}` | 30 s |
| Server Rules | A published rule version | `GET /api/v1/rule-versions/{rule_version}` | 1 h |
| Applicant | A profile preset, and the preset list | `GET /api/v1/admin/applicant-presets` and by identifier | 30 s |
| Credential | A credential template, and the template list | `GET /api/v1/admin/credential-templates` and by identifier | 30 s |
| Moderation | A committed decision, as its participants read it | `GET /api/v1/sessions/{session_id}/decisions/{decision_id}` | 1 h |
| Discord DMs | The channels of a session | `GET /api/v1/sessions/{session_id}/channels` | 30 s |

Values with a time to live of 1 hour never change after they exist. An authorization input has at most 5 seconds.

A refresh token is cached only when the database has refused it, because a used or revoked token never becomes valid again. A cached entry refuses the token with the same result as the database. A missing entry proves nothing, so every accepted refresh uses the database.

## What is never cached

- Access tokens, refresh tokens, chat tickets, password hashes, email addresses, and credentials.
- Case evidence and hidden case data. An expected action and the policy snapshot are cached only as part of a committed decision, which every participant may read. Nothing about a decision is cached before it commits.
- University reference data that belongs to a person or is a source of case evidence.
- The result of an authorization check. The service checks every request, and only reads its input from the cache.
- Draft rule versions, idempotency results, and errors.

Every value is the same for every caller. The service filters a value for the actor after it reads it. A value that depends on the actor is not cached.

## Keys and values

A key is `v1:<service>:<resource>:<id>`, for example `v1:player:account:0e0c…`. The service is the registry name. A value is JSON. A change of its shape changes the version in the key. A value larger than 64 KiB is not cached.

## Reads

1. Read the key. A value that parses is a hit.
2. After a miss, an error, or a value that does not parse, read the datastore.
3. Write the value with `SET key value NX EX ttl`. `NX` keeps a tombstone in place.

## Writes

After the datastore commits, the service writes a tombstone with `SET key "" EX 10`. A read treats an empty value as a miss. A reader that read the old row before the commit cannot put it back, because its `NX` write fails while the tombstone exists. A reader does not store a value whose load took longer than 5 seconds, so a load cannot outlive the tombstone.

If the tombstone cannot be written, readers see the old value until its time to live ends. This is the bound on staleness, so an authorization input has 5 seconds.

A list has a generation, which is a random identifier under its own key. The key of each page contains the generation. A write to a member writes one tombstone on the generation key, which makes every page of the old generation unreachable. A reader gets the generation before it reads the datastore, and caches no page while the tombstone exists.

## Failures

A cache operation has a timeout of 100 milliseconds for connect and for each command. After a failure, the process uses no cache for 1 second, so a lost node does not add its timeout to each request. A tombstone that this skips leaves the old value until its time to live ends. After a commit with an unknown result, the service writes the tombstone. The service then serves from the datastore with the same status and body. The cache never makes a service unready, and its state is not part of readiness.

## Configuration

| Variable | Meaning |
| --- | --- |
| `CACHE_NODES` | Comma-separated `host:port` list. Empty turns the cache off. |
| `CACHE_PASSWORD` | Password of every node |

Each node runs Redis with `maxmemory` 48 MB, `allkeys-lru`, and no persistence. It publishes no host port.

## Metrics

`student_id_cache_requests_total` counts reads with the labels `cache` and `result`. `cache` is the resource, such as `account`. `result` is `hit`, `miss`, `error`, or `off` while the process skips the cache after a failure. No label holds a key or an identifier.

## Verification

- A repeated read is a hit, and its response equals the first one.
- A read directly after a write shows the new value.
- With the cache stopped, every request keeps its status and body, and a service stays ready.
- `redis-cli --scan` shows no key or value with an excluded field.
