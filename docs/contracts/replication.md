# Database replication contract

Each private service database has three copies and fails over without an operator. This contract covers the PostgreSQL databases of Player, Session, Moderation, Discord DMs, and Server Rules, the MongoDB deployment that Applicant and Credential share, and the MongoDB deployment of University Record.

`broker-db`, `warehouse-db`, and Redis have one copy. If `broker-db` stops, the Broker accepts no topic event until it returns, and its volume keeps the accepted ones. The warehouse can be loaded again from the sources.

## Guarantees

| Event | PostgreSQL | MongoDB |
| --- | --- | --- |
| The primary stops cleanly | Writes resume in about 2 seconds | Driver retries hide the election |
| The primary is killed | Writes resume within 25 seconds | Writes resume within 15 seconds |
| A standby or secondary is lost | No interruption | No interruption |
| etcd is lost | No interruption while every node is up | Not used |
| Every node restarts | Data is kept, and writes resume after one node leads | Data is kept, and writes resume after an election |

An acknowledged write survives the loss of any one node. A client can see a connection error during a failover, and the service reports it as a failed dependency under its existing rules.

## PostgreSQL

[Patroni](https://patroni.readthedocs.io/) runs beside PostgreSQL on each node. The nodes of one database compete for a leader key in etcd. The holder is the primary. When the key expires, the most current synchronous standby takes it and promotes itself. A returning primary rejoins as a standby, and `pg_rewind` removes the changes that it did not replicate.

The image is `ghcr.io/zalando/spilo-17`. It includes Patroni and PostgreSQL 17 for AMD64 and ARM64. The containers run Patroni directly with the repository's configuration and do not start the image's connection pooler, scheduler, or extensions. Server Rules moves from PostgreSQL 18 to 17, so that one image serves every database.

One etcd node holds the leader keys of all five databases, each under its own scope.

| Setting | Value | Reason |
| --- | --- | --- |
| Nodes for each database | 3 | Two copies remain after one node is lost. |
| `synchronous_mode` | `true` | A commit waits for one standby, so a promotion loses no acknowledged write. With no standby left, the primary continues alone. |
| `failsafe_mode` | `true` | Without etcd, the primary continues while it reaches every other member. Without this setting, every database becomes read-only when etcd stops. |
| `ttl`, `loop_wait`, `retry_timeout` | 20, 3, 3 seconds | 20 seconds is the smallest `ttl` that Patroni accepts. It bounds the time to notice a killed primary. |
| Base backup checkpoint | `fast` | A lazy checkpoint delays a new standby by more than a minute. |
| `shared_buffers` | 64 MB | The nodes of all databases share one laptop. |

With `synchronous_mode`, a primary that runs alone has one copy of new writes until a standby returns.

The Patroni REST API changes cluster state, so its write endpoints require a password. Replication and superuser passwords come from `.env`. No node publishes a host port. etcd has no authentication and is reachable only on the container network.

### Nodes and volumes

Nodes are declared services named `<database>-1` to `<database>-3`, with one volume each. They are not scaled with `--scale`, because a node needs its own volume and a stable address. A new named volume belongs to root, so the start script corrects its ownership and drops privileges before it starts Patroni.

### Connections

Clients list every node and ask for the primary. There is no proxy.

| Client | Driver | Connection setting |
| --- | --- | --- |
| Player, Session, Moderation | psycopg through SQLAlchemy | `?host=a,b,c&port=5432,5432,5432&target_session_attrs=read-write&connect_timeout=3` |
| Discord DMs | asyncpg through SQLAlchemy | `?host=a:5432&host=b:5432&host=c:5432&target_session_attrs=read-write` |
| Server Rules | JDBC | `jdbc:postgresql://a:5432,b:5432,c:5432/db?targetServerType=primary&connectTimeout=3` |
| ETL | pgx | `postgres://a:5432,b:5432,c:5432/db?target_session_attrs=prefer-standby` |

These settings need no service code. A pool checks a connection before use and replaces one that points to a former primary, which refuses writes.

A frozen node, such as a paused container, does not close its sockets. A standby is promoted within the same 25 seconds, but a client that already waits on the frozen node waits until its own timeout. asyncpg `command_timeout` and JDBC `socketTimeout` end the wait. libpq has no equivalent, so a psycopg call waits until the node returns. The HTTP task timeout still answers the caller.

## MongoDB

Each deployment is a replica set with three data-bearing members and majority writes. An arbiter in place of the third member is not enough. With one data-bearing member lost, a majority write cannot complete, so a failover would not restore writes.

Members of one set share a keyfile from a generated secret in `.local/stack`. A keyfile generated in each container would differ between members. Each member has its own volume and a 256 MB cache, and the health check rules of [development](../development.md) apply.

| Client | Connection setting |
| --- | --- |
| Applicant, Credential, University Record | `mongodb://a,b,c/db?replicaSet=rs0&w=majority&retryWrites=true` without `directConnection` |
| ETL | The same hosts with `readPreference=secondaryPreferred` |

## Migrations, health, and registration

- Schema migrations use the same connection settings, so they run on the primary. Replicas of one service start together, so a migration holds its existing lock.
- A service with no reachable primary reports unready. Discovery treats it as an unready instance, not as a removal. A failover must not leave an instance durably removed after the database returns, so services answer `STORAGE_UNAVAILABLE`, as [storage outages](resilience.md#storage-outages) defines.
- The health check of a PostgreSQL node passes when the node is a running primary or a streaming standby.
- The role script of the [warehouse contract](warehouse.md) runs against the primary. The roles replicate to the standbys.

## Existing volumes

Single-node volumes are not converted. A stack from an earlier release starts with new volumes. To keep data, dump it from the earlier stack and restore it into the new primary.

## Tools that were not chosen

| Tool | Reason |
| --- | --- |
| Streaming replication with manual promotion | Nothing detects a lost primary or prevents two primaries. |
| `pg_auto_failover` | The published image stops at PostgreSQL 15. |
| Stolon | The published images stop at PostgreSQL 15. |
| repmgr | The maintained public image was withdrawn. The legacy copy has had no update since August 2025. |
| A failover manager of our own | Leader election and fencing are the hard part, and Patroni already solves them. |

## Measurements

Measured on 2026-11-25 on the demonstration laptop, with a client that inserted ten rows each second and recorded each acknowledgement. Each PostgreSQL failure ran on two nodes, and each MongoDB failure on three.

| Case | Longest interruption | Acknowledged writes lost |
| --- | --- | --- |
| PostgreSQL, `docker compose stop` of the primary | 1.5 s | 0 of 537 |
| PostgreSQL, `docker kill` of the primary | 20.8 s | 0 of 353 |
| PostgreSQL, `docker pause` of the primary, client timeout of 3 s | 22.8 s | 0 of 338 |
| PostgreSQL, `docker kill` of the standby | None | 0 of 536 |
| etcd killed, `failsafe_mode` off | 34.6 s, until etcd returned | 0 of 365 |
| etcd killed, `failsafe_mode` on | None | 0 of 675 |
| MongoDB, `docker stop` of the primary | None, slowest write 0.5 s | 0 of 395 |
| MongoDB, `docker kill` of the primary | 10.4 s | 0 of 313 |

With three PostgreSQL nodes, all nodes were stopped and then all were killed. The 1,000 rows were present both times, and the database was writable after 4 and 6 seconds.

Idle PostgreSQL nodes used 64 MB for the primary and 50 MB for each standby, and etcd used 17 MB. Fifteen nodes need about 0.85 GB, compared with 0.2 GB for the five single databases. MongoDB members used 90 to 200 MB after load. The four additional members need about 0.5 GB.

The connection settings were tested with the published Player, Session, Moderation, and Discord DMs images, the JDBC driver of the Server Rules image, and the pgx version of the ETL.
