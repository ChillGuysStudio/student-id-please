"""Recreate the local Compose containers and verify retained domain data and keys."""
import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sql(service, user, database, query):
    return subprocess.check_output(["docker", "compose", "exec", "-T", service, "psql", "-U", user,
                                    "-d", database, "-At", "-c", query], cwd=ROOT, text=True)


def snapshot():
    with urllib.request.urlopen("http://localhost:8001/.well-known/jwks.json", timeout=5) as response:
        keys = json.load(response)
    players = sql("player-db", "player", "player_db", "SELECT id, xp FROM players ORDER BY id")
    sessions = sql("session-db", "session", "session_db",
                   "SELECT id, status, score, penalties, processed_count, university_snapshot_id "
                   "FROM sessions ORDER BY id")
    return keys, players, sessions


def main():
    before = snapshot()
    if not before[1] or not before[2]:
        raise SystemExit("Run the Postman collection first so both databases contain records.")
    subprocess.run(["docker", "compose", "down"], cwd=ROOT, check=True)
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "180"], cwd=ROOT, check=True)
    after = snapshot()
    if before != after:
        raise SystemExit("FAIL: persisted keys or domain data changed during container recreation")
    print("PASS: player IDs/XP, session totals/snapshot IDs, and the signing key survived container recreation.")


if __name__ == "__main__":
    main()
