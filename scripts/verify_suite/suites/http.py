"""Grade 3: read-only public Gateway checks through the documented Newman runner."""
from __future__ import annotations

import json
import subprocess

from ..model import Case, Suite


def public_smoke(ctx):
    stack = ctx.stack
    script = stack.root / "scripts" / "run_newman.sh"
    with ctx.step("Run scripts/run_newman.sh --http against the public Gateway", services=["gateway"], match=r"healthz|denied|rejected", fatal=True) as step:
        ctx.expect(script.exists(), f"{script} does not exist")
        done = subprocess.run([str(script), "--http", "--gateway-url", stack.gateway_url], cwd=stack.root, capture_output=True, text=True, timeout=240)
        summary_path = stack.root / ".local" / "postman" / "http-checks" / "newman-htmlextra.summary.json"
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        phase = (summary.get("phases") or [{}])[0]
        step.note(f"{phase.get('requests')} requests, {phase.get('assertions')} assertions, {phase.get('failures')} failures")
        ctx.expect(done.returncode == 0, f"run_newman.sh --http exited with {done.returncode}")
        ctx.expect(summary.get("failed") is False and phase.get("failures") == 0, "Newman reported failed assertions")
        ctx.expect(phase.get("requests", 0) >= 4, "fewer than four requests ran")
    with ctx.step("Public ingress hides the private listener") as step:
        for path in ("/internal/v1/status", "/internal/v1/discovery/instances"):
            status, _ = stack.api("GET", path)
            step.note(f"GET {path} returned {status}")
            ctx.expect(status in (401, 403, 404), f"{path} returned {status}")


SUITE = Suite(
    id="http", title="Public HTTP checks", grade="3",
    description="Four anonymous requests through Newman: Gateway liveness, hidden private routes, and a protected Player read.",
    cases=[Case("public", "Public Gateway smoke through Newman", public_smoke, seconds=15)])
