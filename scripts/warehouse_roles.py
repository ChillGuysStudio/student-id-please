#!/usr/bin/env python3
"""Create the warehouse_reader role and views on each datastore of the running stack.

Run it after the services have created their tables. A rerun converges on the
same grants. The columns come from docs/contracts/warehouse.md.
"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROLE = "warehouse_reader"

# Compose service: (user, database, {table: columns}).
POSTGRES = {
    "player-db": ("player", "player_db", {
        "players": "id, display_name, is_admin, xp, created_at",
        "teams": "id, name, owner_id",
        "team_members": "team_id, player_id",
        "progression_ledger": "id, player_id, kind, source_id, delta"}),
    "session-db": ("session", "session_db", {
        "sessions": "id, team_id, owner_id, status, participants, rule_version, created_at, started_at, ended_at, "
                    "processed_count, score, penalties",
        "cases": "request_id, session_id, entry_service, case_id, state, decision_id"}),
    "moderation-db": ("moderation", "moderation", {
        "decisions": "decision_id, session_id, case_id, moderator_id, action, correct, score_delta, penalty, created_at",
        "bans": "ban_id, source_case_id, created_at",
        "disciplinary_actions": "disciplinary_action_id, player_id, xp_penalty, created_at"}),
    "dms-db": ("discord_dms", "discord_dms", {
        "channels": "channel_id, session_id, name",
        "messages": "channel_id, author_id, sent_at"}),
    "rules-db": ("server_rules", "server_rules", {"rule_versions": "id, status, created_at"}),
}


def fields(*names):
    return {name: 1 for name in names}


def case(item_count):
    return {"sessionId": 1, "state": 1, "itemCount": item_count}


def size(field):
    return {"$size": {"$ifNull": ["$" + field, []]}}


# Compose service: {database: {collection: projection}}. The projections keep _id unless they drop it.
MONGO = {
    "mongodb": {
        "applicant": {
            "applicant_cases": case({"$cond": [{"$ifNull": ["$claims", False]}, 1, 0]}),
            "profile_presets": fields("role", "universityStatus", "major", "year", "courseCount", "enabled", "createdAt")},
        "credential": {
            "credential_cases": case(size("credentials")),
            "credential_templates": fields("kind", "issuer", "validityDays", "enabled", "createdAt")}},
    "university-mongodb": {
        "university_records": {
            "university_cases": case(size("records")),
            "university_data": {"_id": 0, "kind": 1}}},
}

MONGO_SCRIPT = """
const {databases, role, password} = %s;
for (const [name, views] of Object.entries(databases)) {
  const target = db.getSiblingDB(name);
  const privileges = [];
  for (const [collection, projection] of Object.entries(views)) {
    const view = "warehouse_" + collection, pipeline = [{$project: projection}];
    if (target.getCollectionInfos({name: view}).length) {
      target.runCommand({collMod: view, viewOn: collection, pipeline});
    } else {
      target.createView(view, collection, pipeline);
    }
    privileges.push({resource: {db: name, collection: view}, actions: ["find"]});
  }
  if (target.getRole(role)) target.updateRole(role, {privileges, roles: []});
  else target.createRole({role, privileges, roles: []});
  if (target.getUser(role)) target.updateUser(role, {pwd: password, roles: [role]});
  else target.createUser({user: role, pwd: password, roles: [role]});
}
"""


def postgres_script(database, tables, password):
    literal = password.replace("'", "''")
    lines = [
        "\\set ON_ERROR_STOP on", "BEGIN;", "SET LOCAL log_statement = 'none';",
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN CREATE ROLE {ROLE}; END IF; END $$;",
        f"ALTER ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{literal}';",
        f"ALTER ROLE {ROLE} SET default_transaction_read_only = on;",
        # Revoking a table privilege also revokes its column privileges.
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};",
        f"GRANT CONNECT ON DATABASE {database} TO {ROLE};", f"GRANT USAGE ON SCHEMA public TO {ROLE};",
    ]
    lines += [f"GRANT SELECT ({columns}) ON {table} TO {ROLE};" for table, columns in tables.items()]
    return "\n".join(lines + ["COMMIT;", ""])


def mongo_script(databases, password):
    return MONGO_SCRIPT % json.dumps({"databases": databases, "role": ROLE, "password": password})


def reader_password(text):
    for line in text.splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "WAREHOUSE_READER_PASSWORD" and value.strip().strip("'\""):
            return value.strip().strip("'\"")
    raise ValueError("Set WAREHOUSE_READER_PASSWORD in .env")


def execute(service, command, script):
    """Run a script in a container. It goes through stdin, so no password is in an argument list."""
    result = subprocess.run(["docker", "compose", "exec", "-T", service, "sh", "-c", command],
                            cwd=ROOT, input=script, text=True, capture_output=True)
    if result.returncode:
        # Server messages can quote the statement, so only the kind of failure is shown.
        hint = next((hint for hint in ("does not exist", "is not running", "Authentication failed")
                     if hint in result.stderr + result.stdout), "see the container log")
        raise RuntimeError(f"{service}: {hint}")


def main():
    try:
        password = reader_password((ROOT / ".env").read_text())
    except (OSError, ValueError) as error:
        sys.exit(f"Warehouse roles failed: {error}")
    failed = False
    for service, (user, database, tables) in POSTGRES.items():
        failed |= not report(service, f"psql -q -U {user} -d {database}", postgres_script(database, tables, password))
    for service, databases in MONGO.items():
        failed |= not report(service, 'mongosh --quiet --host 127.0.0.1 -u "$MONGO_INITDB_ROOT_USERNAME" '
                             '-p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --file /dev/stdin',
                             mongo_script(databases, password))
    sys.exit(1 if failed else 0)


def report(service, command, script):
    try:
        execute(service, command, script)
    except RuntimeError as error:
        print(f"failed  {error}")
        return False
    print(f"ok      {service}")
    return True


if __name__ == "__main__":
    main()
