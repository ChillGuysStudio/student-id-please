"""Grade 5: raise Session to three replicas, see it register and serve, then return to two and see it leave routing."""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
import time
from collections import Counter

from ..model import Case, Mutation, Suite
from ..util import set_env_value
from .common import marked_gets, row_service

SERVICE = "session"
THIRD = "session-slot-3"


def _apply(ctx, env_text: str, remove_orphans: bool):
    """Write .env, regenerate compose.replicas.yaml, and start or remove containers without recreating the others."""
    stack = ctx.stack
    (stack.root / ".env").write_text(env_text)
    done = subprocess.run([sys.executable, "-B", "scripts/replicas.py"], cwd=stack.root, capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise RuntimeError("replicas.py failed: " + done.stderr.strip()[-200:])
    args = ["up", "-d", "--wait", "--no-recreate", "--pull", "never"] + (["--remove-orphans"] if remove_orphans else [])
    up = stack.compose(*args, timeout=420)
    if up.returncode:
        raise RuntimeError("docker compose up failed: " + stack.redactor.scrub(up.stderr.strip()[-300:]))
    stack.containers(refresh=True)


def _wait(function, timeout, interval=2.0):
    end = time.monotonic() + timeout
    while True:
        value = function()
        if value:
            return value
        if time.monotonic() > end:
            return None
        time.sleep(interval)


def scale_up_down(ctx):
    stack = ctx.stack
    original = (stack.root / ".env").read_text()
    since = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    token = stack.login(0)
    sid = stack.players()["session_id"]
    path = f"/api/v1/sessions/{sid}"

    def restore():
        _apply(ctx, original, remove_orphans=True)
        stack.recover(since)
    ctx.on_exit("return Session to its configured replica count", restore)

    with ctx.step("Session starts with two ready replicas", fatal=True) as step:
        ready = [r for r in stack.live_rows() if r["service_name"] == "session" and r["state"] == "ready"]
        step.note("replicas: " + ", ".join(sorted(row_service(r) for r in ready)))
        ctx.expect(len(ready) == 2, f"expected 2 ready Session replicas, found {len(ready)}")

    with ctx.step("Set SESSION_REPLICAS=3 and start the new replica", services=[THIRD], match="failure_kind=registered", fatal=True) as step:
        _apply(ctx, set_env_value(original, "SESSION_REPLICAS", "3"), remove_orphans=False)
        ctx.expect(THIRD in stack.containers(), "the third Session container did not start")

    with ctx.step("The third replica registers and becomes ready", services=[THIRD, "discovery"],
                  match="failure_kind=registered|health_transition|reactivat", fatal=True) as step:
        def third_row():
            return next((r for r in stack.live_rows() if row_service(r) == THIRD), None)
        row = _wait(third_row, 60)
        ctx.expect(row, "session-slot-3 did not register in 60 s")
        if row["state"] == "removed":
            # Discovery keeps the removal of an earlier session-slot-3, so a new boot with the same ID waits for the operator.
            result = stack.reactivate(row)
            step.note(f"earlier removal record found, operator reactivation ok={result['ok']}")
            ctx.expect(result["ok"], "reactivation failed: " + str(result.get("last")))
        row = _wait(lambda: next((r for r in stack.live_rows() if row_service(r) == THIRD and r["state"] == "ready"), None), 60)
        ctx.expect(row, "session-slot-3 did not reach ready")
        step.note(f"instance {row['instance_id'][:8]}; Session now has "
                  f"{len({r['instance_id'] for r in stack.live_rows() if r['service_name'] == 'session'})} distinct instance IDs")

    with ctx.step("Gateway round-robin reaches all three replicas", services=["session", "session-slot-2", THIRD],
                  match=rf"vf={ctx.run_id}-up") as step:
        counts = Counter()
        for attempt in range(6):
            statuses, served = marked_gets(ctx, token, path, 9, f"up{attempt}", ["session", "session-slot-2", THIRD])
            counts = Counter(served.values())
            if len(counts) == 3 and all(s == 200 for _, s in statuses):
                break
        step.note("served by: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        ctx.expect(len(counts) == 3, "requests reached only: " + ", ".join(sorted(counts)))

    with ctx.step("Remove SESSION_REPLICAS and let the third replica go", services=[THIRD], fatal=True):
        _apply(ctx, original, remove_orphans=True)
        ctx.expect(THIRD not in stack.containers(), "the third Session container is still running")

    with ctx.step("The removed replica no longer routes", services=["session", "session-slot-2"],
                  match=rf"vf={ctx.run_id}-down") as step:
        def settled():
            statuses, served = marked_gets(ctx, token, path, 6, f"down{int(time.monotonic())}", ["session", "session-slot-2"], pause=0.1)
            return (statuses, served) if all(s == 200 for _, s in statuses) else None
        got = _wait(settled, 60, 1.0)
        ctx.expect(got, "requests kept failing after the replica stopped")
        statuses, served = got
        step.note("served by: " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(served.values()).items())))
        third = [r for r in stack.registry() if row_service(r) == THIRD and r["state"] == "ready"]
        ctx.expect(not third, "Discovery still lists session-slot-3 as ready")
        ctx.expect(set(served.values()) <= {"session#1", "session#2"}, "a request reached an unexpected replica")

    with ctx.step("Both original replicas are ready again and all instances are ready") as step:
        stack.recover(since)
        ready = [r for r in stack.live_rows() if r["service_name"] == "session" and r["state"] == "ready"]
        ctx.expect(len(ready) == 2, f"{len(ready)} ready Session replicas")
        ready_count, total = stack.ready_count()
        ctx.expect(ready_count == total, f"{ready_count} of {total} instances ready")


SUITE = Suite(
    id="scaling", title="Scaling", grade="5",
    description="Raise Session to three replicas, see it register and serve, return to two, and see it leave routing.",
    cases=[Case("up-down", "Session 2 to 3 to 2 replicas", scale_up_down, seconds=150,
                mutation=Mutation(
                    faults="sets SESSION_REPLICAS=3 in .env and starts a third Session replica.",
                    restores="writes the original .env back, removes the extra container, and reactivates any instance Discovery removed."))])
