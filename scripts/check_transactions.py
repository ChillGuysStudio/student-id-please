#!/usr/bin/env python3
"""Check that ending a shift commits or aborts in both Session and Player databases.

Runs five cases on the running stack: a normal commit, Player stopped at prepare,
a Broker restart between the phases, a Player and database restart after
prepare, and a repeated end. Each case uses a new shift with three players and no cases. The check
stops and starts containers, so run nothing else that does at the same time.
It prints no credentials. Name cases as arguments to run only those:
commit, player-stopped, broker-restart, participant-restart, repeat.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("seed", ROOT / "scripts/seed_university_catalog.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
BASE = seed.gateway_url()
DATABASES = {"session-db": "session_db", "player-db": "player_db"}


def compose(*args, check=True, timeout=120):
    result = subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"docker compose {args[0]} failed: {result.stderr.strip()[-300:]}")
    return result.stdout


def primary(name):
    for node in (f"{name}-{n}" for n in (1, 2, 3)):
        out = compose("exec", "-T", node, "psql", "-h", "/tmp", "-U", "postgres", "-AtqX", "-c",
                      "SELECT pg_is_in_recovery()", check=False)
        if out.strip() == "f":
            return node
    raise RuntimeError(name + " has no primary")


def sql(name, statement):
    """Run a read on a database primary and return its rows."""
    if name == "broker-db":
        command = ["exec", "-T", "broker-db", "psql", "-U", "broker", "-d", "broker"]
    else:
        command = ["exec", "-T", primary(name), "psql", "-h", "/tmp", "-U", "postgres", "-d", DATABASES[name]]
    out = compose(*command, "-AtqX", "-v", "ON_ERROR_STOP=1", "-c", statement)
    return [line.split("|") for line in out.splitlines() if line]


class Psql:
    """One open psql connection to a database primary, used to hold a row lock or to poll quickly."""

    def __init__(self, name):
        self.process = subprocess.Popen(
            ["docker", "compose", "exec", "-T", primary(name), "psql", "-h", "/tmp", "-U", "postgres",
             "-d", DATABASES[name], "-AtqX"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def ask(self, statement):
        marker = uuid.uuid4().hex
        self.process.stdin.write(statement + f"\n\\echo {marker}\n")
        self.process.stdin.flush()
        rows = []
        for line in self.process.stdout:
            if line.strip() == marker:
                return rows
            rows.append(line.strip())
        raise RuntimeError("psql ended")

    def close(self):
        self.process.stdin.write("\\q\n")
        self.process.stdin.close()
        self.process.wait(timeout=10)


def until(what, check, limit=90):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.5)
    raise RuntimeError(f"{what} did not happen within {limit} seconds")


def register(label):
    name = "tx" + uuid.uuid4().hex[:12]
    creds = {"username": name, "email": name + "@example.test", "password": uuid.uuid4().hex}
    status, player = seed.call(BASE, "POST", "/api/v1/players", {**creds, "display_name": "Transaction check " + label})
    assert status == 201, f"register: HTTP {status}"
    return player["player_id"], seed.login(BASE, creds)


def ok(name, expected, method, path, body=None, token=None):
    status, result = seed.call(BASE, method, path, body, token)
    assert status == expected, f"{name}: HTTP {status} {result.get('code', '')}"
    return result


def shift():
    """Start a shift with an owner and the two Junior Moderators it needs. Return the owner's token and the session ID."""
    owner, token = register("owner")
    team = ok("team", 201, "POST", "/api/v1/teams", {"name": "Transaction check " + uuid.uuid4().hex[:8]}, token)
    juniors = [register(f"junior {n}") for n in (1, 2)]
    for player_id, junior in juniors:
        friendship = ok("friend request", 201, "POST", "/api/v1/friendships", {"recipient_id": player_id}, token)
        ok("friend acceptance", 200, "PUT", f"/api/v1/friendships/{friendship['friendship_id']}/acceptance", {}, junior)
        ok("team member", 200, "POST", f"/api/v1/teams/{team['team_id']}/members", {"player_id": player_id}, token)
    sid = ok("session", 201, "POST", "/api/v1/sessions", {"team_id": team["team_id"]}, token)["session_id"]
    for _, junior in juniors:
        ok("join", 200, "POST", f"/api/v1/sessions/{sid}/participants", {}, junior)
    kinds = ["enrollment", "outlook_group", "course", "academic_year", "schedule", "fcim_message"]
    ok("permissions", 200, "PUT", f"/api/v1/sessions/{sid}/record-permissions", {"permissions": [
        {"player_id": player_id, "session_id": sid, "record_kinds": kinds[n * 3:n * 3 + 3]}
        for n, (player_id, _) in enumerate(juniors)]}, token)
    assert ok("start", 200, "POST", f"/api/v1/sessions/{sid}/start", {}, token)["status"] == "active"
    return token, sid


def end(token, sid, key):
    return seed.call(BASE, "POST", f"/api/v1/sessions/{sid}/end", {}, token, key)


def state(sid):
    """Return the session status, the ledger rows, the Broker states, and the prepared transactions."""
    # The Broker first: it records a transaction as finished only after every participant answered,
    # so the databases read afterwards already show the result.
    broker = [row[0] for row in sql("broker-db", "SELECT t.state FROM transactions t JOIN transaction_participants p "
                                    f"USING (transaction_id) WHERE p.service = 'player' AND p.payload->>'session_id' = '{sid}' "
                                    "ORDER BY t.created_at")]
    status = sql("session-db", f"SELECT status FROM sessions WHERE id = '{sid}'")[0][0]
    ledger = int(sql("player-db", f"SELECT count(*) FROM progression_ledger WHERE kind = 'shift' AND source_id = '{sid}'")[0][0])
    prepared = sum(int(sql(name, "SELECT count(*) FROM pg_prepared_xacts")[0][0]) for name in DATABASES)
    return status, ledger, broker, prepared


def settled(sid, last):
    """Wait until the shift's latest transaction reaches the state `last`, and return the state of both databases."""
    return until(last, lambda: (lambda value: value if value[2][-1:] == [last] else None)(state(sid)))


def player_ready():
    """Wait until Player serves requests through the Broker again, for example after it was stopped.

    A registration reaches Player. A request with a bad token would be answered by Gateway alone.
    """
    def registers():
        name = "txready" + uuid.uuid4().hex[:10]
        return seed.call(BASE, "POST", "/api/v1/players", {"username": name, "email": name + "@example.test",
                         "password": uuid.uuid4().hex, "display_name": "Transaction check readiness"})[0] == 201
    until("Player ready", registers, 120)


def pause_player_after_its_prepare(token, sid, key):
    """End the shift while Player is paused after it prepared. Session prepares after the pause, so the decision is commit."""
    containers = compose("ps", "-q", "player").split()
    hold, watch = Psql("session-db"), Psql("player-db")
    result = {}
    request = threading.Thread(target=lambda: result.update(answer=end(token, sid, key)))
    try:
        hold.ask(f"BEGIN; SELECT 1 FROM sessions WHERE id = '{sid}' FOR UPDATE;")
        request.start()
        until("Player's prepare", lambda: watch.ask(
            "SELECT count(*) FROM pg_prepared_xacts WHERE gid LIKE 'student-id:%:player';") == ["1"], 5)
        subprocess.run(["docker", "pause", *containers], check=True, capture_output=True)
    finally:
        # Ending the lock transaction lets Session prepare. The decision is then commit.
        hold.ask("COMMIT;")
        hold.close()
        watch.close()
    request.join(30)
    return result["answer"], containers


def case(title, run):
    started = time.monotonic()
    try:
        detail = run()
    except Exception as failure:  # Report every case, then fail.
        print(f"FAIL  {title}: {failure}", flush=True)
        return False
    finally:
        player_ready()
    print(f"ok    {title}: {detail} ({time.monotonic() - started:.1f} s)", flush=True)
    return True


def normal():
    token, sid = shift()
    status, body = end(token, sid, str(uuid.uuid4()))
    assert status == 200 and body["status"] == "ended", f"end: HTTP {status}"
    final = settled(sid, "committed")
    assert final == ("ended", 3, ["committed"], 0), final
    return "200, session ended, 3 ledger rows, Broker committed, nothing prepared"


def player_stopped():
    token, sid = shift()
    key = str(uuid.uuid4())
    compose("stop", "player")
    try:
        status, body = end(token, sid, key)
        after = state(sid)
    finally:
        compose("start", "player")
    assert (status, body.get("code")) == (503, "TRANSACTION_ABORTED"), f"end: HTTP {status} {body.get('code')}"
    # The Broker keeps sending Abort to Player until Player answers.
    assert after[:2] == ("active", 0) and after[2] in (["aborting"], ["aborted"]) and after[3] == 0, after
    player_ready()
    settled(sid, "aborted")
    status, _ = end(token, sid, key)
    assert status == 200, f"retry: HTTP {status}"
    final = settled(sid, "committed")
    assert final == ("ended", 3, ["aborted", "committed"], 0), final
    return "503 TRANSACTION_ABORTED with the shift active and no ledger row; the retry committed both"


def broker_restart():
    token, sid = shift()
    (status, _), containers = pause_player_after_its_prepare(token, sid, str(uuid.uuid4()))
    try:
        between = state(sid)
        compose("stop", "message-broker")
    finally:
        subprocess.run(["docker", "unpause", *containers], capture_output=True)
    compose("start", "message-broker")
    assert status == 200, f"end: HTTP {status}"
    assert between == ("ended", 0, ["committing"], 1), between
    final = settled(sid, "committed")
    assert final == ("ended", 3, ["committed"], 0), final
    return "200 with Player prepared and Broker committing; after the restart, recovery committed Player"


def participant_restart():
    token, sid = shift()
    (status, _), containers = pause_player_after_its_prepare(token, sid, str(uuid.uuid4()))
    try:
        between = state(sid)
        database = primary("player-db")
        compose("restart", database)
    finally:
        subprocess.run(["docker", "unpause", *containers], capture_output=True)
    compose("restart", "player")
    assert status == 200, f"end: HTTP {status}"
    assert between == ("ended", 0, ["committing"], 1), between
    final = settled(sid, "committed")
    assert final == ("ended", 3, ["committed"], 0), final
    return f"Player and {database} restarted with the transaction prepared, and it committed afterwards"


def repeated():
    token, sid = shift()
    key = str(uuid.uuid4())
    first = end(token, sid, key)
    settled(sid, "committed")
    again, other = end(token, sid, key), end(token, sid, str(uuid.uuid4()))
    assert first[0] == again[0] == other[0] == 200, (first[0], again[0], other[0])
    assert again[1] == first[1], "the retry returned a different body"
    final = state(sid)
    assert final == ("ended", 3, ["committed"], 0), final
    return "the same key returned the same 200, a new key returned 200, still 3 ledger rows and 1 transaction"


CASES = {"commit": ("normal commit", normal), "player-stopped": ("Player stopped at prepare", player_stopped),
         "broker-restart": ("Broker restart between phases", broker_restart),
         "participant-restart": ("Player and its database restart after prepare", participant_restart),
         "repeat": ("repeated end", repeated)}


def main(names):
    """Run the named cases, or all of them, in order."""
    unknown = set(names) - set(CASES)
    if unknown:
        sys.exit("unknown case: " + ", ".join(sorted(unknown)) + ". Cases: " + ", ".join(CASES))
    results = [case(*CASES[name]) for name in names or CASES]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
