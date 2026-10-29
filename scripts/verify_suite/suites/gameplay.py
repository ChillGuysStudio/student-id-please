"""Grade 6: the guided Newman flow, a whole shift across replicas, and direct chat between two Discord DMs replicas."""
from __future__ import annotations

import datetime
import json
import subprocess
import time
import urllib.parse
import uuid
from collections import Counter

from ..model import Case, Suite
from .flow import UNCERTAIN, Flow, create_case, prepare_session, safe, until

REPLICA_PAIRS = ["player", "player-slot-2", "session", "session-slot-2"]


def guided(ctx):
    """Run the guided Newman requests 01 to 27 and check that both replicas of Player and Session took part."""
    stack = ctx.stack
    script = stack.root / "scripts" / "run_newman.sh"
    started = datetime.datetime.now(datetime.timezone.utc)
    with ctx.step("Run the guided Newman requests 01 to 27", services=REPLICA_PAIRS, match=r'"(POST|PUT) /api/v1/',
                  window=(0.0, 1.0), fatal=True) as step:
        ctx.expect(script.exists(), f"{script} does not exist")
        done = subprocess.run([str(script), "--gateway-url", stack.gateway_url], cwd=stack.root, capture_output=True, text=True, timeout=420)
        summary_path = stack.root / ".local" / "postman" / "newman-htmlextra.summary.json"
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        phase = (summary.get("phases") or [{}])[0]
        step.note(f"{phase.get('requests')} requests, {phase.get('assertions')} assertions, {phase.get('failures')} failures")
        ctx.expect(done.returncode == 0, f"run_newman.sh exited with {done.returncode}")
        ctx.expect(summary.get("failed") is False and phase.get("failures") == 0, "Newman reported failed assertions")
        ctx.expect(phase.get("requests") == 27, f"expected 27 requests, ran {phase.get('requests')}")
    stack.players(refresh=True)
    with ctx.step("The flow created three new demo players and a lobby") as step:
        players = stack.players()
        ctx.expect(all(players.get(k) for k in ("player0", "player1", "player2", "team_id", "session_id")), "the demo environment is incomplete")
        step.note("demo environment: " + str(len(stack.player_env_files())) + " saved runs, newest in use")
    with ctx.step("Both replicas of Player and of Session served part of the flow") as step:
        lines = stack.collect_logs(REPLICA_PAIRS, started - datetime.timedelta(seconds=2), datetime.datetime.now(datetime.timezone.utc),
                                   match=r'"(GET|POST|PUT|PATCH|DELETE) /api/v1/')
        counts = Counter(f"{l.service}#{l.replica}" for l in lines)
        step.note(", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        for expected in ("player#1", "player#2", "session#1", "session#2"):
            ctx.expect(counts[expected] > 0, f"{expected} served no request")


def shift(ctx):
    """One complete shift: lobby, start, two cases decided on Moderation, end, and one progression award."""
    stack = ctx.stack
    flow = Flow(ctx, "shift")
    watched = ["session", "session-slot-2", "moderation", "moderation-slot-2", "player", "player-slot-2"]
    started = datetime.datetime.now(datetime.timezone.utc)
    state = {}
    with ctx.step("Create a session, add both juniors, assign record permissions, and start", services=["session", "session-slot-2"],
                  match=rf"vf={ctx.run_id}-shift-", fatal=True) as step:
        state["sid"], state["tokens"] = prepare_session(ctx, flow)
        step.note("session " + state["sid"][:8])
    sid, tokens = state["sid"], state["tokens"]
    xp_before = [stack.api("GET", "/api/v1/players/me", tokens[n])[1].get("xp") for n in range(3)]
    scored = delta_score = delta_penalty = 0
    for index, entry in enumerate(("applicant", "credential"), 1):
        with ctx.step(f"Case {index}: create it through {entry} and wait until Applicant, Credential and University Record hold it",
                      services=["session", "session-slot-2"], match=rf"vf={ctx.run_id}-shift-case{index}-", fatal=True):
            cid = create_case(ctx, flow, sid, tokens, entry, f"case{index}")
        with ctx.step(f"Case {index}: the presented applicant can be read", services=["session", "session-slot-2"],
                      match=rf"vf={ctx.run_id}-shift-case{index}-read") as step:
            status, _ = flow.call(f"case{index}-read", "GET", f"/api/v1/sessions/{sid}/applicants/{cid}", tokens[0])
            ctx.expect(status == 200, f"applicant read returned {status}")
        with ctx.step(f"Case {index}: Moderation commits one decision and Session applies the score",
                      services=["moderation", "moderation-slot-2"], match=rf"POST /api/v1/sessions/{sid}/decisions HTTP", fatal=True) as step:
            body = {"case_id": cid, "action": "reject", "reason": f"{ctx.run_id} shift case {index}"}
            key = ctx.key(f"shift/decision/{index}")
            status, decision = flow.call(f"case{index}-decide", "POST", f"/api/v1/sessions/{sid}/decisions", tokens[0], body, key, mark=False)
            if status in UNCERTAIN:
                status, decision = flow.replay(f"case{index}-decide", "POST", f"/api/v1/sessions/{sid}/decisions", tokens[0], body, key, {201}, mark=False) or (status, decision)
            ctx.expect(status == 201, f"decision returned {status} {decision.get('code') if isinstance(decision, dict) else ''}")
            delta_score += decision["score_delta"]
            delta_penalty += decision["penalty"]
            scored += 1
            applied = until(lambda: (lambda r: r[0] == 200 and r[1].get("processed_count") == scored and not r[1].get("current_case_id"))(
                flow.call(f"case{index}-wait", "GET", f"/api/v1/sessions/{sid}", tokens[0])), 40)
            ctx.expect(applied, "Session did not apply the score in 40 s")
            replay = flow.call(f"case{index}-replay", "POST", f"/api/v1/sessions/{sid}/decisions", tokens[0], body, key, mark=False)
            ctx.expect(replay[1] == decision, "replaying the decision did not return the stored result")
    with ctx.step("End the shift", services=["session", "session-slot-2"], match=rf"vf={ctx.run_id}-shift-end", fatal=True) as step:
        status, ended = flow.call("end", "POST", f"/api/v1/sessions/{sid}/end", tokens[0], {})
        if status in UNCERTAIN or status == 409:
            time.sleep(2)
            status, ended = flow.replay("end", "POST", f"/api/v1/sessions/{sid}/end", tokens[0], {}, ctx.key("shift/end"), {200}) or (status, ended)
        ctx.expect(status == 200 and ended.get("status") == "ended", f"end returned {status}")
        ctx.expect(ended.get("processed_count") == scored, f"processed {ended.get('processed_count')} of {scored} cases")
        ctx.expect(ended.get("score") == delta_score and ended.get("penalties") == delta_penalty, "the final score is not the sum of the decisions")
        state["award"] = max(0, ended["score"])
    with ctx.step("Each player receives the shift award once", services=["player", "player-slot-2"], match=r"/api/v1/players/me") as step:
        award = state["award"]
        def deltas():
            now = [stack.api("GET", "/api/v1/players/me", tokens[n])[1].get("xp") for n in range(3)]
            return [a - b if a is not None and b is not None else None for a, b in zip(now, xp_before)]
        ok = until(lambda: deltas() == [award] * 3, 40)
        time.sleep(3)
        step.note(f"award {award} XP each, observed {deltas()}")
        ctx.expect(ok and deltas() == [award] * 3, f"XP changes {deltas()}, expected {award} for each player")
    with ctx.step("Player stores exactly three ledger rows and one event receipt, and they stay put") as step:
        sql = lambda: stack.psql("player-db", "player", "player_db",
                                 f"SELECT json_build_object('ledger',(SELECT COUNT(*) FROM progression_ledger WHERE kind='shift' AND source_id='{safe(sid)}'),"
                                 f"'receipts',(SELECT COUNT(*) FROM event_receipts WHERE business_key='shift:{safe(sid)}'));")
        settled = until(lambda: sql() == {"ledger": 3, "receipts": 1}, 40)
        time.sleep(3)
        step.note(f"after settling: {sql()}")
        ctx.expect(settled and sql() == {"ledger": 3, "receipts": 1}, f"ledger state {sql()}, expected 3 rows and 1 receipt")
    with ctx.step("Both Session replicas and both Moderation replicas handled part of the shift") as step:
        lines = stack.collect_logs(watched[:4], started - datetime.timedelta(seconds=2), datetime.datetime.now(datetime.timezone.utc),
                                   match=rf"vf={ctx.run_id}-shift-|/api/v1/sessions/{sid}/decisions")
        counts = Counter(f"{l.service}#{l.replica}" for l in lines)
        step.note(", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        for expected in ("session#1", "session#2", "moderation#1", "moderation#2"):
            ctx.expect(counts[expected] > 0, f"{expected} served no request of this shift")


def chat(ctx):
    """Two DMs on different replicas exchange one message through their direct WebSockets."""
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    stack = ctx.stack
    flow = Flow(ctx, "chat")
    state = {}
    with ctx.step("Create and start a session for the chat", fatal=True):
        state["sid"], state["tokens"] = prepare_session(ctx, flow)
    sid, tokens = state["sid"], state["tokens"]
    with ctx.step("Both DMs open the same mod-chat channel") as step:
        channels = []
        for n in (0, 1):
            status, body = flow.call(f"channels-{n}", "GET", f"/api/v1/sessions/{sid}/channels", tokens[n])
            ctx.expect(status == 200, f"channel list returned {status}")
            channels.append(next(c for c in body["channels"] if c["name"] == "#general-mod-chat")["channel_id"])
        ctx.expect(channels[0] == channels[1], "the two DMs see different channels")
        state["channel"] = channels[0]
    with ctx.step("Negotiation sends the two DMs to different replicas", fatal=True) as step:
        urls = []
        for n in (0, 1):
            for attempt in range(6):
                status, body = flow.call(f"negotiate-{n}-{attempt}", "POST", f"/api/v1/sessions/{sid}/realtime-negotiation", tokens[n], {}, mark=False)
                ctx.expect(status == 200, f"negotiation returned {status}")
                if n == 0 or urllib.parse.urlsplit(body["url"]).port != urllib.parse.urlsplit(urls[0]).port:
                    urls.append(body["url"])
                    break
        step.note("replica ports: " + ", ".join(str(urllib.parse.urlsplit(u).port) for u in urls))
        ctx.expect(len(urls) == 2, "negotiation kept returning the same replica")
        state["urls"] = urls
    client_id = str(uuid.uuid4())
    frame = {"type": "message.send", "client_message_id": client_id, "channel_id": state["channel"], "text": f"{ctx.run_id} chat check"}

    def wait(ws, kind):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            data = json.loads(ws.recv(timeout=12))
            ctx.expect(data.get("type") != "error", "the server sent an error frame")
            if data.get("type") == kind and data.get("message", data).get("client_message_id") == client_id:
                return data
        raise TimeoutError(kind)
    with ctx.step("A message sent to replica 1 reaches the client on replica 2", services=["discord-dms", "discord-dms-slot-2"],
                  match=r"message|ticket|websocket|connect") as step:
        with connect(state["urls"][0], open_timeout=10, proxy=None) as first, connect(state["urls"][1], open_timeout=10, proxy=None) as second:
            first.send(json.dumps(frame))
            ack = wait(first, "message.ack")
            event = wait(second, "message.created")
            ctx.expect(ack["message_id"] == event["message"]["message_id"], "the ack and the delivered message differ")
            ctx.expect(event["message"]["author_id"] == stack.players()["player0"], "the author is wrong")
            first.send(json.dumps(frame))
            again = wait(first, "message.ack")
            ctx.expect(again == ack, "a duplicate frame got a different ack")
            step.note("a duplicate client_message_id returned the same ack")
            try:
                with connect(state["urls"][0], open_timeout=5, proxy=None):
                    ctx.expect(False, "a consumed ticket was accepted")
            except InvalidStatus as error:
                step.note(f"a consumed ticket is refused with HTTP {error.response.status_code}")
                ctx.expect(error.response.status_code == 401, f"consumed ticket returned {error.response.status_code}")
    with ctx.step("The message is stored once and history shows it") as step:
        status, history = flow.call("history", "GET", f"/api/v1/channels/{state['channel']}/messages", tokens[1])
        ctx.expect(status == 200, f"history returned {status}")
        ctx.expect(len([m for m in history.get("items", []) if m.get("client_message_id") == client_id]) == 1, "the message is not stored exactly once")
    with ctx.step("Negotiation without a token is refused") as step:
        status, _ = flow.call("negotiate-anon", "POST", f"/api/v1/sessions/{sid}/realtime-negotiation", None, {}, mark=False)
        ctx.expect(status in (401, 403), f"anonymous negotiation returned {status}")


SUITE = Suite(
    id="gameplay", title="Gameplay across replicas", grade="6",
    description="The guided Newman flow, a whole shift served by both replicas, and direct chat between two DMs replicas.",
    cases=[
        Case("guided", "Guided Newman flow, requests 01 to 27", guided, seconds=60),
        Case("shift", "A shift with two decided cases", shift, seconds=90),
        Case("chat", "Direct chat between two DMs replicas", chat, seconds=30),
    ])
