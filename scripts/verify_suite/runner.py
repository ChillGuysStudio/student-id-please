"""Runs cases and steps, captures container logs per step, and restores the stack when a case ends."""
from __future__ import annotations

import contextlib
import datetime
import signal
import time

from .model import Case, CaseAbort, CaseResult, Check, Step
from .stack import Stack


class Context:
    """What a case receives: the stack, the output, and helpers for steps and cleanup."""

    def __init__(self, stack: Stack, ui, options):
        self.stack, self.ui, self.options = stack, ui, options
        self.run_id = stack.run_id
        self.steps: list = []
        self._cleanups: list = []
        self.data: dict = {}

    def key(self, purpose: str) -> str:
        from .util import idem_key
        return idem_key(self.run_id, purpose)

    def label(self, purpose: str) -> str:
        return f"{self.run_id}-{purpose}"

    def expect(self, condition, message: str):
        if not condition:
            raise Check(message)

    def evidence(self, step: Step, lines, per_replica: bool = True):
        """Attach log lines to a step as proof. With `per_replica`, keep the first line of each service and replica."""
        seen, kept = set(), []
        for line in lines:
            key = (line.service, line.replica)
            if per_replica and key in seen:
                continue
            seen.add(key)
            kept.append(line)
        for line in kept:
            line.text = self.stack.redactor.scrub(line.text)
        step.logs = kept

    def on_exit(self, title: str, function):
        """Register a restore action. Actions run in reverse order when the case ends, even after Ctrl-C."""
        self._cleanups.append((title, function))

    @contextlib.contextmanager
    def step(self, title: str, services=(), match=None, fatal=False, window=(1.5, 2.0)):
        """Run one check. A failed expectation or exception marks the step failed and the case continues, unless fatal."""
        step = Step(title)
        wall, mono = datetime.datetime.now(datetime.timezone.utc), time.monotonic()
        step.started = wall.isoformat()
        error = None
        try:
            yield step
        except KeyboardInterrupt:
            raise
        except Check as failure:
            step.ok, step.detail, error = False, str(failure), failure
        except Exception as failure:  # noqa: BLE001
            step.ok, step.detail, error = False, f"{type(failure).__name__}: {failure}", failure
        step.seconds = time.monotonic() - mono
        step.detail = self.stack.redactor.scrub(step.detail)
        if services:
            time.sleep(0.4)
            end = datetime.datetime.now(datetime.timezone.utc)
            try:
                step.logs = self.stack.collect_logs(services, wall - datetime.timedelta(seconds=window[0]),
                                                    end + datetime.timedelta(seconds=window[1] - 1.0), match)
            except Exception as failure:  # noqa: BLE001
                step.note(f"log capture failed: {type(failure).__name__}")
            for line in step.logs:
                line.text = self.stack.redactor.scrub(line.text)
        self.steps.append(step)
        self.ui.step(step)
        if error is not None and fatal:
            raise CaseAbort(step.detail)

    def run_cleanups(self):
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            while self._cleanups:
                title, function = self._cleanups.pop()
                started = time.monotonic()
                step = Step("restore: " + title, started=datetime.datetime.now(datetime.timezone.utc).isoformat())
                try:
                    if function() is False:  # nothing was left to restore, so show no step
                        continue
                except Exception as failure:  # noqa: BLE001
                    step.ok, step.detail = False, self.stack.redactor.scrub(f"{type(failure).__name__}: {failure}")
                step.seconds = time.monotonic() - started
                self.steps.append(step)
                self.ui.step(step)
        finally:
            signal.signal(signal.SIGINT, previous)


def run_case(stack: Stack, ui, options, suite, case: Case) -> CaseResult:
    result = CaseResult(suite=suite.id, case=case.id, title=case.title)
    if case.mutation and not ui.confirm_mutation(case, options):
        result.status = "skipped"
        ui.case_skipped(case)
        return result
    ui.case_start(suite, case)
    ctx = Context(stack, ui, options)
    started = time.monotonic()
    try:
        case.run(ctx)
    except CaseAbort as abort:
        result.error = f"stopped: {abort}"
    except KeyboardInterrupt:
        result.error = "interrupted"
        ctx.run_cleanups()
        result.steps, result.status, result.seconds = ctx.steps, "failed", time.monotonic() - started
        ui.case_end(result)
        raise
    except Exception as failure:  # noqa: BLE001
        result.error = stack.redactor.scrub(f"{type(failure).__name__}: {failure}")
        ctx.steps.append(Step("case error", ok=False, detail=result.error))
    ctx.run_cleanups()
    result.steps = ctx.steps
    result.seconds = time.monotonic() - started
    result.status = "failed" if result.error or any(not s.ok for s in ctx.steps) else "passed"
    ui.case_end(result)
    return result
