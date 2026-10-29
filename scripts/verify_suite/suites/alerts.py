"""Grades 8 and 9: real Gateway load turns critical, Discovery alerts, and Discord receives the alerts."""
from __future__ import annotations

import concurrent.futures
import datetime
import http.client
import json
import re
import socket
import subprocess
import time

from ..model import Case, Mutation, Suite
from .flow import until

SAMPLER = """import datetime,json,sys,time,urllib.request
c=json.load(sys.stdin)
h={'X-Control-Name':'operator','X-Control-Token':c['token']}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=2) as r:
        assert r.status==200
        return json.load(r)
def registry():
    rows=get(c['discovery']+'/internal/v1/discovery/instances?include_unavailable=true')['instances']
    return {x['instance_id']:{k:x.get(k) for k in ['service_name','registration_id','state','boot_id','lease_expires_at','last_checked_at']} for x in rows}
before=registry();samples=[]
for _ in range(c['samples']):
    s=get(c['gateway']+'/internal/v1/status')
    assert s['instance_id']==c['gateway_id'] and s['service_name']=='gateway' and s['ready'] and s['live']
    samples.append({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'load':s['load']})
    time.sleep(c['interval'])
after=registry()
print(json.dumps({'samples':samples,'before':before,'after':after}))
"""

ALERT = re.compile(r"alert event=(\w+)")


def _gateway_row(stack):
    return next(r for r in stack.registry() if r["service_name"] == "gateway")


def _occupy(port):
    """Open one connection and send an incomplete request, which holds one Gateway task slot."""
    connection = socket.create_connection(("127.0.0.1", port), timeout=2)
    connection.settimeout(2)
    try:
        connection.sendall(b"POST /api/v1/players HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                           b"Content-Length: 2\r\nConnection: close\r\n\r\n{")
    except BaseException:
        connection.close()
        raise
    return connection


def critical_load(ctx):
    stack = ctx.stack
    env = stack.container_env("gateway")
    limit = int(env["HTTP_MAX_CONCURRENT_TASKS"])
    port = int(stack.gateway_url.rsplit(":", 1)[1])
    gateway = _gateway_row(stack)
    live_ids = {r["instance_id"] for r in stack.live_rows()}  # removed rows without a container never renew
    state = {"sockets": [], "result": None}
    started = datetime.datetime.now(datetime.timezone.utc)

    def release():
        sockets, state["sockets"] = state["sockets"], []
        for connection in sockets:
            connection.close()
        return bool(sockets) or False
    ctx.on_exit("close the held connections", release)

    with ctx.step(f"Gateway limits itself to {limit} concurrent tasks and reports its load", fatal=True) as step:
        status = stack.in_network("import json,sys,urllib.request\nc=json.load(sys.stdin)\nr=urllib.request.Request(c['url'],headers={'X-Control-Name':'operator','X-Control-Token':c['token']})\n"
                                  "print(json.dumps(json.load(urllib.request.urlopen(r,timeout=3))['load']))",
                                  {"url": gateway["http_url"].rstrip("/") + "/internal/v1/status"})
        step.note(f"load before the test: {status}")
        ctx.expect(status["max_concurrent_tasks"] == limit, "the reported limit differs from HTTP_MAX_CONCURRENT_TASKS")
        ctx.expect(not status["critical"], "the Gateway is already critical")

    samples = 48
    child = subprocess.Popen(["docker", "exec", "-i", stack.container("player"), "python", "-c", SAMPLER], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    child.stdin.write(json.dumps({"token": stack.env["OPERATOR_CONTROL_TOKEN"], "discovery": stack.discovery_url, "gateway": gateway["http_url"].rstrip("/"),
                                  "gateway_id": gateway["instance_id"], "samples": samples, "interval": 0.25}))
    child.stdin.close()
    child.stdin = None
    overload = None
    with ctx.step(f"Hold {limit} incomplete requests, then send one more", services=["gateway"], match=r"task_limit_exceeded",
                  fatal=True) as step:
        time.sleep(1.0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as pool:
            futures = [pool.submit(_occupy, port) for _ in range(limit)]
            for future in concurrent.futures.as_completed(futures):
                state["sockets"].append(future.result())
        time.sleep(0.3)
        request = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            request.request("GET", "/api/v1/players/me")
            response = request.getresponse()
            body = json.loads(response.read(4096))
            overload = {"http": response.status, "code": body.get("code")}
            retry_after = response.getheader("Retry-After")
        finally:
            request.close()
        step.note(f"the request over the limit got HTTP {overload['http']} {overload['code']}, Retry-After {retry_after}")
        ctx.expect(overload == {"http": 503, "code": "TASK_LIMIT_EXCEEDED"}, f"expected 503 TASK_LIMIT_EXCEEDED, got {overload}")
        time.sleep(4.0)
        release()
    out, err = child.communicate(timeout=40)
    with ctx.step("Gateway load reaches critical, then returns to zero", services=["discovery"],
                  match=r"alert event=(critical_load|load_recovered) service_name=gateway", window=(20.0, 2.0)) as step:
        ctx.expect(child.returncode == 0, "the status sampler failed")
        data = json.loads(out)
        samples_ = data["samples"]
        critical = [s for s in samples_ if s["load"]["critical"] and s["load"]["utilization"] >= 0.9]
        recovered = [s for s in samples_ if critical and s["at"] > critical[-1]["at"] and not s["load"]["critical"] and s["load"]["active_tasks"] == 0]
        step.note(f"peak {max(s['load']['active_tasks'] for s in samples_)} active tasks, {len(critical)} critical samples, {len(recovered)} recovered samples")
        ctx.expect(critical, "the Gateway never reported critical load")
        ctx.expect(recovered, "the load did not return to zero")
        state["result"] = data

    with ctx.step("The registry kept every generation and kept renewing leases") as step:
        data = state["result"]
        before, after = data["before"], data["after"]
        changed = []
        for key, old in before.items():
            if key not in live_ids:
                continue
            new = after.get(key)
            if not new or new["state"] != old["state"] or new["registration_id"] != old["registration_id"] or new["boot_id"] != old["boot_id"]:
                changed.append(old["service_name"])
            elif not (old["lease_expires_at"] < new["lease_expires_at"] and old["last_checked_at"] < new["last_checked_at"]):
                changed.append(old["service_name"] + " (no renewal)")
        ctx.expect(not changed, "changed during the load: " + ", ".join(changed))
        step.note(f"{len(live_ids)} instances with a running container compared")

    with ctx.step("Discovery logs critical_load, then load_recovered, for the Gateway", services=["discovery"], match=r"alert event=(critical_load|load_recovered)") as step:
        def alerts():
            lines = [t for _, t in stack.fetch_logs("discovery", started - datetime.timedelta(seconds=2))]
            return [l for l in lines if ALERT.search(l) and f"instance_id={gateway['instance_id']}" in l]
        both = until(lambda: (lambda a: a if any("event=critical_load " in l for l in a) and any("event=load_recovered " in l for l in a) else None)(alerts()), 25, 1.0)
        ctx.expect(both, "Discovery did not log both alerts in 25 s")
        order = [ALERT.search(l).group(1) for l in both]
        first_critical = order.index("critical_load")
        last_recovered = len(order) - 1 - order[::-1].index("load_recovered")
        step.note("alert order: " + " ".join(order))
        ctx.expect(first_critical < last_recovered, "load_recovered came before critical_load")
        state["alerts"] = len(both)

    with ctx.step("Discord accepted every alert from this run", services=["discovery"], match=r"discord_delivery") as step:
        def counts():
            lines = [t for _, t in stack.fetch_logs("discovery", started - datetime.timedelta(seconds=2))]
            sent = sum("alert event=" in l for l in lines)
            return sent, sum("discord_delivery_success" in l for l in lines), sum(bool(re.search(r"discord_delivery_(fail|error)", l)) for l in lines)
        done = until(lambda: counts()[1] >= counts()[0] > 0, 30, 1.5)
        sent, delivered, failed = counts()
        step.note(f"alerts logged {sent}, discord_delivery_success {delivered}, delivery failures {failed}")
        ctx.expect(failed == 0, f"{failed} Discord delivery failures")
        ctx.expect(done, f"{delivered} deliveries for {sent} alerts after 30 s")


def delivery_history(ctx):
    stack = ctx.stack
    with ctx.step("Discovery has a Discord webhook configured") as step:
        value = stack.container_env("discovery").get("DISCORD_WEBHOOK_URL", "")
        step.note("the Discovery container's DISCORD_WEBHOOK_URL (from DISCOVERY_DISCORD_WEBHOOK_URL in .env) is " + ("set" if value else "empty"))
        ctx.expect(bool(value), "no webhook is configured, so Discovery sends no alerts")
    # Old failures, such as a burst Discord rate-limited, stay in the log for the container's lifetime. They are reported,
    # and only the most recent delivery decides the result. The critical-load case checks every delivery of its own run.
    with ctx.step("Discovery logged alerts and Discord receipts, and the latest delivery succeeded", services=["discovery"], match=r"discord_delivery|alert event=") as step:
        lines = [t for _, t in stack.fetch_logs("discovery", datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30))]
        events = {}
        for line in lines:
            match = ALERT.search(line)
            if match:
                events[match.group(1)] = events.get(match.group(1), 0) + 1
        success = sum("discord_delivery_success" in l for l in lines)
        failed = sum(bool(re.search(r"discord_delivery_(fail|error)", l)) for l in lines)
        step.note("alerts by event: " + ", ".join(f"{k}={v}" for k, v in sorted(events.items())))
        deliveries = [l for l in lines if re.search(r"discord_delivery_(success|fail|error)", l)]
        latest = "none" if not deliveries else ("success" if "discord_delivery_success" in deliveries[-1] else "failure")
        step.note(f"discord_delivery_success={success}, earlier delivery failures={failed}, latest delivery={latest}")
        ctx.expect(events.get("critical_load") and events.get("load_recovered"), "no critical_load and load_recovered alerts in the log. Run the critical-load case first.")
        ctx.expect(success >= 1, "no discord_delivery_success lines")
        ctx.expect(latest == "success", "the latest Discord delivery failed, so Discord is not accepting alerts now")


SUITE = Suite(
    id="alerts", title="Critical load and Discord alerts", grade="8 and 9",
    description="Real load makes the Gateway critical and refuse the next request with 503, and Discovery alerts Discord twice.",
    cases=[
        Case("critical-load", "Critical load, 503 TASK_LIMIT_EXCEEDED, and Discord alerts", critical_load, seconds=60,
             mutation=Mutation(faults="holds as many incomplete requests as the Gateway task limit allows, with no business write.",
                               restores="closes the connections and waits for the load to return to zero.")),
        Case("delivery", "Discord receipts in the Discovery log", delivery_history, seconds=5),
    ])
