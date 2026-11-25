#!/usr/bin/env python3
"""Kill the primary of each replicated database and check that it fails over.

For each database, write a marker, kill the primary, wait until another member
accepts a second marker, start the killed member, and wait until it has both.
Name databases as arguments to check only those. Run nothing else that stops
containers at the same time.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
POSTGRES = {"player-db": "player_db", "session-db": "session_db", "moderation-db": "moderation",
            "dms-db": "discord_dms", "rules-db": "server_rules"}
MONGO = ("mongodb", "university-mongodb")
# The contract allows 25 seconds for PostgreSQL and 15 seconds for MongoDB. Finding and killing the primary adds a little.
LIMIT = {"postgres": 30, "mongo": 20}
REJOIN = 90


def compose(*args, script=None):
    command = ["docker", "compose", *args]
    try:
        return subprocess.run(command, cwd=ROOT, input=script, text=True, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        # A commit can wait for a standby that is gone.
        return subprocess.CompletedProcess(command, 124, "", "")


def members(name):
    return [f"{name}-{n}" for n in (1, 2, 3)]


class Postgres:
    kind = "postgres"

    def __init__(self, name):
        self.name, self.database = name, POSTGRES[name]

    def sql(self, node, statement):
        result = compose("exec", "-T", node, "psql", "-h", "/tmp", "-U", "postgres", "-d", self.database, "-AtqX",
                         "-v", "ON_ERROR_STOP=1", script=statement)
        return result.stdout.split() if result.returncode == 0 else None

    def primary(self, skip=None):
        for node in members(self.name):
            if node != skip and self.sql(node, "SELECT pg_is_in_recovery()") == ["f"]:
                return node
        return None

    def write(self, node, marker):
        return self.sql(node, "SET statement_timeout = '3s'; CREATE SCHEMA IF NOT EXISTS failover_check; "
                        "CREATE TABLE IF NOT EXISTS failover_check.markers (id uuid); "
                        f"INSERT INTO failover_check.markers VALUES ('{marker}')") is not None

    def read(self, node):
        return self.sql(node, "SELECT id FROM failover_check.markers") or []

    def rejoined(self, node):
        return self.sql(node, "SELECT pg_is_in_recovery()") == ["t"]

    def clean(self, node):
        self.sql(node, "DROP SCHEMA IF EXISTS failover_check CASCADE")


class Mongo:
    kind = "mongo"

    def __init__(self, name):
        self.name = name

    def run(self, node, script):
        # MONGO_ADMIN_* is in every member's environment, and the script goes through standard input.
        result = compose("exec", "-T", node, "sh", "-c", 'mongosh --quiet -u "$MONGO_ADMIN_USERNAME" -p "$MONGO_ADMIN_PASSWORD" '
                         "--authenticationDatabase admin --host 127.0.0.1 --file /dev/stdin", script=script)
        try:
            return json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else None
        except (IndexError, ValueError):
            return None

    def primary(self, skip=None):
        for node in members(self.name):
            if node != skip and self.run(node, "print(JSON.stringify(db.hello().isWritablePrimary))"):
                return node
        return None

    def write(self, node, marker):
        return self.run(node, "db.getSiblingDB('failover_check').markers.insertOne({_id: '%s'}, "
                        "{writeConcern: {w: 'majority', wtimeout: 3000}}); print('true')" % marker) is True

    def read(self, node):
        return self.run(node, "db.getMongo().setReadPref('secondaryPreferred'); "
                        "print(JSON.stringify(db.getSiblingDB('failover_check').markers.find().toArray().map(d => d._id)))") or []

    def rejoined(self, node):
        return self.run(node, "print(JSON.stringify(db.hello().secondary))") is True

    def clean(self, node):
        self.run(node, "db.getSiblingDB('failover_check').dropDatabase(); print('true')")


def wait(limit, check):
    """Return the first truthy result of check, or None after limit seconds."""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if result := check():
            return result
        time.sleep(0.5)
    return None


def failover(database):
    """Return (killed, new primary, seconds) or raise RuntimeError."""
    old = database.primary()
    if not old:
        raise RuntimeError("no primary at the start")
    before, after = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        return kill_and_check(database, old, before, after)
    finally:
        database.clean(database.primary() or old)


def kill_and_check(database, old, before, after):
    if not database.write(old, before):
        raise RuntimeError("the first write failed")
    if compose("kill", old).returncode:
        raise RuntimeError(f"could not kill {old}")
    started = time.monotonic()
    try:
        def promoted():
            node = database.primary(skip=old)
            return node if node and database.write(node, after) else None
        new = wait(LIMIT[database.kind], promoted)
        seconds = time.monotonic() - started
    finally:
        compose("start", old)
    if not new:
        raise RuntimeError(f"no member accepted a write within {LIMIT[database.kind]} seconds")
    if not wait(REJOIN, lambda: database.rejoined(old)):
        raise RuntimeError(f"{old} did not rejoin within {REJOIN} seconds")
    if not wait(REJOIN, lambda: {before, after} <= set(database.read(old))):
        raise RuntimeError(f"{old} misses a marker")
    if not {before, after} <= set(database.read(new)):
        raise RuntimeError(f"{new} misses a marker")
    return old, new, seconds


def main(names):
    known = [*POSTGRES, *MONGO]
    unknown = sorted(set(names) - set(known))
    if unknown:
        sys.exit(f"Unknown database: {', '.join(unknown)}. Choose from: {', '.join(known)}")
    failed = False
    for name in names or known:
        try:
            old, new, seconds = failover(Postgres(name) if name in POSTGRES else Mongo(name))
            print(f"ok      {name}: killed {old}, {new} accepted writes after {seconds:.1f} s, {old} rejoined with both markers", flush=True)
        except RuntimeError as error:
            failed = True
            print(f"failed  {name}: {error}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
