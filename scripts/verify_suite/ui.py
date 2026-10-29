"""Terminal output built on rich: header, steps with log lines, menu, prompts, and the summary table."""
from __future__ import annotations

import re
import sys

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .util import fmt_duration

DEFAULT_LOG_LINES = 4
_VARIABLE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b[0-9a-f]{8,}\b|\d+")


def collapse(lines) -> list:
    """Merge lines of the same service and replica whose text differs only in numbers and ids.

    Returns (first line of the group, group size) pairs in order of first appearance."""
    groups: dict = {}
    for line in lines:
        key = (line.service, line.replica, _VARIABLE.sub("#", line.text))
        if key in groups:
            groups[key][1] += 1
        else:
            groups[key] = [line, 1]
    return [(line, count) for line, count in groups.values()]

STATUS_STYLE = {"passed": "[green]pass[/]", "failed": "[bold red]FAIL[/]", "skipped": "[yellow]skipped[/]"}


class UI:
    def __init__(self, verbose=False, quiet=False, yes=False, console=None):
        self.console = console or Console(highlight=False, soft_wrap=False)
        if not self.console.is_terminal and console is None:
            self.console.width = max(self.console.width, 120)
        self.verbose, self.quiet, self.yes = verbose, quiet, yes
        self.interactive = sys.stdin.isatty() and sys.stdout.isatty()

    def say(self, text="", style=None):
        self.console.print(escape(text) if style is None else f"[{style}]{escape(text)}[/]")

    # ---------------------------------------------------------------- header and suites
    def header(self, info: dict):
        table = Table.grid(padding=(0, 2))
        for key in ("Project", "Gateway", "Ready", "Run ID"):
            table.add_row(f"[bold]{key}[/]", escape(str(info.get(key.lower().replace(" ", "_"), ""))))
        self.console.print(table)
        self.console.print()

    def stack_down(self, message: str):
        self.console.print(f"[bold red]The stack is not running.[/] {escape(message)}")

    def suite_start(self, suite):
        self.console.rule(f"[bold]{escape(suite.title)}[/]  [dim]grade {escape(suite.grade)}[/]", align="left")

    def case_start(self, suite, case):
        if not self.quiet:
            self.console.print(f"[bold cyan]{escape(case.title)}[/]")

    def case_skipped(self, case):
        self.console.print(f"[yellow]Skipped[/] {escape(case.title)}")

    def case_end(self, result):
        style = STATUS_STYLE[result.status]
        line = f"  {style} {escape(result.title)} [dim]({fmt_duration(result.seconds)})[/]"
        if result.error:
            line += f" [red]{escape(result.error)}[/]"
        if not self.quiet or result.status != "passed":
            self.console.print(line)
            self.console.print()

    # ---------------------------------------------------------------- steps
    def step(self, step):
        if self.quiet and step.ok:
            return
        mark = "[green]✓[/]" if step.ok else "[bold red]✗[/]"
        self.console.print(f"  {mark} {escape(step.title)} [dim]{fmt_duration(step.seconds)}[/]")
        if step.detail and not step.ok:
            self.console.print(f"      [red]{escape(step.detail)}[/]")
        if self.quiet:
            return
        for note in step.notes:
            self.console.print(f"      [dim]{escape(note)}[/]")
        if self.verbose:
            rows = [(line, 1) for line in step.logs]
        else:
            rows = collapse(step.logs)
        shown = rows if self.verbose else rows[:DEFAULT_LOG_LINES]
        for line, count in shown:
            who = f"{line.service} #{line.replica}"
            times = f" [dim]×{count}[/]" if count > 1 else ""
            self.console.print(f"      [dim]{escape(line.stamp)}[/] [magenta]{escape(who):<24}[/] {escape(line.text)}{times}")
        hidden = sum(count for _, count in rows[len(shown):])
        if hidden:
            self.console.print(f"      [dim]... {hidden} more lines (use --verbose)[/]")

    # ---------------------------------------------------------------- prompts
    def confirm_mutation(self, case, options) -> bool:
        m = case.mutation
        self.console.print(f"[bold yellow]Warning[/] {escape(case.title)}. Faults: {escape(m.faults)} Restores: {escape(m.restores)}")
        if self.yes:
            return True
        if not self.interactive:
            self.console.print("[yellow]Not a terminal and no --yes, so this case does not run.[/]")
            return False
        while True:
            answer = self.console.input("Run? \\[Y/n] ").strip().lower()
            if answer in ("", "y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

    def choose(self, prompt: str, count: int, allow_all=True):
        """Return an index, 'all', or None to quit."""
        while True:
            answer = self.console.input(prompt).strip().lower()
            if answer in ("q", "quit", "exit"):
                return None
            if allow_all and answer in ("a", "all"):
                return "all"
            if answer.isdigit() and 1 <= int(answer) <= count:
                return int(answer) - 1

    def suite_table(self, suites):
        table = Table(show_header=True, header_style="bold")
        for column in ("#", "Suite", "Grade", "What it shows", "Duration"):
            table.add_column(column)
        for number, suite in enumerate(suites, 1):
            mark = " (changes the stack)" if any(c.mutation for c in suite.cases) else ""
            table.add_row(str(number), suite.id, suite.grade, escape(suite.description + mark), fmt_duration(suite.duration))
        self.console.print(table)

    def case_table(self, suite):
        table = Table(show_header=True, header_style="bold")
        for column in ("#", "Case", "Changes the stack", "Duration"):
            table.add_column(column)
        for number, case in enumerate(suite.cases, 1):
            table.add_row(str(number), escape(case.title), "yes, restores" if case.mutation else "no", fmt_duration(case.seconds))
        self.console.print(table)

    # ---------------------------------------------------------------- summary
    def summary(self, results, paths=None):
        table = Table(title="Summary", show_header=True, header_style="bold")
        for column in ("Suite", "Grade", "Result", "Duration"):
            table.add_column(column)
        for suite in results:
            table.add_row(suite.suite, suite.grade, STATUS_STYLE[suite.status], fmt_duration(suite.seconds))
        self.console.print(table)
        if paths:
            self.console.print(f"Reports: {escape(str(paths[0]))}")
            self.console.print(f"         {escape(str(paths[1]))}")
