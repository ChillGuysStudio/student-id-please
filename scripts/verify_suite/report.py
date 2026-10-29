"""JSON and Markdown reports for one verification run."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .util import fmt_duration

MARK = {"passed": "pass", "failed": "FAIL", "skipped": "skipped"}


def build_report(run_id, started, finished, header, results, redact=lambda s: s):
    """A JSON-ready dict from SuiteResult objects. Every string passes through `redact`."""
    suites = []
    for suite in results:
        cases = []
        for case in suite.cases:
            cases.append({
                "case": case.case, "title": case.title, "status": case.status,
                "seconds": round(case.seconds, 2), "error": redact(case.error),
                "steps": [{"title": redact(s.title), "ok": s.ok, "seconds": round(s.seconds, 3), "started": s.started,
                           "detail": redact(s.detail), "notes": [redact(n) for n in s.notes],
                           "logs": [{"service": l.service, "replica": l.replica, "stamp": l.stamp, "text": redact(l.text)}
                                    for l in s.logs]} for s in case.steps],
            })
        suites.append({"suite": suite.suite, "title": suite.title, "grade": suite.grade, "status": suite.status,
                       "seconds": round(suite.seconds, 2), "cases": cases})
    overall = "failed" if any(s["status"] == "failed" for s in suites) else "passed"
    return {"run_id": run_id, "started": started, "finished": finished, "header": header, "result": overall, "suites": suites}


def render_markdown(report: dict) -> str:
    head = report["header"]
    lines = [f"# Verification run {report['run_id']}", "",
             f"Result: {MARK.get(report['result'], report['result'])}. Started {report['started']}, finished {report['finished']}.", "",
             f"- Project: {head.get('project', '')}",
             f"- Gateway: {head.get('gateway', '')}",
             f"- Ready instances at start: {head.get('ready', '')}", "",
             "| Suite | Grade | Result | Duration |", "| --- | --- | --- | --- |"]
    for suite in report["suites"]:
        lines.append(f"| {suite['suite']} | {suite['grade']} | {MARK[suite['status']]} | {fmt_duration(suite['seconds'])} |")
    for suite in report["suites"]:
        lines += ["", f"## {suite['title']}"]
        for case in suite["cases"]:
            lines += ["", f"### {case['title']} ({MARK[case['status']]}, {fmt_duration(case['seconds'])})", ""]
            if case["error"]:
                lines += [f"Error: {case['error']}", ""]
            for step in case["steps"]:
                mark = "pass" if step["ok"] else "FAIL"
                tail = f" {step['detail']}" if step["detail"] and not step["ok"] else ""
                lines.append(f"- {mark} {step['title']} ({fmt_duration(step['seconds'])}).{tail}")
                for note in step["notes"]:
                    lines.append(f"  - {note}")
                for log in step["logs"][:8]:
                    lines.append(f"  - `{log['service']}` replica {log['replica']}: `{log['text']}`")
    return "\n".join(lines) + "\n"


def write_reports(directory: Path, report: dict) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    json_path, md_path = directory / "report.json", directory / "report.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(render_markdown(report))
    os.chmod(json_path, 0o600)
    os.chmod(md_path, 0o600)
    return json_path, md_path
