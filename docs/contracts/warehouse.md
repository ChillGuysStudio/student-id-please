# Warehouse and ETL contract

The warehouse is a PostgreSQL database, `warehouse-db`, that holds an analytics copy of service data. The ETL service extracts rows from the eight domain services' datastores, transforms them, and loads them into the warehouse. No service reads the warehouse to serve a request.

## The storage exception

Each service owns its storage, and other services use its APIs or events. The ETL is the only exception. It reads the datastores directly because no API returns the complete history, and eight export APIs would exist only to feed one copy.

The exception is narrow:

- The ETL connects to each datastore as `warehouse_reader`, which can read only the columns in this document. The database enforces the list. A query for another column fails.
- The ETL writes only to `warehouse-db`.
- A service may change its storage at any time. A change to a listed column must update this document and the ETL.

In PostgreSQL, the role holds `CONNECT`, `USAGE` on the schema, and column-level `SELECT` grants. MongoDB has no field-level grants. Each source collection therefore has a view named `warehouse_<collection>` that projects the listed fields, and the role can run `find` on those views only. Both MongoDB deployments run with authentication enabled.

## Data that never leaves its source

The warehouse does not hold these values, and the reader role cannot read them where the database stores them in their own column or field:

- Password hashes, email addresses, refresh tokens, chat tickets, idempotency keys, and request hashes.
- Chat message text, decision and ban reasons, and the policy snapshot of a decision.
- Case generation data, which is the scenario, the seed, and the subject.
- Case evidence, which is claims, documents, validation results, authenticity, and university records.
- University reference data about a person, and university identities.
- Inbox, outbox, and retained attempt payloads.

Case evidence appears only as a count. A decision appears only after the service commits it.

## Model

Dimension and fact tables live in the `warehouse` schema. Keys are the source identifiers. There are no foreign keys between tables, because sources load independently and a fact can arrive before its dimension.

| Table | Key | Columns |
| --- | --- | --- |
| `dim_date` | `date_key` | `day`, `year`, `month`, `day_of_month`, `iso_weekday` |
| `dim_player` | `player_id` | `display_name`, `is_admin`, `xp`, `registered_at` |
| `dim_team` | `team_id` | `name`, `owner_id`, `member_count` |
| `dim_shift` | `session_id` | `team_id`, `owner_id`, `status`, `rule_version`, `created_at`, `started_at`, `ended_at`, `duration_seconds`, `participant_count` |
| `bridge_shift_participant` | `session_id`, `player_id` | `role` |
| `dim_case` | `request_id` | `case_id`, `session_id`, `entry_service`, `state`, `decision_id` |
| `dim_rule_version` | `rule_version` | `status`, `created_at` |
| `dim_profile_preset` | `preset_id` | `role`, `university_status`, `major`, `study_year`, `course_count`, `enabled`, `created_at` |
| `dim_credential_template` | `template_id` | `kind`, `issuer`, `validity_days`, `enabled`, `created_at` |
| `fact_decision` | `decision_id` | `session_id`, `case_id`, `moderator_id`, `date_key`, `action`, `correct`, `score_delta`, `penalty`, `decided_at` |
| `fact_shift_score` | `session_id` | `date_key`, `processed_count`, `score`, `penalties` |
| `fact_progression` | `entry_id` | `player_id`, `kind`, `source_id`, `xp_delta` |
| `fact_disciplinary_action` | `action_id` | `player_id`, `date_key`, `xp_penalty`, `applied_at` |
| `fact_ban` | `ban_id` | `case_id`, `date_key`, `banned_at` |
| `fact_chat_activity` | `session_id`, `channel`, `author_id`, `hour` | `date_key`, `message_count` |
| `fact_case_evidence` | `case_id`, `owner` | `session_id`, `state`, `item_count` |
| `fact_university_catalogue` | `kind` | `entry_count` |

Every row also has `loaded_at`, the time the ETL last changed it. Snapshot tables have `removed_at`, described in [load modes](#load-modes).

## Sources

The mode column names how the ETL reads each table.

### PostgreSQL

| Service | Table | Columns read | Mode | Target and transformation |
| --- | --- | --- | --- | --- |
| Player | `players` | `id`, `display_name`, `is_admin`, `xp`, `created_at` | Snapshot | `dim_player`. The ISO 8601 text becomes a timestamp. |
| Player | `teams` | `id`, `name`, `owner_id` | Snapshot | `dim_team` |
| Player | `team_members` | `team_id`, `player_id` | Snapshot | Counted into `dim_team.member_count` |
| Player | `progression_ledger` | `id`, `player_id`, `kind`, `source_id`, `delta` | Snapshot | `fact_progression` |
| Session | `sessions` | `id`, `team_id`, `owner_id`, `status`, `participants`, `rule_version`, `created_at`, `started_at`, `ended_at`, `processed_count`, `score`, `penalties` | Snapshot | `dim_shift` with the computed duration and participant count, `fact_shift_score` for ended shifts, and one `bridge_shift_participant` row for each participant |
| Session | `cases` | `request_id`, `session_id`, `entry_service`, `case_id`, `state`, `decision_id` | Snapshot | `dim_case` |
| Moderation | `decisions` | `decision_id`, `session_id`, `case_id`, `moderator_id`, `action`, `correct`, `score_delta`, `penalty`, `created_at` | Append | `fact_decision` |
| Moderation | `bans` | `ban_id`, `source_case_id`, `created_at` | Append | `fact_ban` |
| Moderation | `disciplinary_actions` | `disciplinary_action_id`, `player_id`, `xp_penalty`, `created_at` | Append | `fact_disciplinary_action` |
| Discord DMs | `channels` | `channel_id`, `session_id`, `name` | With `messages` | Joined into `fact_chat_activity` |
| Discord DMs | `messages` | `channel_id`, `author_id`, `sent_at` | Append | `fact_chat_activity`. The source counts messages for each hour. |
| Server Rules | `rule_versions` | `id`, `status`, `created_at` | Snapshot | `dim_rule_version` |

### MongoDB

| Service | Collection | Fields in the view | Mode | Target and transformation |
| --- | --- | --- | --- | --- |
| Applicant | `applicant_cases` | `_id`, `sessionId`, `state`, and `itemCount`, which is 1 when claims exist | Snapshot | `fact_case_evidence` with owner `applicant` |
| Applicant | `profile_presets` | `_id`, `role`, `universityStatus`, `major`, `year`, `courseCount`, `enabled`, `createdAt` | Snapshot | `dim_profile_preset` |
| Credential | `credential_cases` | `_id`, `sessionId`, `state`, and `itemCount`, which is the number of documents | Snapshot | `fact_case_evidence` with owner `credential` |
| Credential | `credential_templates` | `_id`, `kind`, `issuer`, `validityDays`, `enabled`, `createdAt` | Snapshot | `dim_credential_template` |
| University Record | `university_cases` | `_id`, `sessionId`, `state`, and `itemCount`, which is the number of records | Snapshot | `fact_case_evidence` with owner `university_record` |
| University Record | `university_data` | `kind` | Snapshot | Counted into `fact_university_catalogue` |

The view computes `itemCount`, so evidence never reaches the ETL. A document without an expected field loads with a null in that column. A document without an `_id` or with an identifier that is not a UUID is skipped and counted as rejected.

## Load modes

**Snapshot.** The ETL reads every listed row in one read transaction and upserts it. A row that the source no longer returns gets `removed_at`. The ETL never deletes a warehouse row, except that it replaces the participants of a shift it loads. This mode is for tables whose rows change or that have no timestamp. Most source tables have no `updated_at` column, so a cursor would miss their changes.

**Append.** The rows never change after insert, and the source has an insert timestamp. The ETL reads rows from the cursor minus ten minutes and upserts them by identifier. The overlap catches a transaction that committed after a later timestamp was read. For chat, the ETL truncates the start to the hour and replaces the counts of each hour it reads. The cursor is the greatest timestamp loaded.

A rerun changes no row whose values are equal, so it adds no duplicates and keeps `loaded_at`.

## Runs and failures

Each service is one source: `player`, `session`, `moderation`, `discord-dms`, `rules`, `applicant`, `credential`, and `university_record`. The ETL commits the rows and cursors of a source in one warehouse transaction. A source that fails rolls back and the other sources still load.

`warehouse.etl_runs` records one row for each source and run, with `run_id`, `source`, `outcome`, `rows_read`, `rows_written`, `rows_rejected`, `error_kind`, `started_at`, and `finished_at`. `warehouse.etl_cursors` holds one timestamp for each append table.

| Outcome | Meaning |
| --- | --- |
| `ok` | All rows of the source loaded. |
| `partial` | The source loaded and at least one document was rejected. |
| `failed` | The source did not load. `error_kind` is `unavailable`, `unauthorized`, `schema`, `timeout`, or `internal`. |

An advisory lock in `warehouse-db` allows one run at a time. A second run exits with outcome `skipped` and writes nothing. `etl --once` exits with status 0 when every source is `ok` or `partial`, 3 when the run is skipped, and 1 otherwise. Without `--once`, the ETL runs every `ETL_INTERVAL`, five minutes by default, and a failed source does not stop it.

The ETL applies its warehouse migrations at startup. Each source has a timeout, `ETL_SOURCE_TIMEOUT`, 60 seconds by default.

## Logs

Records follow the [logging contract](logging.md) with `service` set to `etl`. The ETL writes one `etl_source` record for each source with `run_id`, `source`, `outcome`, `rows_read`, `rows_written`, `rows_rejected`, and `duration_ms`, and one `etl_run` record for the run. A failure adds `error_kind`. No record holds a connection string, a row value, or a driver error message.

## Verification

- As `warehouse_reader`, selecting `players.password_hash`, `messages.text`, or `decisions.policy` fails with a permission error, and reading `applicant_cases` directly fails with an authorization error.
- After a played shift, `etl --once` fills each fact table. A second run reports zero `rows_written`.
- With one source stopped, the run reports that source as `failed` and loads the other seven.
- A test compares the columns the ETL selects with the tables in this document.
