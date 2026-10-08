"""Validate conventional commit subjects for PRs and local hooks."""

import argparse
from pathlib import Path
import re
import subprocess
import sys


COMMIT_SUBJECT = re.compile(
    r"(feat|fix|docs|style|refactor|test|chore)"
    r"(?:\([a-z0-9]+(?:[.-][a-z0-9]+)*\))?!?: "
    r"\S(?:[^\r\n]*\S)?"
)
SUBJECT_GUIDANCE = (
    "Subjects must use <type>(<optional-scope>)!: <summary>; scope and ! are "
    "optional. Types: feat, fix, docs, style, refactor, test, chore. "
    "Imperative mood is recommended, not enforced."
)


def validate_subject(subject):
    """Return whether a subject follows the convention."""
    return COMMIT_SUBJECT.fullmatch(subject) is not None


def check_message_file(path):
    """Check only the first line of a complete commit message."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or not validate_subject(lines[0]):
        raise ValueError(SUBJECT_GUIDANCE)


def resolve_commit(ref):
    """Resolve a locally available ref, without fetching."""
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def commits_in_range(base, head):
    """Return every (SHA, subject) introduced between two local Git refs."""
    base, head = resolve_commit(base), resolve_commit(head)
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=%H%x09%s", f"{base}..{head}", "--"],
        check=True, capture_output=True, text=True,
    )
    return [tuple(line.split("\t", 1)) for line in result.stdout.splitlines()]


def check_range(base, head, *, allow_empty=False):
    """Validate introduced commits; PRs must not be empty, pushes may be."""
    commits = commits_in_range(base, head)
    if not commits and not allow_empty:
        raise ValueError("The pull request does not introduce any commits.")
    invalid = [
        f"{commit[:7]} {subject}"
        for commit, subject in commits if not validate_subject(subject)
    ]
    if invalid:
        details = "\n".join(f"  - {entry}" for entry in invalid)
        raise ValueError(f"{SUBJECT_GUIDANCE}\nInvalid commits:\n{details}")
    print(f"Commit policy valid for {len(commits)} commit(s).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-file", help="check the first line of a commit message")
    parser.add_argument("refs", nargs="*", metavar="REF")
    args = parser.parse_args(argv)
    if args.message_file is not None:
        if args.refs:
            parser.error("--message-file cannot be combined with refs")
        check_message_file(args.message_file)
    else:
        if len(args.refs) != 2:
            parser.error("supply BASE HEAD or --message-file PATH")
        check_range(*args.refs)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        sys.exit(1)
