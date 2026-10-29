"""Grades 7 and 10: a caller whose hop to the Gateway fails three times in a window opens its breaker.

The fault is an iptables REJECT rule in one caller container's network namespace. It blocks that container's
connections to the Gateway's internal port and nothing else. The Gateway itself is untouched. The rule goes in
through a throwaway container that uses a pinned image, and it comes out in every case, including Ctrl-C."""
from __future__ import annotations

import datetime
import re
import subprocess
import time
from dataclasses import dataclass

from ..model import Case, Mutation, Suite
from ..stack import PINNED_TOOL
from ..window import ClockTrack, expected_trip, trip_matches
from .common import row_service
from .flow import Flow, create_case, prepare_session, until

FAIL = re.compile(r"\b(dependency_failure|gateway_hop_failure|gateway_attempt_failed) ")
MAX_REQUESTS = 24


@dataclass
class Caller:
    id: str
    title: str
    service: str  # Compose service of replica 1
    read: str | None = None  # GET route whose handler calls the Gateway
    write: str | None = None  # "applicant" or "decision" when only a write reaches the Gateway
    needs_case: bool = False
    dms: bool = False
    both_first: bool = False  # block both replicas from the start, so a healthy one cannot consume the single test write


CALLERS = [
    Caller("session", "Session", "session", read="/api/v1/sessions/{sid}/cases/{cid}/status", needs_case=True),
    Caller("university-record", "University Record", "university-record", read="/api/v1/sessions/{sid}/record-permissions/me"),
    Caller("discord-dms", "Discord DMs", "discord-dms", read="/api/v1/sessions/{sid}/channels", dms=True),
    Caller("applicant", "Applicant", "applicant", write="applicant", both_first=True),
    Caller("moderation", "Moderation", "moderation", write="decision", needs_case=True, both_first=True),
    Caller("rules", "Server Rules", "server-rules", write="decision", needs_case=True, both_first=True),
]


def _utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(moment: datetime.datetime, back: float = 0.0) -> str:
    """UTC text that compares with Discovery's `removed_at`. `back` allows for the stepping wall clock."""
    return (moment - datetime.timedelta(seconds=back)).strftime("%Y-%m-%dT%H:%M:%S")


class Fault:
    """The REJECT rule for traffic from one container to the Gateway's internal port."""

    def __init__(self, stack, gateway_ip: str):
        self.stack, self.ip = stack, gateway_ip

    def _iptables(self, container: str, *rule: str):
        return self.stack.docker("run", "--rm", "--net", f"container:{container}", "--cap-add", "NET_ADMIN", PINNED_TOOL, "iptables",
                                 *rule, timeout=90)

    def _spec(self):
        return ["OUTPUT", "-p", "tcp", "-d", self.ip, "--dport", "8083", "-j", "REJECT", "--reject-with", "tcp-reset"]

    def present(self, container: str) -> bool:
        return self._iptables(container, "-C", *self._spec()).returncode == 0

    def install(self, container: str):
        spec = self._spec()
        self._iptables(container, "-I", spec[0], "1", *spec[1:])
        if not self.present(container):
            raise RuntimeError(f"the fault rule is not active in {container}")

    def remove(self, container: str) -> bool:
        for _ in range(5):
            if not self.present(container):
                return True
            self._iptables(container, "-D", *self._spec())
        return not self.present(container)


def run_caller(ctx, caller: Caller):
    stack = ctx.stack
    services = [caller.service, caller.service + "-slot-2"]
    containers = [stack.container(s) for s in services]
    flow = Flow(ctx, f"brk-{caller.id}")
    clock = ClockTrack()
    ctx.on_exit("stop clock sampling", lambda: clock.stop.set() or False)
    state = {"armed": [], "restored": False, "sid": None, "cid": None, "path": None}
    started = _utc()
    since = _iso(started, 3.0)
    gateway_service = "gateway"
    gateway = stack.inspect(gateway_service)
    gateway_ip = next(iter(gateway["NetworkSettings"]["Networks"].values()))["IPAddress"]
    gateway_id = stack.container_env(gateway_service)["INSTANCE_ID"]
    instance = {s: stack.container_env(s)["INSTANCE_ID"] for s in services}
    task_timeout = float(stack.container_env(services[0])["OUTBOUND_TASK_TIMEOUT_SECONDS"])
    window = 3.5 * task_timeout
    fault = Fault(stack, gateway_ip)

    def lines(service, since_dt):
        return [text for _, text in stack.fetch_logs(service, since_dt)]

    def restore():
        """Remove the rules, wait for any removal still in flight, reactivate everything removed since the start, check traffic."""
        if state["restored"]:
            return False
        problems = [c for c in containers if not fault.remove(c)]
        state["armed"].clear()
        if problems:
            raise RuntimeError("the fault rule is still active in " + ", ".join(problems))
        if any("circuit_open" in l for s in services for l in lines(s, started - datetime.timedelta(seconds=2))):
            until(lambda: stack.removed_since(since), 90, 2.0)
        stack.recover(since, quiet=18.0)
        if state["sid"]:
            statuses = [stack.api("GET", state["path"], stack.login(0))[0] for _ in range(4)]
            if set(statuses) != {200}:
                raise RuntimeError(f"traffic did not recover, statuses {statuses}")
        state["restored"] = True
    ctx.on_exit(f"unblock {caller.title} and reactivate removed instances", restore)

    with ctx.step(f"Restart both {caller.title} replicas for a fresh clock, then return the registry to all ready", fatal=True) as step:
        boot = _iso(_utc(), 3.0)
        for container in containers:
            done = stack.docker("restart", container, timeout=120)
            ctx.expect(done.returncode == 0, f"restart of {container} failed")
        stack.containers(refresh=True)
        reactivated = stack.recover(boot, quiet=20.0, min_elapsed=30.0)
        step.note("reactivated after restart: " + (", ".join(reactivated) or "none"))
    started = _utc()
    since = _iso(started, 3.0)

    with ctx.step("Create labelled test data: a started session" + (" and a ready case" if caller.needs_case else ""), fatal=True) as step:
        sid, tokens = prepare_session(ctx, flow)
        state["sid"] = sid
        if caller.needs_case:
            state["cid"] = create_case(ctx, flow, sid, tokens, "credential", "case")
        state["path"] = (caller.read or "/api/v1/sessions/{sid}").format(sid=sid, cid=state["cid"])
        step.note(f"session {sid[:8]}")
    token = stack.login(0)
    sid, cid = state["sid"], state["cid"]

    def trigger(n):
        if caller.read:
            return stack.api("GET", state["path"], token)[0]
        if caller.write == "applicant":
            return flow.call("applicant-case", "POST", f"/api/v1/sessions/{sid}/cases", token, {"entry_service": "applicant"},
                             key=ctx.key(f"brk/{caller.id}/applicant-case"))[0]
        body = {"case_id": cid, "action": "reject", "reason": f"{ctx.run_id} {caller.id} breaker trigger {n}"}
        return flow.call("decision", "POST", f"/api/v1/sessions/{sid}/decisions", token, body, mark=False)[0]

    def gateway_failures(service):
        return [l for l in lines(gateway_service, started - datetime.timedelta(seconds=2))
                if re.search(r"\bdependency_failure ", l) and "destination_instance_id=" + instance[service] in l]

    def hop_failed(service):
        if caller.dms:
            return gateway_failures(service)
        return [l for l in lines(service, started - datetime.timedelta(seconds=2)) if FAIL.search(l)]

    def tripped():
        probe = "gateway_breaker circuit_open" if caller.dms else None
        return any((probe in l) if probe else ("circuit_open" in l and "destination_instance_id=" + gateway_id in l)
                   for s in services for l in lines(s, started - datetime.timedelta(seconds=2)))

    statuses, victim = [], services[0]
    other = services[1]
    begin = time.monotonic()
    watch = r"dependency_failure|gateway_hop_failure|gateway_attempt_failed|circuit_open|removal_outcome"
    title = (f"Block {caller.title} to Gateway on both replicas" if caller.both_first
             else f"Block {caller.title} to Gateway on one replica and send requests until a hop fails")
    with ctx.step(title, services=services + ["gateway"], match=watch, fatal=True) as step:
        candidates = services[:1] if caller.both_first else services
        for candidate in candidates:
            victim, other = candidate, [s for s in services if s != candidate][0]
            fault.install(stack.container(victim))
            state["armed"].append(victim)
            if caller.both_first:
                fault.install(stack.container(other))
                state["armed"].append(other)
                break
            for _ in range(3):
                statuses.append(trigger(len(statuses)))
                time.sleep(0.4)
                if hop_failed(victim):
                    break
            if hop_failed(victim):
                break
            ctx.expect(fault.remove(stack.container(victim)), "could not remove the rule to move it")
            state["armed"].remove(victim)
            step.note(f"{victim} made no hop for these requests, so the rule moved to the other replica")
        step.note(f"blocked: {', '.join(state['armed'])}")
        if not caller.both_first:
            ctx.expect(hop_failed(victim), "no hop failure appeared on either replica")
            step.note("statuses so far: " + ", ".join(str(s) for s in statuses))
    if not caller.both_first:
        with ctx.step("The unblocked replica keeps answering while the other is blocked", services=services, match=r'"(GET|POST) /api/') as step:
            extra = []
            for n in range(2):
                extra.append(trigger(len(statuses)))
                statuses.append(extra[-1])
                time.sleep(0.4)
            step.note("statuses: " + ", ".join(str(s) for s in extra))
            bad = [s for s in statuses if s not in (200, 500, 502, 503, 504)]
            ctx.expect(not bad, f"unexpected statuses {bad}")
            ctx.expect(200 in extra or tripped(), "neither request returned 200 from the unblocked replica")

    with ctx.step("Block the other replica too and send requests until a breaker opens", services=services, match=watch) as step:
        for n in range(len(statuses), MAX_REQUESTS):
            if tripped():
                break
            if other not in state["armed"] and (n >= 6 or caller.both_first):
                fault.install(stack.container(other))
                state["armed"].append(other)
            statuses.append(trigger(n))
            time.sleep(0.4)
            if tripped():
                break
        counts = {str(k): statuses.count(k) for k in sorted(set(statuses))}
        step.note(f"{len(statuses)} requests in {time.monotonic() - begin:.1f} s, statuses {counts}")
        ctx.expect(tripped(), "no breaker opened in 24 requests")
    time.sleep(1.5)

    with ctx.step(f"Each process opens its breaker when three failures fall inside {window:.1f} s", services=services, match=r"circuit_open") as step:
        any_trip = False
        for service in services:
            raw = lines(service, started - datetime.timedelta(seconds=2))
            mine = [l for l in raw if "destination_instance_id=" + gateway_id in l]
            fails = [l for l in mine if FAIL.search(l)]
            trips = [l for l in mine if "circuit_open " in l]
            if caller.dms:
                # DMs logs its hop failures without fields, so count the Gateway's failure lines for it, and take the trip from DMs.
                fails = gateway_failures(service)
                trips = [l for l in raw if "gateway_breaker circuit_open" in l]
                ft, tt = clock.timeline(fails), clock.timeline(trips)
            else:
                order = [l for l in mine if l in fails or l in trips]
                timeline = dict(enumerate(clock.timeline(order)))
                ft = [timeline[i] for i, l in enumerate(order) if l in fails]
                tt = [timeline[i] for i, l in enumerate(order) if l in trips]
            trip_at, expected = min(tt, default=None), expected_trip(ft, window)
            ok = trip_matches(trip_at, expected, tolerance_before=1.0 if caller.dms else 0.0)
            any_trip |= trip_at is not None
            span = "none" if expected is None else f"third failure at +{expected - ft[0]:.2f} s"
            step.note(f"{service}: {len(ft)} failures, {span}, trip {'at +%.2f s' % (trip_at - ft[0]) if trip_at is not None and ft else 'none'}, matches replay {ok}")
            ctx.expect(ok, f"{service}: the trip does not match the sliding-window replay")
        ctx.expect(any_trip, "no caller process opened its breaker")
        if clock.steps():
            step.note(f"wall clock steps seen and removed from the timeline: {clock.steps()}")

    with ctx.step("Discovery removes the Gateway for circuit_open, once", services=["discovery"],
                  match=r"\bremoved service_name=gateway .*reason=circuit_open", window=(20.0, 2.0)) as step:
        before = next(r for r in stack.registry() if r["instance_id"] == gateway_id)
        ok = until(lambda: next((r for r in stack.registry() if r["instance_id"] == gateway_id and r["state"] == "removed"), None), 150, 1.0)
        ctx.expect(ok, "Discovery did not remove the Gateway in 150 s")
        ctx.expect(ok["removal_reason"] == "circuit_open", f"removal reason {ok['removal_reason']}")
        ctx.expect(ok["registration_id"] == before["registration_id"], "a different Gateway generation was removed")
        removals = [l for l in lines("discovery", started - datetime.timedelta(seconds=2)) if " removed " in l and "registration_id=" + before["registration_id"] in l]
        step.note(f"removal lines for this generation: {len(removals)}")
        ctx.expect(len(removals) == 1, f"{len(removals)} removal lines for the Gateway generation")
        counted = [l for l in lines(gateway_service, started - datetime.timedelta(seconds=2))
                   if "dependency_failure " in l and any(i in l for i in instance.values())]
        step.note(f"Gateway failure lines that name these callers: {len(counted)}")

    with ctx.step("Remove the fault, reactivate everything removed since the start (Gateway first), and check traffic",
                  services=["discovery"], match=r"\breactivated\b") as step:
        restore()
        removed = [row_service(r) for r in stack.live_rows() if r["state"] != "ready"]
        ctx.expect(not removed, "not ready: " + ", ".join(removed))
        step.note("all instances ready, 4 follow-up requests returned 200")


def case_for(caller: Caller):
    return Case(caller.id, f"{caller.title} to Gateway: three failures open its breaker", lambda ctx: run_caller(ctx, caller),
                mutation=Mutation(
                    faults=f"blocks {caller.title} replicas from the Gateway internal port with an iptables REJECT rule, which makes Discovery remove the Gateway.",
                    restores="deletes the rule, reactivates the Gateway and any caller slot removed during the run, and waits for every instance to be ready."),
                seconds=150)


def all_callers(ctx):
    for caller in CALLERS:
        ctx.ui.say(f"-- {caller.title}")
        try:
            run_caller(ctx, caller)
        except Exception:  # noqa: BLE001 the failing step is already recorded
            pass
        finally:
            # Remove this caller's rule and reactivate its removals before the next caller starts.
            ctx.run_cleanups()


SUITE = Suite(
    id="breaker", title="Caller circuit breakers", grade="7 and 10",
    description="Each caller opens its breaker after three failed Gateway hops in a window, Discovery removes the Gateway, and recovery restores it.",
    cases=[case_for(c) for c in CALLERS] + [
        Case("all", "All six callers, one after another", all_callers, seconds=len(CALLERS) * 150, aggregate=True,
             mutation=Mutation(faults="blocks each caller from the Gateway in turn, which makes Discovery remove the Gateway each time.",
                               restores="deletes each rule, reactivates the Gateway and any removed caller slot, and waits for every instance to be ready."))])
