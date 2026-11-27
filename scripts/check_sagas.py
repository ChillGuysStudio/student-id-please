#!/usr/bin/env python3
"""Check that ending a shift runs as a saga, survives failures, and compensates.

Runs five cases on the running stack: a normal run, a Player outage that
delays the saga, a permanent failure that compensates, a Broker restart
mid-saga, and a repeated step. Each case uses a new shift with three players
and no cases, and prints the saga from the administrator listing. The check
stops and starts containers, so run nothing else that does at the same time.
It prints no credentials. Name cases as arguments to run only those:
normal, player-outage, compensation, broker-restart, repeated-step.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
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


def saga(sid):
    """Return the saga state and its steps as (operation, state, attempts) from broker-db, newest saga last."""
    rows = sql("broker-db", "SELECT s.saga_id, s.state, st.operation, st.state, st.attempts, st.compensation_attempts "
               "FROM sagas s JOIN saga_steps st USING (saga_id) WHERE s.saga_id IN (SELECT saga_id FROM saga_steps "
               f"WHERE operation = 'award-shift' AND payload->>'session_id' = '{sid}') ORDER BY s.created_at, st.position")
    sagas = {}
    for saga_id, state, operation, step, attempts, compensations in rows:
        sagas.setdefault(saga_id, [state, []])[1].append((operation, step, int(attempts), int(compensations)))
    return list(sagas.values())


def state(sid):
    """Return the latest saga state, the session status, and the shift's ledger rows by kind."""
    sagas = saga(sid)
    status = sql("session-db", f"SELECT status FROM sessions WHERE id = '{sid}'")[0][0]
    rows = sql("player-db", "SELECT kind, count(*) FROM progression_ledger "
               f"WHERE source_id = '{sid}' AND kind IN ('shift', 'shift_reversal') AND saga_id IS NOT NULL GROUP BY kind")
    return (sagas[-1][0] if sagas else None), status, {kind: int(n) for kind, n in rows}


def settled(sid, final):
    return until(final, lambda: (lambda value: value if value[0] == final else None)(state(sid)))


def player_ready():
    """Wait until Player serves requests through the Broker again. A registration reaches Player."""
    def registers():
        name = "sagaready" + uuid.uuid4().hex[:10]
        return seed.call(BASE, "POST", "/api/v1/players", {"username": name, "email": name + "@example.test",
                         "password": uuid.uuid4().hex, "display_name": "Saga check readiness"})[0] == 201
    until("Player ready", registers, 120)


def listing(sid):
    """Return the shift's latest saga from the administrator listing, as one line."""
    saga_id = sql("broker-db", "SELECT saga_id FROM saga_steps WHERE operation = 'award-shift' "
                  f"AND payload->>'session_id' = '{sid}' ORDER BY saga_id")
    # After a Broker restart, requests reach Player again a little later than the saga completes.
    player_ready()
    creds = seed.load_credentials(BASE)
    seed.set_admin(creds["player_id"], "--grant")
    try:
        token = seed.login(BASE, creds)
        page = ok("listing", 200, "GET", "/api/v1/admin/broker/sagas?limit=20&flow=end-shift", token=token)
    finally:
        seed.set_admin(creds["player_id"], "--revoke")
    wanted = {row[0] for row in saga_id}
    items = [item for item in page["items"] if item["saga_id"] in wanted]
    assert items, "the listing does not show the saga"
    item = items[0]
    steps = " ".join(f"{s['operation']}={s['state']}/{s['attempts']}" + (f"+{s['compensation_attempts']}c" if s["compensation_attempts"] else "")
                     for s in item["steps"])
    cause = item["cause"] and f" cause {item['cause']['kind']}:{item['cause'].get('code')}"
    return f"{item['state']}: {steps}{cause or ''}"


def paused(containers):
    subprocess.run(["docker", "pause", *containers], check=True, capture_output=True)


def unpaused(containers):
    subprocess.run(["docker", "unpause", *containers], capture_output=True)


def case(title, run):
    started = time.monotonic()
    try:
        detail = run()
    except Exception as failure:  # Report every case, then fail.
        print(f"FAIL  {title}: {failure}", flush=True)
        return False
    finally:
        player_ready()
    print(f"ok    {title} ({time.monotonic() - started:.1f} s)\n      {detail}", flush=True)
    return True


def normal():
    token, sid = shift()
    key = str(uuid.uuid4())
    status, body = end(token, sid, key)
    assert status == 200 and body["status"] == "ended", f"end: HTTP {status}"
    assert state(sid) == ("completed", "ended", {"shift": 3}), state(sid)
    again = end(token, sid, key)
    assert again[0] == 200 and again[1] == body, "a retry with the same key returned another response"
    return "200 ended, 3 award rows, retry returned the same 200. Listing: " + listing(sid)


def player_outage():
    token, sid = shift()
    compose("stop", "player")
    try:
        status, body = end(token, sid, str(uuid.uuid4()))
        during = state(sid)
    finally:
        compose("start", "player")
    assert status == 202 and body["status"] == "ending", f"end: HTTP {status} {body.get('status')}"
    assert during == ("running", "ending", {}), during
    player_ready()
    final = settled(sid, "completed")
    assert final == ("completed", "ended", {"shift": 3}), final
    return "202 ending while Player was stopped, then completed with 3 award rows. Listing: " + listing(sid)


def compensation():
    token, sid = shift()
    owner = sql("session-db", f"SELECT owner_id FROM sessions WHERE id = '{sid}'")[0][0]
    # An earlier award with other values makes Player reject this saga's award for good.
    sql("player-db", "INSERT INTO progression_ledger (id, player_id, kind, source_id, delta) "
        f"VALUES ('{uuid.uuid4()}', '{owner}', 'shift', '{sid}', 7) RETURNING id")
    key = str(uuid.uuid4())
    status, body = end(token, sid, key)
    assert status in (202, 409), f"end: HTTP {status}"
    final = settled(sid, "compensated")
    assert final == ("compensated", "active", {}), final
    again = end(token, sid, key)
    assert (again[0], again[1].get("code")) == (409, "PROGRESSION_REJECTED"), f"retry: HTTP {again[0]} {again[1].get('code')}"
    return (f"end {status}, saga compensated, shift active again, no award rows; the retry returned "
            "409 PROGRESSION_REJECTED. Listing: " + listing(sid))


def broker_restart():
    token, sid = shift()
    containers = compose("ps", "-q", "player").split()
    paused(containers)
    try:
        status, body = end(token, sid, str(uuid.uuid4()))
        during = state(sid)
        compose("stop", "message-broker")
    finally:
        unpaused(containers)
    compose("start", "message-broker")
    assert status == 202 and body["status"] == "ending", f"end: HTTP {status} {body.get('status')}"
    assert during[:2] == ("running", "ending"), during
    final = settled(sid, "completed")
    assert final == ("completed", "ended", {"shift": 3}), final
    steps = saga(sid)[-1][1]
    assert steps[0][2] == 1, f"hold-shift ran again: {steps[0]}"
    return "202 ending, the Broker restarted mid-saga, recovery completed it. Listing: " + listing(sid)


def repeated_step():
    token, sid = shift()
    containers = compose("ps", "-q", "player").split()
    paused(containers)
    try:
        status, _ = end(token, sid, str(uuid.uuid4()))
        # Recovery sends the award again while the first call still waits in the paused Player.
        until("a repeated award", lambda: saga(sid)[-1][1][1][2] >= 2, 30)
    finally:
        unpaused(containers)
    assert status == 202, f"end: HTTP {status}"
    final = settled(sid, "completed")
    assert final == ("completed", "ended", {"shift": 3}), final
    attempts = saga(sid)[-1][1][1][2]
    return f"the award was sent {attempts} times and applied once: 3 award rows. Listing: " + listing(sid)


CASES = {"normal": ("normal run", normal), "player-outage": ("Player outage delays the saga", player_outage),
         "compensation": ("permanent failure compensates", compensation),
         "broker-restart": ("Broker restart mid-saga", broker_restart),
         "repeated-step": ("repeated step", repeated_step)}


def main(names):
    """Run the named cases, or all of them, in order."""
    unknown = set(names) - set(CASES)
    if unknown:
        sys.exit("unknown case: " + ", ".join(sorted(unknown)) + ". Cases: " + ", ".join(CASES))
    results = [case(*CASES[name]) for name in names or CASES]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
