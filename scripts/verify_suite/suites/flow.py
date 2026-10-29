"""Shared Gateway flow for the gameplay and race suites: sessions, cases, decisions, and race helpers."""
from __future__ import annotations

import re
import threading
import time
import uuid

from ..model import Check

UNCERTAIN = {0, 502, 503, 504}  # outcome unknown: a timeout does not prove the write rolled back
KINDS = ["enrollment", "outlook_group", "course", "academic_year", "schedule", "fcim_message"]
SAFE = re.compile(r"^[A-Za-z0-9._:-]+$")


def safe(value) -> str:
    """Guard for values that go into a database query."""
    value = str(value)
    if not SAFE.match(value):
        raise ValueError("unsafe value for a query")
    return value


def until(check, timeout=30, interval=1.0):
    end = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > end:
            return None
        time.sleep(interval)


class Flow:
    """Calls the Gateway with a request marker, so the access log of each replica shows who served it."""

    def __init__(self, ctx, tag: str):
        self.ctx, self.tag, self.count = ctx, tag, 0
        self.stack = ctx.stack

    @property
    def marker_prefix(self) -> str:
        return f"{self.ctx.run_id}-{self.tag}"

    def target(self, name, path, mark=True):
        """The request path, with a `vf` marker when the route accepts one. The decisions route rejects any query string."""
        return f"{path}?vf={self.marker_prefix}-{name}" if mark else path

    def call(self, name, method, path, token, body=None, key=None, timeout=20, mark=True):
        self.count += 1
        key = key or (self.ctx.key(f"{self.tag}/{name}/{self.count}") if body is not None else None)
        return self.stack.api(method, self.target(name, path, mark), token, body, key, timeout)

    def race(self, name, method, path, jobs, timeout=20, mark=True):
        """Send len(jobs) requests at the same moment. Each job is (token, body, key). Returns [(status, body)]."""
        target = self.target(name, path, mark)
        barrier = threading.Barrier(len(jobs))
        out = [None] * len(jobs)

        def worker(i, job):
            token, body, key = job
            barrier.wait(10)
            out[i] = self.stack.api(method, target, token, body, key, timeout)
        threads = [threading.Thread(target=worker, args=(i, j)) for i, j in enumerate(jobs)]
        [t.start() for t in threads]
        [t.join(timeout + 10) for t in threads]
        return out

    def replay(self, name, method, path, token, body, key, success, timeout=30, mark=True):
        """Retry a write with its original key until a definitive success comes back."""
        holder = []

        def attempt():
            result = self.call(name, method, path, token, body, key, mark=mark)
            if result[0] in success:
                holder.append(result)
            return bool(holder)
        until(attempt, timeout, 1.0)
        return holder[0] if holder else None


def prepare_session(ctx, flow: Flow, start=True):
    """Create a session on the demo team, join both juniors, assign record permissions, and optionally start it."""
    stack, players = ctx.stack, ctx.stack.players()
    tokens = [stack.login(n) for n in range(3)]
    status, session = flow.call("create-session", "POST", "/api/v1/sessions", tokens[0], {"team_id": players["team_id"]})
    ctx.expect(status == 201, f"session create returned {status}")
    sid = str(uuid.UUID(session["session_id"]))
    for n in (1, 2):
        status, _ = flow.call(f"join-{n}", "POST", f"/api/v1/sessions/{sid}/participants", tokens[n], {})
        ctx.expect(status == 200, f"junior {n} join returned {status}")
    perms = [{"player_id": players[f"player{n}"], "session_id": sid, "record_kinds": KINDS[(n - 1) * 3:(n - 1) * 3 + 3]} for n in (1, 2)]
    status, _ = flow.call("permissions", "PUT", f"/api/v1/sessions/{sid}/record-permissions", tokens[0], {"permissions": perms})
    ctx.expect(status == 200, f"record permissions returned {status}")
    if start:
        key = ctx.key(f"{flow.tag}/start")
        status, body = flow.call("start", "POST", f"/api/v1/sessions/{sid}/start", tokens[0], {}, key)
        if status in UNCERTAIN:
            # A timeout does not prove rollback, so retry with the original key until the stored result returns.
            status, body = flow.replay("start", "POST", f"/api/v1/sessions/{sid}/start", tokens[0], {}, key, {200}) or (status, body)
        ctx.expect(status == 200, f"session start returned {status}")
    return sid, tokens


def create_case(ctx, flow: Flow, sid, tokens, entry, name):
    """Create a case and wait until all three owners hold it. Returns the case id."""
    status, case = flow.call(f"{name}-create", "POST", f"/api/v1/sessions/{sid}/cases", tokens[0], {"entry_service": entry})
    ctx.expect(status == 202, f"case create returned {status}")
    cid = str(uuid.UUID(case["case_id"]))
    ready = until(lambda: (lambda r: r[1] if r[0] == 200 and r[1].get("state") == "ready" else None)(
        flow.call(f"{name}-poll", "GET", f"/api/v1/sessions/{sid}/cases/{cid}/status", tokens[0])), 40)
    ctx.expect(ready, "the case did not become ready in 40 s")
    ctx.expect(set(ready["ready_services"]) == {"applicant", "credential", "university_record"}, f"ready services: {ready['ready_services']}")
    return cid
