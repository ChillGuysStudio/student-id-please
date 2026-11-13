# Service metrics and monitoring contract

This contract defines the metrics that every process exposes, how Prometheus finds the replicas, and the Grafana dashboards that the stack provisions. Prometheus and Grafana show the metrics. Loki and Promtail collect the logs for Grafana, as the [Logs](#logs) section defines. The stack adds no ELK or tracing platform. Records stay as the [logging contract](logging.md) defines them.

## Endpoint

Every process with a listener serves the Prometheus text format on a separate metrics listener:

```text
GET /metrics
```

| Setting | Owner and value |
| --- | --- |
| `METRICS_ADDRESS` | Every process. Listen address, `:9464`. Every process in the stack uses this port, because Discovery derives scrape targets from it. |

The listener serves only `GET /metrics` with `200` in the Prometheus text format, `Content-Type: text/plain; version=0.0.4; charset=utf-8`. Every other method or path returns `404` with no body. It runs outside the business admission gates and the control-call bound, and it accepts at most 2 concurrent requests. A third request receives `503`. A scrape reads in-memory values only. It never queries a database or calls another process. Successful scrapes log at `DEBUG`.

The metrics listener is private because nothing outside the Compose network can reach it:

- Compose publishes no metrics port. Only Gateway `:8080`, the DMs proxy `:8009`, Prometheus, and Grafana have host ports, all bound to `127.0.0.1`.
- No process advertises the metrics port as its `http_url` or `grpc_url`. The Broker dispatches only to those addresses, and Gateway sends only its public route table. Neither can forward a request to `/metrics`.
- The DMs proxy forwards to `discord-dms:8000`, the DMs HTTP listener. The metrics listener is another port.
- Gateway's public route table and its `:8083` listener have no metrics route.

The endpoint has no credential, like the private gRPC listeners. It exposes only the catalogue below: bounded counts, durations, and states. It contains no secret, token, player data, or request detail. A separate port keeps `/metrics` off every listener that business traffic reaches, including the DMs listener behind the proxy.

The Moderation publisher has no listener and exposes no metrics. The Broker's publish and delivery metrics count its events.

## Catalogue

All services share one catalogue. A metric name has one type, one unit, and one meaning in every language. Units are seconds for time, and counters end in `_total`.

A process never sets the `service` or `instance` label. Prometheus attaches both to every series from the target labels that [target discovery](#target-discovery) supplies. `service` is the registry name, or `discovery`. `instance` is the canonical instance ID.

Each label has a fixed set of values. A value outside its set is recorded as `unmatched` when the label is `route`, and is a bug otherwise. No label ever holds a player, session, case, request, event, attempt, or registration ID, a raw path or query, a URL, a token, or an error message.

| Label | Values |
| --- | --- |
| `transport` | `http`, `grpc` |
| `attempt` | `first`, `reroute` |
| `decision` | `sent`, `not_allowed`, `attempt_limit`, `no_budget`, `no_alternate` |
| `reason` | Queue rejections: `queue_full`, `queue_timeout`, `no_healthy_instances`. Dead letters: `rejected`, `exhausted`, `forbidden_pair`. Removals: `circuit_open`, `operator`, `shutdown`. |
| `state` | Deliveries: `pending`, `in_flight`. Registry records: `pending`, `ready`, `unhealthy`, `expired`, `removed`. |
| `version` | One value per build, the image version without `v` |
| `revision` | One value per build, the source commit |
| `route` | An HTTP route template, such as `/api/v1/sessions/{session_id}`, the full gRPC method name, or `unmatched`. The Broker labels all Gateway dispatch requests `gateway_dispatch`. |
| `status_class` | `2xx`, `3xx`, `4xx`, `5xx`. A gRPC result uses the `http_status` of its detail. A status without a detail uses the HTTP status of its code in the [status mapping](grpc.md#status-mapping). `OK` is `2xx`, and `CANCELLED` is `4xx`. |
| `target_service` | A registry name: `player`, `session`, `applicant`, `credential`, `rules`, `university_record`, `moderation`, `discord-dms`, `gateway`, `message-broker`, or `discovery` |
| `target_instance` | The canonical instance ID of a generation in the Broker's current snapshot |
| `outcome` | Defined per metric below |
| `topic` | A topic of the [topic catalogue](dead-letters.md#producers-and-consumers) |
| `subscriber` | A subscriber registry name from the same table |

### Every process

| Name | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `student_id_requests_total` | Counter | `transport`, `route`, `status_class` | Completed requests that the process served. Liveness paths and `/metrics` are not counted. |
| `student_id_request_duration_seconds` | Histogram | `transport`, `route` | Duration of the same requests, from receipt to the last response byte |
| `student_id_dependency_calls_total` | Counter | `target_service`, `outcome` | Outbound calls by result: `ok`, `rejected` for a non-qualifying error, `connection_error`, `timeout`, or `http_5xx`. The Broker counts its backend attempts in `student_id_broker_dispatch_total` instead. |
| `student_id_active_tasks` | Gauge | None | The `active_tasks` value of the [status snapshot](resilience.md#status-and-load). The Broker reports the sum over both gates. |
| `student_id_max_concurrent_tasks` | Gauge | None | The `max_concurrent_tasks` value of the same snapshot |
| `student_id_build_info` | Gauge | `version`, `revision` | Always 1. `version` is the image version without `v`, and `revision` is the source commit. |

Every histogram uses these bucket bounds, in seconds: `0.005`, `0.01`, `0.025`, `0.05`, `0.1`, `0.25`, `0.5`, `1`, `2.5`, `5`, `10`, `30`. The same bounds in every language let one query combine services.

### Message Broker

| Name | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `student_id_broker_dispatch_total` | Counter | `target_service`, `target_instance`, `attempt`, `outcome` | Targeted attempts, including policy reads. `attempt` is `first` or `reroute`. `outcome` is `ok`, `rejected`, `connection_error`, `timeout`, or `http_5xx`. |
| `student_id_broker_dispatch_duration_seconds` | Histogram | `target_service` | Duration of each targeted attempt |
| `student_id_broker_backend_in_flight` | Gauge | `target_service`, `target_instance` | The Broker's unfinished targeted attempts to the generation, `in_flight` in the [load formula](routing.md#load) |
| `student_id_broker_backend_load` | Gauge | `target_service`, `target_instance` | The load that selection uses. Only eligible generations have a series. |
| `student_id_broker_reroutes_total` | Counter | `target_service`, `decision` | Reroute decisions, with the `decision` values of the [routing contract](routing.md#logging) |
| `student_id_broker_breaker_trips_total` | Counter | `target_service` | Breaker trips |
| `student_id_broker_breaker_open` | Gauge | `target_service` | Generations that the breaker excludes now |
| `student_id_broker_queue_depth` | Gauge | `target_service` | Requests waiting in the targeted queue |
| `student_id_broker_queue_oldest_age_seconds` | Gauge | `target_service` | Wait time of the oldest waiting request, 0 when the queue is empty |
| `student_id_broker_queue_rejections_total` | Counter | `target_service`, `reason` | `queue_full`, `queue_timeout`, or `no_healthy_instances` |
| `student_id_broker_events_published_total` | Counter | `topic`, `outcome` | Publish requests: `published`, `duplicate`, or `rejected` |
| `student_id_broker_deliveries_total` | Counter | `topic`, `subscriber`, `outcome` | Delivery attempts: `delivered`, `retry`, or `dead_lettered` |
| `student_id_broker_deliveries` | Gauge | `topic`, `subscriber`, `state` | Stored deliveries in state `pending` or `in_flight` |
| `student_id_broker_delivery_oldest_pending_age_seconds` | Gauge | `topic`, `subscriber` | Age of the oldest `pending` delivery since its event was published, 0 when none |
| `student_id_broker_dead_letters` | Gauge | `topic`, `subscriber`, `reason` | Stored dead letters by reason: `rejected`, `exhausted`, or `forbidden_pair` |

The last three gauges come from `broker-db`. The Broker reads them every 5 seconds in the background with a 1-second deadline. A scrape returns the last successful read. When a read fails, the Broker drops those series until the next successful read, so a dashboard shows no data instead of an old value. The other values are in memory.

When a generation leaves the Broker's snapshot, the Broker deletes every series with its `target_instance`. Instance labels therefore stay bounded by the live replicas.

### Discovery

| Name | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `student_id_discovery_instances` | Gauge | `target_service`, `state` | Registry records by state: `pending`, `ready`, `unhealthy`, `expired`, or `removed` |
| `student_id_discovery_probes_total` | Counter | `target_service`, `outcome` | Status probes: `ready`, `unready`, `invalid`, or `failed` |
| `student_id_discovery_removals_total` | Counter | `target_service`, `reason` | Accepted removals: `circuit_open`, `operator`, or `shutdown` |

### Library metrics

A process may also expose the runtime metrics of its client library, such as `go_*`, `process_*`, `jvm_*`, or `python_*`, when their labels are bounded. Dashboards use only the catalogue. Each language uses its standard client: `github.com/prometheus/client_golang` for Go, the Micrometer Prometheus registry for Java, and `prometheus_client` for Python.

## Target discovery

Prometheus finds its targets through Discovery with `http_sd_configs`. Discovery serves the list on its existing HTTP listener, `DISCOVERY_ADDR`, at `:8081` in Compose:

```text
GET /sd/v1/targets
X-Control-Name: prometheus
X-Control-Token: <token>
```

Discovery authenticates the headers against `CONTROL_PLANE_TOKENS`. Only `prometheus` and `operator` may call this route. A missing or wrong credential returns `401`, and another principal returns `403`. Discovery's gRPC interceptor rejects the `prometheus` principal on every RPC with `PERMISSION_DENIED`, so the scrape credential cannot read or change the registry.

The response is `200` with `Content-Type: application/json`, in the [HTTP SD format](https://prometheus.io/docs/prometheus/latest/http_sd/):

```json
[
  {"targets": ["172.18.0.21:9464"], "labels": {"service": "applicant", "instance": "4b8f0c3e-6f5d-4c4a-9d55-0e7f1f0c2a11"}},
  {"targets": ["discovery:9464"], "labels": {"service": "discovery", "instance": "9a1d2f7c-3b4e-4f61-8a2b-5c6d7e8f9012"}}
]
```

- The list has one group for each registry record with an unexpired lease, in any state, except a record removed for `shutdown`. A replica removed by its breaker or the operator still runs, so it stays observable. An expired record and a shut-down replica leave the list, so Prometheus stops scraping them.
- The target is the host of the record's `grpc_url` with port `DISCOVERY_METRICS_PORT`, default `9464`. Each registrant already advertises its own container address there, so a replica added by `docker compose --scale` appears after its first registration. No registration field changes.
- Discovery adds itself with target `DISCOVERY_METRICS_TARGET` and its own instance ID. It is not in its own registry.
- Groups sort by service, then instance ID. The response has no other labels.

| Setting | Owner and value |
| --- | --- |
| `DISCOVERY_METRICS_PORT` | Discovery. Default `9464`, the port of every target. It equals the port of `METRICS_ADDRESS`. |
| `DISCOVERY_METRICS_TARGET` | Discovery. Default `discovery:9464`, its own target. |

Prometheus refreshes the list every 5 seconds. A new replica is scraped within one refresh after it registers. A replica that stops gracefully removes itself for `shutdown` and leaves at the next refresh. A replica that dies leaves when its lease expires, at most 15 seconds after its last renewal. If the route fails, Prometheus keeps its last list.

`scripts/setup.py` generates `PROMETHEUS_CONTROL_TOKEN` in `.env`, like the other control tokens, and writes the same value to `.local/stack/prometheus-control-token` with mode `0444`. Discovery's `CONTROL_PLANE_TOKENS` adds a `prometheus` entry. Prometheus reads the token from that file. No other service receives it.

## Prometheus

`config/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s
  scrape_timeout: 3s
  evaluation_interval: 5s
scrape_configs:
  - job_name: student-id
    http_sd_configs:
      - url: http://discovery:8081/sd/v1/targets
        refresh_interval: 5s
        http_headers:
          X-Control-Name:
            values: [prometheus]
          X-Control-Token:
            files: [/etc/prometheus/control-token]
```

The scrape uses `http` and the default path `/metrics`. The job applies no relabeling, because the target groups already carry `service` and `instance`.

## Grafana

Grafana provisions two data sources and three dashboards from files at startup. Nobody builds a dashboard by hand.

| File | Content |
| --- | --- |
| `config/grafana/provisioning/datasources/prometheus.yaml` | Data source `Prometheus`, UID `prometheus`, URL `http://prometheus:9090`, default |
| `config/grafana/provisioning/datasources/loki.yaml` | Data source `Loki`, UID `loki`, URL `http://loki:3100` |
| `config/grafana/provisioning/dashboards/student-id.yaml` | One file provider for `/var/lib/grafana/dashboards`, with `allowUiUpdates: false` |
| `config/grafana/dashboards/services.json` | Dashboard `Student ID services`, UID `student-id-services` |
| `config/grafana/dashboards/broker.json` | Dashboard `Student ID broker`, UID `student-id-broker` |
| `config/grafana/dashboards/logs.json` | Dashboard `Student ID logs`, UID `student-id-logs`, described under [Logs](#logs) |

The services and broker dashboards have the variable `service`, from `label_values(student_id_requests_total, service)`. It allows several values and `All`. Panels use `$__rate_interval`.

### Services dashboard

| Panel | Query |
| --- | --- |
| Request rate | `sum by (service) (rate(student_id_requests_total{service=~"$service"}[$__rate_interval]))` |
| Error ratio | `sum by (service) (rate(student_id_requests_total{service=~"$service", status_class="5xx"}[$__rate_interval])) / sum by (service) (rate(student_id_requests_total{service=~"$service"}[$__rate_interval]))` |
| Client errors | `sum by (service) (rate(student_id_requests_total{service=~"$service", status_class="4xx"}[$__rate_interval]))` |
| p50 and p95 latency | `histogram_quantile(0.95, sum by (service, le) (rate(student_id_request_duration_seconds_bucket{service=~"$service"}[$__rate_interval])))`, and the same with `0.5` |
| Load by replica | `student_id_active_tasks{service=~"$service"} / student_id_max_concurrent_tasks{service=~"$service"}` |
| Ready instances | `sum by (target_service) (student_id_discovery_instances{state="ready"})` |
| Unavailable instances | `sum by (target_service, state) (student_id_discovery_instances{state=~"unhealthy|removed"})` |
| Dependency failures | `sum by (service, target_service, outcome) (rate(student_id_dependency_calls_total{service=~"$service", outcome!="ok"}[$__rate_interval]))` |
| Scraped targets | `up{service=~"$service"}` |
| Versions | `student_id_build_info{service=~"$service"}`, as a table |

### Broker dashboard

| Panel | Query |
| --- | --- |
| Dispatch rate by replica | `sum by (target_service, target_instance) (rate(student_id_broker_dispatch_total{target_service=~"$service"}[$__rate_interval]))` |
| Load by replica | `student_id_broker_backend_load{target_service=~"$service"}` |
| In-flight attempts | `student_id_broker_backend_in_flight{target_service=~"$service"}` |
| Dispatch failures | `sum by (target_service, outcome) (rate(student_id_broker_dispatch_total{target_service=~"$service", outcome!="ok"}[$__rate_interval]))` |
| Attempt latency p95 | `histogram_quantile(0.95, sum by (target_service, le) (rate(student_id_broker_dispatch_duration_seconds_bucket{target_service=~"$service"}[$__rate_interval])))` |
| Reroutes | `sum by (target_service, decision) (increase(student_id_broker_reroutes_total{target_service=~"$service"}[$__range]))` |
| Breaker trips | `sum by (target_service) (increase(student_id_broker_breaker_trips_total[$__range]))` |
| Open breakers | `student_id_broker_breaker_open` |
| Targeted queue depth | `student_id_broker_queue_depth{target_service=~"$service"}` |
| Oldest targeted request | `student_id_broker_queue_oldest_age_seconds{target_service=~"$service"}` |
| Queue rejections | `sum by (target_service, reason) (rate(student_id_broker_queue_rejections_total[$__rate_interval]))` |
| Delivery outcomes | `sum by (topic, subscriber, outcome) (rate(student_id_broker_deliveries_total[$__rate_interval]))` |
| Pending deliveries | `student_id_broker_deliveries{state="pending"}` |
| Oldest pending delivery | `student_id_broker_delivery_oldest_pending_age_seconds` |
| Dead letters | `student_id_broker_dead_letters`, as a table by topic, subscriber, and reason |

The `service` variable of this dashboard filters `target_service`. The panels show the Broker's view of each destination.

## Logs

Every process already writes its records to stdout as the [logging contract](logging.md) defines. Compose sets the `json-file` logging driver on every application service (`x-logging` in `compose.yaml`, rotating at 10 MB with three files), because a daemon's default driver may be `local`, which writes no files that Promtail can read. Docker keeps the records in each container's `json-file` log. The collection path adds no code to any service:

```text
container stdout -> Docker json-file log -> Promtail -> Loki -> Grafana
```

- Promtail tails `/var/lib/docker/containers/*/*-json.log` through a read-only mount of that directory. It never mounts the Docker socket, and no component in the stack does. `DOCKER_CONTAINERS_DIR` in `.env` changes the host directory when Docker's data root is elsewhere.
- Promtail unwraps Docker's envelope, parses each line as JSON, and keeps only lines with a `service` field. PostgreSQL, Redis, Caddy, and the monitoring components write other formats and are dropped.
- Labels are only `service` and `level`, both bounded. `event`, `instance_id`, `request_id`, and every other field stay in the line, where `| json` reads them. A record's `ts` is its timestamp in Loki. Promtail drops the `filename` and `stream` labels, because the file name carries the container ID.
- Loki runs as one process with filesystem storage in the volume `loki-data`, with no authentication. Retention is 72 hours, enforced by its compactor. It publishes no host port. Only Grafana and Promtail reach it, on the Compose network.
- Records hold no tokens, assertions, tickets, query strings, or payloads, so Loki holds none. Promtail adds no fields. Logs still download through Gateway as the [logging contract](logging.md#administrator-download) defines.

### Logs dashboard

`Student ID logs` has these variables and panels. The variables `service` and `level` come from the Loki label values, allow several values, and have `All`. `search` is free text that filters with a literal match.

| Panel | Query |
| --- | --- |
| Log rate | `sum by (service, level) (count_over_time({service=~"$service", level=~"$level"} \|= "$search" [$__auto]))` |
| Logs | `{service=~"$service", level=~"$level"} \|= "$search"` |

## Compose

CPR adds four services for monitoring. None joins Discovery, and none has a metrics listener of its own.

| Service | Image | Host port | Storage and settings |
| --- | --- | --- | --- |
| `prometheus` | `prom/prometheus:v3.1.0` | `127.0.0.1:${PROMETHEUS_PORT:-9090}:9090` | Mounts `config/prometheus/prometheus.yml` and `.local/stack/prometheus-control-token` read-only. Volume `prometheus-data` at `/prometheus`. Flags `--config.file=/etc/prometheus/prometheus.yml`, `--storage.tsdb.path=/prometheus`, and `--storage.tsdb.retention.time=2d`. Depends on `discovery`. |
| `loki` | `grafana/loki:3.3.2` | None | Mounts `config/loki/loki.yml` read-only. Volume `loki-data` at `/loki`. Retention `72h`, no authentication. |
| `promtail` | `grafana/promtail:3.3.2` | None | Mounts `config/promtail/promtail.yml` read-only, `/var/lib/docker/containers` read-only, and the volume `promtail-positions`. Depends on `loki`. |
| `grafana` | `grafana/grafana:11.4.0` | `127.0.0.1:${GRAFANA_PORT:-3000}:3000` | Mounts `config/grafana/provisioning` and `config/grafana/dashboards` read-only. No volume, so every start provisions the same state. `GF_SECURITY_ADMIN_USER=admin`, `GF_SECURITY_ADMIN_PASSWORD` from `GRAFANA_ADMIN_PASSWORD`, `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`. Depends on `prometheus` and `loki`. |

`scripts/setup.py` generates `GRAFANA_ADMIN_PASSWORD` with the other passwords. It never prints it. The Prometheus UI has no login, so its port binds only to `127.0.0.1`. Every process sets `METRICS_ADDRESS: ':9464'` through the shared `x-registration` block, and Discovery sets it directly.

Prometheus runs as user `nobody`. The token file is mode `0444` for that reason, like the mounted public keys.

## Repository changes

| Repository | Change |
| --- | --- |
| Message Broker | The metrics listener, the common metrics, and the Broker metrics, including the `broker-db` reader and series deletion for departed generations |
| Discovery | The metrics listener, the common and Discovery metrics, `GET /sd/v1/targets`, `DISCOVERY_METRICS_PORT`, and the `prometheus` principal that only that route accepts |
| Gateway | The metrics listener and the common metrics, with public route templates as `route` |
| Player, Session | The metrics listener and the common metrics with `prometheus_client` |
| Moderation, Discord DMs | The same. The Moderation publisher process adds nothing. |
| Applicant, Credential, University Record, Server Rules | The metrics listener and the common metrics with Micrometer, on a management port at `:9464` that serves only `/metrics` |
| CPR | This contract, the Prometheus, Loki, Promtail, and Grafana services and configuration files, `PROMETHEUS_CONTROL_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, the `prometheus` entry in Discovery's `CONTROL_PLANE_TOKENS`, `METRICS_ADDRESS`, the architecture page, and the demonstration guide |

Each repository tests its own side: the exposition of every catalogue metric it owns, the label sets, the `404` for other paths, and the route template on an unmatched path. Discovery tests the target list for each state, a scaled replica, an expired record, and the credential rules.

## Verification

The released stack passes these checks with real services:

- `docker compose up -d --wait` from a clean checkout starts Prometheus and Grafana. `http://127.0.0.1:9090/targets` lists every replica and Discovery as `up`. Grafana at `http://127.0.0.1:3000` shows both dashboards after login, with no manual step.
- `docker compose up -d --no-deps --scale applicant=4 applicant` adds two `applicant` targets within 10 seconds. Scaling back to 2 removes them within 10 seconds.
- `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/metrics` and the same on port `8009` do not return the exposition. `docker compose exec discovery wget -qO- http://discovery:8081/sd/v1/targets` without the headers fails with `401`.
- Known traffic matches the counters. With no other traffic, read `sum(student_id_requests_total{service="gateway", route="/api/v1/players/me"})` and `sum(student_id_broker_dispatch_total{target_service="player"})` from the Prometheus query API, send 20 `GET /api/v1/players/me` requests, wait one scrape interval, and read both again. Each raw counter grew by exactly 20.
- The [read reroute check](routing.md#verification) shows `timeout` dispatches, reroutes with `decision="sent"`, one breaker trip, and one more `removed` instance. A rejected event shows a `dead_lettered` delivery and one more stored dead letter. The dashboards show each change.
- The routing checks with unequal load show diverging dispatch rates and converging `student_id_broker_backend_load`.
- `count by (__name__) ({__name__=~"student_id_.+"})` and `count({__name__=~"student_id_.+"})` show bounded series. No series has a label value that is a player, session, case, request, or event ID.
- Logs still download through Gateway as the [logging contract](logging.md#administrator-download) defines.
- `docker compose up -d --wait` starts Loki and Promtail. In Grafana, `Student ID logs` shows records of every service after a request through Gateway, and no PostgreSQL, Redis, or Caddy lines. `docker compose config` shows no mount of `docker.sock`. The Loki label list is exactly `service` and `level`: `docker compose exec loki wget -qO- http://127.0.0.1:3100/loki/api/v1/labels`.
