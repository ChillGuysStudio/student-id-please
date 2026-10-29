"""Sliding-window replay of breaker log lines on a step-free timeline.

The host wall clock steps back about 1.8 s every 32 s, while the monotonic clock does not. Log stamps from one
process can therefore run backwards across a step, and a correct three-failures-in-a-window breaker then looks
wrong. `ClockTrack` samples wall minus monotonic time. That offset stays constant between steps, so each log stamp can
be mapped to the monotonic instant whose wall reading matches it."""
from __future__ import annotations

import datetime
import re
import threading
import time

STAMP = re.compile(r"(\d{4}[-/]\d{2}[-/]\d{2})[T ](\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)")


def stamp(line: str) -> float:
    """Epoch seconds of the timestamp inside a container log line. Container logs are UTC."""
    match = STAMP.search(line)
    if not match:
        raise ValueError("no timestamp in line")
    text = match.group(1).replace("/", "-") + "T" + match.group(2).replace(",", ".")
    return datetime.datetime.fromisoformat(text).replace(tzinfo=datetime.timezone.utc).timestamp()


def resolution(line: str) -> float:
    """Timestamp precision of a line in seconds: milliseconds when it has a fraction, otherwise one second."""
    return 0.05 if re.search(r"\d{2}:\d{2}:\d{2}[.,]\d", line) else 1.0


class ClockTrack:
    def __init__(self, period=0.01, step=0.25, start=True):
        self.period, self.step = period, step
        self.stop = threading.Event()
        w, m = time.time(), time.monotonic()
        self.segs = [[m, m, w - m]]  # [first monotonic, last monotonic, wall minus monotonic]
        self.thread = threading.Thread(target=self._run, daemon=True)
        if start:
            self.thread.start()

    def _run(self):
        while not self.stop.wait(self.period):
            self.sample(time.time(), time.monotonic())

    def sample(self, wall: float, mono: float):
        seg = self.segs[-1]
        if abs((wall - mono) - seg[2]) > self.step:
            self.segs.append([mono, mono, wall - mono])
        else:
            seg[1] = mono

    def steps(self) -> list:
        return [round(b[2] - a[2], 3) for a, b in zip(self.segs, self.segs[1:])]

    def timeline(self, lines) -> list:
        """Monotonic instants for the log lines of one process, given in arrival order.

        For each line the candidates are the instants whose wall reading matches the stamp. The earliest one that keeps
        the lines in arrival order wins."""
        out, prev = [], None
        for line in lines:
            wall = stamp(line)
            res = resolution(line)
            candidates = sorted(wall - seg[2] for seg in list(self.segs) if seg[0] - res - 0.05 <= wall - seg[2] <= seg[1] + res + 0.05)
            if not candidates:
                candidates = [wall - self.segs[-1][2]]
            pick = next((c for c in candidates if prev is None or c >= prev - 0.25), candidates[-1])
            out.append(pick)
            prev = pick if prev is None else max(prev, pick)
        return out


def expected_trip(failures, window: float, threshold: int = 3):
    """Time of the failure that fills the window: the first failure with `threshold` failures in [t - window, t].

    The window includes its start, as docs/contracts/resilience.md requires: failures at 0, 2 and 7 s trip a 7 s window.
    """
    for index, t in enumerate(failures):
        if len([f for f in failures[: index + 1] if t - window <= f <= t]) >= threshold:
            return t
    return None


def trip_matches(trip_at, expected, tolerance_before: float = 0.0, tolerance_after: float = 1.0) -> bool:
    """A process that never had a full window must not trip. Otherwise the trip must follow the filling failure closely."""
    if expected is None:
        return trip_at is None
    return trip_at is not None and tolerance_before * -1 <= trip_at - expected <= tolerance_after
