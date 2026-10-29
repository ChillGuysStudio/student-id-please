"""Grade 4: every instance registers with Discovery, stays ready, renews its lease, and runs the expected image."""
from __future__ import annotations

import time

from ..model import Case, Suite
from ..stack import BACKING
from .common import row_service


def _expected(stack) -> dict:
    """Compose service to INSTANCE_ID for every service that registers with Discovery."""
    return {s: stack.container_env(s)["INSTANCE_ID"] for s in stack.expected_services()}


def registered_and_ready(ctx):
    stack = ctx.stack
    expected = _expected(stack)
    with ctx.step("Registry lists every instance the containers advertise, once each", services=["discovery"],
                  match=r"registration|health_transition") as step:
        rows = stack.registry()
        by_id = {}
        for row in rows:
            by_id.setdefault(row["instance_id"], []).append(row)
        missing = [s for s, i in expected.items() if i not in by_id]
        doubled = [s for s, i in expected.items() if len(by_id.get(i, [])) > 1]
        step.note(f"{len(expected)} containers register; {len(rows)} registry rows (removed rows without a container are tombstones)")
        ctx.expect(not missing, "not registered: " + ", ".join(missing))
        ctx.expect(not doubled, "registered twice: " + ", ".join(doubled))
    with ctx.step("Every registered instance is ready and healthy") as step:
        by_id = {r["instance_id"]: r for r in stack.registry()}
        bad = []
        for service, instance in sorted(expected.items()):
            row = by_id.get(instance)
            status = (row or {}).get("status") or {}
            if not row or row["state"] != "ready" or not status.get("ready") or not status.get("live"):
                bad.append(f"{service}:{(row or {}).get('state', 'missing')}")
        step.note(f"{len(expected)} of {len(expected)} expected instances are ready")
        ctx.expect(not bad, "not ready: " + ", ".join(bad))
    with ctx.step("Each service name has two replicas with distinct instance IDs") as step:
        by_name = {}
        for service, instance in expected.items():
            by_name.setdefault(service.split("-slot-")[0], set()).add(instance)
        thin = [n for n, ids in by_name.items() if n not in ("gateway", "discovery") and len(ids) < 2]
        step.note(", ".join(f"{n}={len(ids)}" for n, ids in sorted(by_name.items())))
        ctx.expect(not thin, "fewer than two replicas: " + ", ".join(thin))


def leases_renew(ctx):
    stack = ctx.stack
    expected = _expected(stack)
    wait = 8.0
    first = {r["instance_id"]: r for r in stack.registry()}
    with ctx.step(f"Leases and health checks advance within {wait:.0f} s", services=["gateway"], match="discovery_registration") as step:
        time.sleep(wait)
        second = {r["instance_id"]: r for r in stack.registry()}
        stale = []
        for service, instance in sorted(expected.items()):
            a, b = first.get(instance), second.get(instance)
            if not a or not b:
                stale.append(f"{service}:missing")
            elif b["registration_id"] != a["registration_id"]:
                stale.append(f"{service}:new-registration")
            elif not (b["lease_expires_at"] > a["lease_expires_at"] and b["last_checked_at"] > a["last_checked_at"]):
                stale.append(service)
        ctx.expect(not stale, "lease or probe did not advance: " + ", ".join(stale))


def images_match(ctx):
    stack = ctx.stack
    with ctx.step("Running images match `docker compose config --images`") as step:
        wanted = set(stack.images())
        running = {}
        for service, name in sorted(stack.containers().items()):
            info = stack.inspect(service)
            image = info["Config"]["Image"]
            if not BACKING.search(image):
                running[service] = image
        step.note(f"{len(wanted)} application images configured, {len(running)} application containers running")
        stray = sorted(s for s, i in running.items() if i not in wanted)
        idle = sorted(i for i in wanted if i not in running.values())
        ctx.expect(not stray, "running an image Compose does not configure: " + ", ".join(stray))
        ctx.expect(not idle, "configured image not running: " + ", ".join(idle))
    with ctx.step("Every application container runs the image currently stored locally") as step:
        old = []
        for service in sorted(stack.containers()):
            info = stack.inspect(service)
            if BACKING.search(info["Config"]["Image"]):
                continue
            current = stack.docker("image", "inspect", "--format", "{{.Id}}", info["Config"]["Image"]).stdout.strip()
            if current and current != info["Image"]:
                old.append(service)
        ctx.expect(not old, "container predates a local image update: " + ", ".join(old))


SUITE = Suite(
    id="registry", title="Discovery registry", grade="4",
    description="All instances are registered and ready, leases renew, and the images match the Compose configuration.",
    cases=[
        Case("registered", "Instances registered and ready", registered_and_ready, seconds=5),
        Case("leases", "Leases keep renewing", leases_renew, seconds=15),
        Case("images", "Running images match Compose", images_match, seconds=10),
    ])
