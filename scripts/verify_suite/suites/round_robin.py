"""Grade 6: Gateway alternates read requests between the two replicas of a service."""
from __future__ import annotations

from collections import Counter

from ..model import Case, Suite
from ..util import alternates, balanced
from .common import marked_gets

REQUESTS = 12


def _check(ctx, tag, label, path_for, services):
    stack = ctx.stack
    token = stack.login(0)
    path = path_for(stack.players()["session_id"])
    with ctx.step(f"{REQUESTS} GET {label} requests alternate between the two replicas",
                  services=services, match=rf"vf={ctx.run_id}-{tag}-") as step:
        statuses, served = marked_gets(ctx, token, path, REQUESTS, tag, services)
        sequence = [served.get(marker, "unseen") for marker, _ in statuses]
        step.note("order: " + " ".join(s.replace(f"{services[0].split('-slot')[0]}#", "#") for s in sequence))
        step.note("totals: " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(sequence).items())))
        ctx.expect(all(s == 200 for _, s in statuses), "statuses: " + ", ".join(str(s) for _, s in statuses))
        ctx.expect("unseen" not in sequence, f"{sequence.count('unseen')} requests are missing from the access logs")
        ctx.expect(balanced(sequence, 2), "replicas did not serve six requests each")
        ctx.expect(alternates(sequence), "a replica served two requests in a row")


def player(ctx):
    _check(ctx, "rr-player", "/players/me", lambda sid: "/api/v1/players/me", ["player", "player-slot-2"])


def session(ctx):
    _check(ctx, "rr-session", "/sessions/{id}", lambda sid: f"/api/v1/sessions/{sid}", ["session", "session-slot-2"])


def moderation(ctx):
    _check(ctx, "rr-moderation", "/sessions/{id}/decisions", lambda sid: f"/api/v1/sessions/{sid}/decisions", ["moderation", "moderation-slot-2"])


SUITE = Suite(
    id="round-robin", title="Round-robin balancing", grade="6",
    description="Twelve GET requests alternate between the two replicas, read from the access logs.",
    note="Applicant, Credential, University Record and Server Rules write no per-request log lines, so only Player, Session and Moderation can show this.",
    cases=[
        Case("player", "Player: 12 reads alternate", player, seconds=10),
        Case("session", "Session: 12 reads alternate", session, seconds=10),
        Case("moderation", "Moderation: 12 reads alternate", moderation, seconds=10),
    ])
