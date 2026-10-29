"""Grade 3: every instance reports an authenticated status, and the logs stay useful."""
from __future__ import annotations

import datetime

from ..model import Case, Suite
from .common import probe_origins

NOISE_LIMIT_PER_MINUTE = 1500


def authenticated_status(ctx):
    stack = ctx.stack
    targets = probe_origins(stack)
    ctx.expect(len(targets) >= 2, "No instances found in the registry.")
    probe_ip = _probe_ip(stack)
    for service, origin in targets:
        match = rf"{probe_ip.replace('.', r'[.]')}:\d+ - \"GET /internal/v1/status" if probe_ip else None
        with ctx.step(f"{service}: status 200, wrong token 401", services=[service], match=match) as step:
            result = stack.probe_status(origin)
            step.note(f"live={result['live']} ready={result['ready']} service={result['service']}")
            ctx.expect(result["ok"] == 200, f"status returned {result['ok']}")
            ctx.expect(result["wrong"] == 401, f"a wrong token returned {result['wrong']}, expected 401")
            ctx.expect(result["live"] is True and result["ready"] is True, "instance is not live and ready")


def _probe_ip(stack):
    try:
        networks = stack.inspect("player")["NetworkSettings"]["Networks"]
        return next(iter(networks.values()))["IPAddress"]
    except Exception:  # noqa: BLE001
        return None


def log_volume(ctx):
    stack = ctx.stack
    services = sorted(s for s in stack.containers() if not s.endswith("-db") and s not in ("redis", "rabbitmq", "mongodb", "university-mongodb"))
    window = 60
    with ctx.step(f"Every service wrote logs in the last {window} s, and none flooded", services=[]) as step:
        quiet, loud, now = [], [], datetime.datetime.now(datetime.timezone.utc)
        for service in services:
            count = len(stack.fetch_logs(service, now - datetime.timedelta(seconds=window), now))
            if count == 0 and service != "moderation-publisher":
                quiet.append(service)
            if count > NOISE_LIMIT_PER_MINUTE:
                loud.append(f"{service} ({count})")
        step.note(f"checked {len(services)} services")
        ctx.expect(not quiet, "no log lines from " + ", ".join(quiet))
        ctx.expect(not loud, "more than %d lines per minute from %s" % (NOISE_LIMIT_PER_MINUTE, ", ".join(loud)))
    with ctx.step("Logs of the last 5 minutes contain no secret value") as step:
        now = datetime.datetime.now(datetime.timezone.utc)
        leaking = []
        for service in services:
            text = "\n".join(t for _, t in stack.fetch_logs(service, now - datetime.timedelta(minutes=5), now))
            if stack.redactor.holds_secret(text):
                leaking.append(service)
        ctx.expect(not leaking, "a configured secret appears in the logs of " + ", ".join(leaking))


SUITE = Suite(
    id="status", title="Status and logs", grade="3",
    description="Every instance answers its authenticated status, rejects a wrong token, and logs usefully.",
    cases=[
        Case("authenticated", "Authenticated status of every instance", authenticated_status, seconds=15),
        Case("log-volume", "Log volume and secret-free logs", log_volume, seconds=20),
    ])
