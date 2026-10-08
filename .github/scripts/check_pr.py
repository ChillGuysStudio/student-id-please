"""Validate task and release PR titles, targets, and descriptions."""

import json
import os
from pathlib import Path
import re
import sys

from check_commits import validate_subject
from release import version_from_title


TYPES = r"(?:feat|fix|docs|style|refactor|test|chore)"
TEMPLATE_PROMPTS = {
    "Why?": "Describe the problem and why this change is needed.",
    "Changes": "Describe the resulting behavior and relevant design choices.",
    "How to Test?": "List the checks reviewers can run and the results already verified.",
}
PLACEHOLDER = re.compile(
    r"(?:todo|tbd|fixme|n/?a|none|pending|placeholder|test|testing|"
    r"why|changes|how to test|your (?:text|answer|description) here|"
    r"(?:fill|write|insert|add) (?:this|here|.+ here)|"
    r"(?:describe|explain) (?:why|the changes|your changes|the tests)|"
    r"replace (?:this|me|.+ here)|\.{3}|…|[-_]+)[.!?]*",
    re.IGNORECASE,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def meaningful_section(text, heading):
    """Ignore comments, template prompts, and common placeholder-only lines."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:\[[ xX]\]\s*)?", "", line)
        line = line.strip(" \t*_`>\r")
        if line == TEMPLATE_PROMPTS[heading] or PLACEHOLDER.fullmatch(line):
            continue
        if len(re.findall(r"[a-zA-Z0-9]", line)) >= 3:
            return True
    return False


def check_policy(pr):
    title = pr["title"]
    head = pr["head"]["ref"]
    base = pr["base"]["ref"]
    require(validate_subject(title), "PR title must be a conventional subject.")
    if base == "main":
        require(head == "dev", "Only dev may target main.")
        head_repo = pr["head"].get("repo") or {}
        base_repo = pr["base"].get("repo") or {}
        require(
            head_repo.get("full_name")
            and head_repo.get("full_name") == base_repo.get("full_name"),
            "Release PR must use this repository's dev branch.",
        )
        version_from_title(title)
    else:
        require(base == "dev", "Task PRs must target dev.")
        require(
            re.fullmatch(TYPES + r"\(lab-\d+\): \S(?:[^\r\n]*\S)?", title),
            "Task title must use <type>(lab-X): <summary>.",
        )
    body = re.sub(r"<!--.*?-->", "", pr.get("body") or "", flags=re.DOTALL)
    for heading in TEMPLATE_PROMPTS:
        sections = re.findall(
            r"^## " + re.escape(heading) + r"[ \t]*\r?\n(.*?)(?=^#{1,2} |\Z)",
            body, re.MULTILINE | re.DOTALL,
        )
        require(
            len(sections) == 1 and meaningful_section(sections[0], heading),
            f"Add meaningful, non-placeholder content under ## {heading}.",
        )


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    require(event_path, "GITHUB_EVENT_PATH is required.")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    check_policy(event["pull_request"])
    print("PR policy valid.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        sys.exit(1)
