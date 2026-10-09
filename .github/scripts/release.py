"""Validate release PR versions and reserve their annotated tags on main."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


TITLE = re.compile(
    r"(?:feat|fix|docs|style|refactor|test|chore)"
    r"\((v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\): \S(?:[^\r\n]*\S)?"
)
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def version_from_title(title):
    match = TITLE.fullmatch(title)
    if not match:
        raise ValueError("Release title must use <type>(vX.Y.Z): <summary> without leading zeros.")
    return match[1]


def validate_version(tag, sha):
    """Permit same-commit retries but never reuse a version for different code."""
    tags = subprocess.check_output(["git", "tag", "--list"], text=True).splitlines()
    if tag in tags:
        target = subprocess.check_output(["git", "rev-parse", f"{tag}^{{commit}}"], text=True).strip()
        if target != sha:
            raise ValueError(f"{tag} already identifies another commit. Use a new release version.")
        return False
    version = tuple(map(int, TAG.fullmatch(tag).groups()))
    existing = [tuple(map(int, match.groups())) for name in tags if (match := TAG.fullmatch(name))]
    if existing and version <= max(existing):
        raise ValueError("Release version must be greater than every existing release tag.")
    return True


def check_release_pr(pr, repository):
    if pr["base"]["ref"] != "main":
        return
    head_repository = (pr["head"].get("repo") or {}).get("full_name")
    if pr["head"]["ref"] != "dev" or head_repository != repository:
        raise ValueError("Only this repository's dev branch may release to main.")
    tag = version_from_title(pr["title"])
    if not validate_version(tag, pr["head"]["sha"]):
        raise ValueError(f"{tag} already exists. Choose a new version in the PR title.")
    print(f"Release PR version is valid: {tag}")


def api(path, payload=None):
    args = ["gh", "api", path]
    if payload is not None:
        args.extend(["--method", "POST", "--input", "-"])
    result = subprocess.run(
        args, input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def release_pr(prs, repository, sha):
    candidates = [pr for pr in prs if pr.get("merged_at")
                  and pr["base"]["ref"] == "main"
                  and pr["head"]["ref"] == "dev"
                  and (pr["head"].get("repo") or {}).get("full_name") == repository
                  and pr.get("merge_commit_sha") == sha]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one merged dev-to-main PR for the pushed main HEAD.")
    return candidates[0]


def reserve_tag(repository, tag, sha):
    if validate_version(tag, sha):
        annotated = api(f"repos/{repository}/git/tags", {
            "tag": tag, "message": "", "object": sha, "type": "commit",
        })
        api(f"repos/{repository}/git/refs", {"ref": f"refs/tags/{tag}", "sha": annotated["sha"]})


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    if os.environ.get("RELEASE_CHECK") == "true":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        check_release_pr(event["pull_request"], repository)
        return
    if os.environ["GITHUB_REF"] != "refs/heads/main":
        raise ValueError("Release job must run for main.")
    sha = os.environ["GITHUB_SHA"]
    for attempt in range(6):
        prs = api(f"repos/{repository}/commits/{sha}/pulls?per_page=100")
        try:
            pr = release_pr(prs, repository, sha)
            break
        except ValueError:
            if attempt == 5:
                raise
            time.sleep(5)
    tag = version_from_title(pr["title"])
    reserve_tag(repository, tag, sha)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"tag={tag}\nversion={tag[1:]}\n")
    print(f"Reserved {tag} for PR #{pr['number']} at {sha}.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        sys.exit(1)
