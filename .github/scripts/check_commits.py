"""Check PR commit subjects against the documented commit convention."""

import re
import subprocess
import sys


COMMIT_SUBJECT = re.compile(
    r"(feat|fix|docs|style|refactor|test|chore)"
    r"(?:\([a-z0-9]+(?:-[a-z0-9]+)*\))?: "
    r"\S(?:.*\S)?"
)


def validate_subject(subject):
    """Return whether a commit subject follows type(scope): summary."""
    return COMMIT_SUBJECT.fullmatch(subject) is not None


def commits_in_range(base, head):
    """Return (SHA, subject) pairs introduced between two Git refs."""
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=%H%x09%s", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    commits = []
    for line in result.stdout.splitlines():
        commit, subject = line.split("\t", 1)
        commits.append((commit, subject))
    return commits


def check_range(base, head):
    """Validate every commit introduced by a pull request."""
    commits = commits_in_range(base, head)
    if not commits:
        raise ValueError("The pull request does not introduce any commits.")

    invalid = [
        f"{commit[:7]} {subject}"
        for commit, subject in commits
        if not validate_subject(subject)
    ]
    if invalid:
        details = "\n".join(f"  - {entry}" for entry in invalid)
        raise ValueError(
            "Commit subjects must use <type>(<scope>): <summary>, where type is "
            "feat, fix, docs, style, refactor, test, or chore.\n"
            f"Invalid commits:\n{details}"
        )

    print(f"Commit policy valid for {len(commits)} commit(s).")


def main():
    if len(sys.argv) != 3:
        raise ValueError("Usage: check_commits.py <base-ref> <head-ref>")
    check_range(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        sys.exit(1)
