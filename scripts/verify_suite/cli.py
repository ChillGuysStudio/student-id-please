"""Command line: menu, non-interactive forms, header, run loop, and reports."""
from __future__ import annotations

import argparse
import datetime
import sys
import uuid
from pathlib import Path

from .model import SuiteResult
from .report import build_report, write_reports
from .runner import run_case
from .stack import Stack, StackError
from .suites import all_suites
from .ui import UI
from .util import new_run_id

EPILOG = """examples:
  uv run scripts/verify.py                  open the menu
  uv run scripts/verify.py list             list suites and cases
  uv run scripts/verify.py status           run one suite
  uv run scripts/verify.py scaling up-down  run one case
  uv run scripts/verify.py status --yes     skip the confirmation before cases that change the stack
"""


def parse(argv):
    parser = argparse.ArgumentParser(prog="verify.py", description="Verify the running stack against the course grades.",
                                     epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", help="a suite id, or `list`")
    parser.add_argument("case", nargs="?", help="a case id inside the suite")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="directory with .env, .local/stack and .local/postman (default: this repository)")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask before cases that change the stack")
    parser.add_argument("--verbose", "-v", action="store_true", help="print every captured log line")
    parser.add_argument("--quiet", "-q", action="store_true", help="print failures and the summary only")
    return parser.parse_args(argv)


def list_suites(ui, suites):
    for suite in suites:
        ui.say(f"{suite.id}  (grade {suite.grade})  {suite.description}")
        for case in suite.cases:
            ui.say(f"    {suite.id} {case.id}  {case.title}" + ("  [changes the stack, restores it]" if case.mutation else ""))


def pick_interactively(ui, suites):
    """Menu: choose a suite, then a case. Returns a list of (suite, [cases]) or None."""
    ui.suite_table(suites)
    chosen = ui.choose("Suite number, or q to quit: ", len(suites), allow_all=False)
    if chosen is None:
        return None
    suite = suites[chosen]
    ui.case_table(suite)
    case = ui.choose("Case number, a for all cases, or q to quit: ", len(suite.cases))
    if case is None:
        return None
    return [(suite, suite.cases if case == "all" else [suite.cases[case]])]


def select(args, suites):
    by_id = {s.id: s for s in suites}
    if args.target not in by_id:
        raise SystemExit(f"Unknown suite {args.target!r}. Suites: {', '.join(by_id)}. Run `verify.py list` for the cases.")
    suite = by_id[args.target]
    if not args.case:
        return [(suite, suite.cases)]
    cases = [c for c in suite.cases if c.id == args.case]
    if not cases:
        raise SystemExit(f"Unknown case {args.case!r} in {suite.id}. Cases: {', '.join(c.id for c in suite.cases)}.")
    return [(suite, cases)]


def main(argv=None):
    args = parse(sys.argv[1:] if argv is None else argv)
    suites = all_suites()
    ui = UI(verbose=args.verbose, quiet=args.quiet, yes=args.yes)
    if args.target == "list":
        list_suites(ui, suites)
        return 0
    started_at = datetime.datetime.now(datetime.timezone.utc)
    run_id = new_run_id(started_at, uuid.uuid4().hex)
    try:
        stack = Stack(args.root, run_id)
        if not stack.healthy() or not stack.containers():
            ui.stack_down(f"Start it with:\n  {stack.start_command}")
            return 2
        ready, total = stack.ready_count()
    except StackError as error:
        ui.stack_down(str(error))
        return 2
    except Exception as error:  # noqa: BLE001
        ui.stack_down(f"{type(error).__name__}. Start it with:\n  cd {args.root} && docker compose up -d --wait")
        return 2
    stack.notice = ui.say
    header = {"project": stack.project, "gateway": stack.gateway_url, "ready": f"{ready} of {total} instances ready", "run_id": run_id}
    ui.header(header)
    if args.target:
        plan = select(args, suites)
    else:
        if not ui.interactive:
            ui.say("No suite given. Run `verify.py list` to see the suites, or open the menu in a terminal.")
            return 2
        plan = pick_interactively(ui, suites)
        if plan is None:
            return 0
    results = []
    try:
        for suite, cases in plan:
            ui.suite_start(suite)
            outcome = SuiteResult(suite.id, suite.grade, suite.title)
            results.append(outcome)
            for case in cases:
                outcome.cases.append(run_case(stack, ui, args, suite, case))
    except KeyboardInterrupt:
        ui.say("Interrupted. The stack was restored.", "yellow")
    report = build_report(run_id, started_at.isoformat(), datetime.datetime.now(datetime.timezone.utc).isoformat(), header, results,
                          redact=stack.redactor.scrub)
    paths = write_reports(args.root / ".local" / "verify" / run_id, report)
    ui.summary(results, paths)
    return 0 if report["result"] == "passed" and results else 1
