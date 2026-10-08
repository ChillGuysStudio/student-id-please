#!/usr/bin/env python3
"""Initialize or update only one developer's two service submodules."""

import argparse
from pathlib import Path
import subprocess
import sys


PROFILES = {
    "andrei": ("moderation-service", "discord-dms-service"),
    "adrian": ("applicant-service", "credential-service"),
    "alexei": ("server-rules-service", "university-record-service"),
    "alexandru": ("player-service", "session-service"),
}
ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=None, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd or ROOT, check=check, capture_output=True, text=True,
    )


def module_paths():
    result = git("config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$")
    return dict(line.split(maxsplit=1) for line in result.stdout.splitlines())


def check_worktree(path):
    """Do not overwrite local edits or detach an in-progress service branch."""
    directory = ROOT / path
    if not (directory / ".git").exists():
        return
    top = git("rev-parse", "--show-toplevel", cwd=directory)
    if Path(top.stdout.strip()).resolve() != directory.resolve():
        raise ValueError(f"{path} is not a valid service checkout.")
    if git("status", "--porcelain", cwd=directory).stdout.strip():
        raise ValueError(f"{path} has local changes. Finish or save them before updating.")
    branch = git("symbolic-ref", "--quiet", "HEAD", cwd=directory, check=False)
    head = git("rev-parse", "HEAD", cwd=directory).stdout.strip()
    entry = git("ls-files", "--stage", "--", path).stdout.strip().split()
    if len(entry) != 4 or entry[0] != "160000":
        raise ValueError(f"{path} must have one recorded submodule pin.")
    if branch.returncode == 0 and head != entry[1]:
        raise ValueError(
            f"{path} is on a task branch. Switch that service to a detached "
            "checkout before changing its pin."
        )


def update(profile):
    paths = PROFILES[profile]
    modules = module_paths()
    missing = set(paths) - set(modules.values())
    if missing:
        raise ValueError(f"Services missing from .gitmodules: {', '.join(sorted(missing))}")
    for path in paths:
        check_worktree(path)
    git("config", "--local", "submodule.recurse", "false")
    git("config", "--local", "fetch.recurseSubmodules", "false")
    git("config", "--local", "push.recurseSubmodules", "no")
    for key, path in modules.items():
        active_key = key.removesuffix(".path") + ".active"
        git("config", "--local", active_key, "true" if path in paths else "false")
    print(f"Updating {profile}: {', '.join(paths)}", flush=True)
    subprocess.run(
        ["git", "-c", "submodule.recurse=false", "-c", "fetch.recurseSubmodules=false",
         "submodule", "update", "--init", "--", *paths],
        cwd=ROOT, check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "update"))
    parser.add_argument("profile", choices=PROFILES)
    args = parser.parse_args()
    update(args.profile)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Service update failed: {error}", file=sys.stderr)
        sys.exit(1)
