"""Check the documented PR naming, target and description rules."""

import json
import os
from pathlib import Path
import re
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_policy(pr):
    title = pr["title"]
    head = pr["head"]["ref"]
    base = pr["base"]["ref"]
    title_match = re.fullmatch(
        r"(feat|fix|docs|style|refactor|test|chore)\(lab-(\d+)\): \S.+", title
    )
    require(title_match, "Title must use <type>(lab-X): <summary>.")
    if base == "main":
        require(head == "dev", "Only dev may target main.")
        require(
            pr["head"]["repo"]["full_name"] == pr["base"]["repo"]["full_name"],
            "Release PR must use this repository's dev branch.",
        )
    else:
        require(base == "dev", "Task PRs must target dev.")
        branch_match = re.fullmatch(r"(feat|fix|docs|chore)/lab-(\d+)/[a-z0-9]+(?:-[a-z0-9]+)*", head)
        require(branch_match, "Branch must use <type>/lab-X/<kebab-case-description>.")
        require(branch_match[2] == title_match[2], "Branch and PR title must name the same lab.")
    body = pr.get("body") or ""
    for heading in ("Why?", "Changes", "How to Test?"):
        section = re.search(
            r"^## " + re.escape(heading) + r"\s*\n(.*?)(?=^## |\Z)",
            body, re.MULTILINE | re.DOTALL,
        )
        require(section and section[1].strip(), f"Missing content under ## {heading}.")


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    require(event_path, "GITHUB_EVENT_PATH is required.")
    event = json.loads(Path(event_path).read_text())
    check_policy(event["pull_request"])
    print("PR policy valid.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        sys.exit(1)
