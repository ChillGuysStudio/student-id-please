"""Check the documented PR policy and Markdown assets without dependencies."""

import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit


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


def check_docs(root):
    root = root.resolve()
    json_count = 0
    markdown_files = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    for path in markdown_files:
        text = path.read_text()
        for block in re.findall(r"^```json\s*\n(.*?)^```\s*$", text, re.MULTILINE | re.DOTALL):
            json.loads(block)
            json_count += 1
        # Exclude fenced examples before checking actual document links.
        prose = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text, flags=re.MULTILINE | re.DOTALL)
        targets = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", prose)
        targets += re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', prose)
        for target in targets:
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            resolved = (path.parent / unquote(url.path)).resolve()
            require(root == resolved or root in resolved.parents, f"Link escapes repository: {target}")
            require(resolved.exists(), f"Broken local link in {path.name}: {target}")
    for path in (root / "docs").rglob("*.svg"):
        ET.parse(path)
    print(f"Documentation valid: {len(markdown_files)} Markdown files, {json_count} JSON examples.")


def main():
    root = Path(__file__).resolve().parents[2]
    if "--docs-only" not in sys.argv:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        require(event_path, "GITHUB_EVENT_PATH is required; use --docs-only for a local document check.")
        event = json.loads(Path(event_path).read_text())
        check_policy(event["pull_request"])
        print("PR policy valid.")
    check_docs(root)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, ET.ParseError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        sys.exit(1)
