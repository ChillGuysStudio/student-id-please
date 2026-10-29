"""Grade 6: the same first write sent to both replicas at once leaves one durable record and one idempotency record."""
from __future__ import annotations

import datetime
import json
import time
import uuid
from collections import Counter

from ..model import Case, Mutation, Suite
from .flow import UNCERTAIN, Flow, create_case, prepare_session, safe, until

ATTEMPTS = 4


def _admin_token(ctx) -> str:
    """Grant admin to demo player 2 through the operator command, and register the revoke. Returns an admin token."""
    stack = ctx.stack
    player_id = str(uuid.UUID(stack.players()["player2"]))

    def is_admin():
        return stack.psql("player-db", "player", "player_db", f"SELECT json_build_object('a',is_admin) FROM players WHERE id='{safe(player_id)}';")["a"]

    def command(action):
        code = "import json,sys; from app.admin import main; c=json.load(sys.stdin); main([c['player_id'],c['action']])"
        return stack.docker("exec", "-i", stack.container("player"), "python", "-c", code,
                            input=json.dumps({"player_id": player_id, "action": action}), timeout=40)

    ctx.expect(is_admin() is False, "demo player 2 is already admin, so the suite will not touch it")

    def revoke():
        done = command("--revoke")
        stack.forget_token(2)
        if done.returncode or is_admin() is not False:
            raise RuntimeError("admin revoke did not take effect")
    ctx.on_exit("revoke admin from demo player 2", revoke)
    ctx.expect(command("--grant").returncode == 0 and is_admin() is True, "admin grant failed")
    return stack.fresh_login(2)


def _race(ctx, flow, label, path, token, body_for, services, durable, idem, success=frozenset({201}), prepare=None, mark=True):
    """Send the same body with the same key twice at once. Repeat with fresh data if the logs do not show both replicas."""
    stack = ctx.stack
    for attempt in range(1, ATTEMPTS + 1):
        tag = ctx.label(f"{label}-{attempt}")
        extra = prepare(attempt) if prepare else {}
        body = body_for(tag, extra)
        key = ctx.key(f"race/{label}/{attempt}")
        before = idem(extra)
        marker = f"{label}-{attempt}"
        outcome = {}
        started = datetime.datetime.now(datetime.timezone.utc)
        seen = rf"vf={ctx.run_id}-race-{marker} HTTP" if mark else rf"POST {path} HTTP"
        with ctx.step(f"Attempt {attempt}: send one write twice at the same moment") as step:
            results = flow.race(marker, "POST", path, [(token, body, key)] * 2, mark=mark)
            outcome["results"] = results
            outcome["ended"] = datetime.datetime.now(datetime.timezone.utc)
            step.note("statuses: " + ", ".join(str(r[0]) for r in results))
            if not services:
                step.note("this service writes no per-request log, so the replica split is not observable")
            ctx.expect(all(r[0] in success or r[0] in UNCERTAIN for r in results), "unexpected statuses " + str([r[0] for r in results]))
        replayed = None
        with ctx.step("Both responses agree with one stored result") as step:
            results = outcome["results"]
            if any(r[0] in UNCERTAIN for r in results):
                replayed = flow.replay(f"{marker}-retry", "POST", path, token, body, key, success, mark=mark)
                step.note("a racer timed out, so the write was retried with its original key")
                ctx.expect(replayed, "the retry with the original key did not return a result")
                ctx.expect(all(r[1] == replayed[1] for r in results if r[0] in success), "responses differ from the stored result")
            else:
                ctx.expect(results[0] == results[1], "the two responses differ")
                replayed = flow.call(f"{marker}-replay", "POST", path, token, body, key, mark=mark)
                ctx.expect(replayed[0] in success and replayed[1] == results[0][1], "a replay did not return the original response")
        time.sleep(1.0)
        with ctx.step("One durable record exists") as step:
            count = until(lambda: durable(tag, extra) == 1, 8, 1.0)
            ctx.expect(count, f"{durable(tag, extra)} durable records for {tag}")
        with ctx.step("One idempotency record was added") as step:
            ctx.expect(idem(extra) - before == 1, f"{idem(extra) - before} idempotency records added")
        if not services:
            return
        # Stop right after the race, so the replay in the step above does not count as a third copy.
        lines = stack.collect_logs(services, started - datetime.timedelta(seconds=2), outcome["ended"] + datetime.timedelta(seconds=0.1),
                                   match=seen)
        per = Counter(f"{line.service}#{line.replica}" for line in lines if "POST" in line.text)
        observable = sum(per.values()) == 2
        with ctx.step("Each replica received one copy of the write") as step:
            step.note("received by: " + (", ".join(f"{k}={v}" for k, v in sorted(per.items())) or "no access-log lines"))
            ctx.evidence(step, [line for line in lines if "POST" in line.text])
            if not observable:
                # Gateway can cancel a request at its deadline, and a cancelled request is never logged.
                step.note("the access logs do not show exactly two requests, so the split cannot be proved here")
            else:
                ctx.expect(sorted(per.values()) == [1, 1], "both copies reached the same replica")
        if not observable or sorted(per.values()) == [1, 1]:
            return
    ctx.expect(False, f"no attempt showed the write on both replicas in {ATTEMPTS} tries")


def _flow(ctx):
    return Flow(ctx, "race")


def player_team(ctx):
    stack = ctx.stack
    token = stack.login(0)
    sql = lambda q: stack.psql("player-db", "player", "player_db", q)["n"]
    _race(ctx, _flow(ctx), "team", "/api/v1/teams", token, lambda tag, e: {"name": tag}, ["player", "player-slot-2"],
          durable=lambda tag, e: sql(f"SELECT json_build_object('n',COUNT(*)) FROM teams WHERE name='{safe(tag)}';"),
          idem=lambda e: sql("SELECT json_build_object('n',COUNT(*)) FROM idempotency;"))


def session_create(ctx):
    stack = ctx.stack
    token = stack.login(0)
    flow = _flow(ctx)
    sql = lambda q: stack.psql("session-db", "session", "session_db", q)["n"]

    def prepare(attempt):
        status, team = flow.call(f"team-{attempt}", "POST", "/api/v1/teams", token, {"name": ctx.label(f"sess-team-{attempt}")})
        ctx.expect(status == 201, f"team create returned {status}")
        return {"team": team["team_id"]}
    _race(ctx, flow, "session", "/api/v1/sessions", token, lambda tag, e: {"team_id": e["team"]}, ["session", "session-slot-2"],
          durable=lambda tag, e: sql(f"SELECT json_build_object('n',COUNT(*)) FROM sessions WHERE team_id='{safe(e['team'])}';"),
          idem=lambda e: sql("SELECT json_build_object('n',COUNT(*)) FROM idempotency;"), prepare=prepare)


def moderation_decision(ctx):
    stack = ctx.stack
    flow = _flow(ctx)
    state = {}
    with ctx.step("Prepare a started session", fatal=True):
        state["sid"], state["tokens"] = prepare_session(ctx, flow)
    sid, tokens = state["sid"], state["tokens"]
    sql = lambda q: stack.psql("moderation-db", "moderation", "moderation", q)

    def prepare(attempt):
        with ctx.step(f"Create case {attempt} and wait for all three owners", fatal=True):
            return {"cid": create_case(ctx, flow, sid, tokens, "applicant" if attempt % 2 else "credential", f"case{attempt}")}

    def durable(tag, e):
        row = sql(f"SELECT json_build_object('d',(SELECT COUNT(*) FROM decisions WHERE session_id='{safe(sid)}' AND case_id='{safe(e['cid'])}'),"
                  f"'e',(SELECT COUNT(*) FROM outbox WHERE event_type='DecisionScored' AND correlation_id='{safe(e['cid'])}'));")
        return row["d"] if row["d"] == row["e"] else -1

    _race(ctx, flow, "decision", f"/api/v1/sessions/{sid}/decisions", tokens[0],
          lambda tag, e: {"case_id": e["cid"], "action": "reject", "reason": f"{tag} concurrent decision"},
          ["moderation", "moderation-slot-2"], durable=durable,
          idem=lambda e: sql("SELECT json_build_object('n',COUNT(*)) FROM idempotency;")["n"], prepare=prepare, mark=False)


def _mongo_race(ctx, label, path, database, collection, field, body_for):
    stack = ctx.stack
    token = _admin_token(ctx)
    count = lambda tag, e: stack.mongo(f"return db.getSiblingDB('{database}').{collection}.countDocuments({{{field}:'{safe(tag)}'}});")
    idem = lambda e: stack.mongo(f"return db.getSiblingDB('{database}').idempotency.countDocuments({{}});")
    _race(ctx, _flow(ctx), label, path, token, body_for, [], durable=count, idem=idem)


def applicant_preset(ctx):
    _mongo_race(ctx, "applicant", "/api/v1/admin/applicant-presets", "applicant", "profile_presets", "label",
                lambda tag, e: {"label": tag, "role": "outsider", "university_status": "none", "major": None, "year": None,
                                "course_count": 0, "enabled": False})


def credential_template(ctx):
    _mongo_race(ctx, "credential", "/api/v1/admin/credential-templates", "credential", "credential_templates", "issuer",
                lambda tag, e: {"kind": "student_id", "issuer": tag, "validity_days": None, "enabled": False})


ADMIN = Mutation(faults="grants admin to demo player 2 through the operator command so it can create catalog entries.",
                 restores="revokes the admin role afterwards and checks that it is gone.")

SUITE = Suite(
    id="race", title="Concurrent first writes", grade="6",
    description="The same first write sent to both replicas at once leaves one durable record and one idempotency record.",
    cases=[
        Case("team", "Player: one team from a doubled create", player_team, seconds=20),
        Case("session", "Session: one session from a doubled create", session_create, seconds=30),
        Case("decision", "Moderation: one decision from a doubled decision", moderation_decision, seconds=60),
        Case("applicant", "Applicant: one preset from a doubled create", applicant_preset, mutation=ADMIN, seconds=20),
        Case("credential", "Credential: one template from a doubled create", credential_template, mutation=ADMIN, seconds=20),
    ])
