"""Data classes shared by the runner, the suites, and the reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


class Check(AssertionError):
    """A failed expectation inside a step."""


class CaseAbort(Exception):
    """A fatal step failed, so the rest of the case cannot run."""


@dataclass
class LogLine:
    service: str
    replica: str
    stamp: str
    text: str


@dataclass
class Step:
    title: str
    ok: bool = True
    detail: str = ""
    seconds: float = 0.0
    started: str = ""
    logs: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def note(self, text: str):
        self.notes.append(text)


@dataclass
class Mutation:
    """What a case changes and how it puts the stack back. Shown before the case runs."""
    faults: str
    restores: str


@dataclass
class Case:
    id: str
    title: str
    run: Callable
    mutation: Optional[Mutation] = None
    seconds: int = 30


@dataclass
class Suite:
    id: str
    title: str
    grade: str
    description: str
    cases: list
    note: str = ""

    @property
    def duration(self) -> int:
        return sum(case.seconds for case in self.cases)


@dataclass
class CaseResult:
    suite: str
    case: str
    title: str
    status: str = "passed"  # passed, failed, skipped
    seconds: float = 0.0
    steps: list = field(default_factory=list)
    error: str = ""


@dataclass
class SuiteResult:
    suite: str
    grade: str
    title: str
    cases: list = field(default_factory=list)

    @property
    def status(self) -> str:
        states = {c.status for c in self.cases}
        if "failed" in states:
            return "failed"
        if states and states <= {"skipped"}:
            return "skipped"
        return "passed"

    @property
    def seconds(self) -> float:
        return sum(c.seconds for c in self.cases)
