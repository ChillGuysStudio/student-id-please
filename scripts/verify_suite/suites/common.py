"""Helpers that several suites share."""
from __future__ import annotations

import re

from ..util import host_to_service


def row_service(row: dict) -> str:
    """Compose service name for a registry row."""
    return host_to_service(re.search(r"//([^:/]+)", row["http_url"]).group(1))


def row_label(row: dict) -> str:
    return row_service(row)


def probe_origins(stack) -> list:
    """(compose service, origin) for every instance that answers /internal/v1/status, Discovery included."""
    seen = {row_service(r): r["http_url"] for r in stack.live_rows()}
    seen.setdefault("discovery", stack.discovery_url)
    return sorted(seen.items())


def session_for_reads(ctx) -> str:
    """Session id of the latest demo run, for read-only requests."""
    return ctx.stack.players()["session_id"]


def marked_gets(ctx, token: str, path: str, count: int, tag: str, services, pause: float = 0.15):
    """Send `count` GETs that carry a unique `vf` query marker, then read which replica logged each one.

    Returns (statuses, served) where served maps the marker to a label such as "session#2". Services whose
    access log shows no request line (the Java ones) cannot appear in `served`."""
    import datetime
    import time
    from ..util import served_by
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=2)
    statuses = []
    for i in range(count):
        marker = f"{ctx.run_id}-{tag}-{i}"
        status, _ = ctx.stack.api("GET", f"{path}?vf={marker}", token)
        statuses.append((marker, status))
        time.sleep(pause)
    time.sleep(0.5)
    lines = ctx.stack.collect_logs(services, since, datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1),
                                   match=rf"vf={ctx.run_id}-{tag}-")
    return statuses, served_by(lines, ctx.run_id)
