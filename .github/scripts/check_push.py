"""Validate pre-push ref updates using only locally available Git objects."""

import re
import subprocess
import sys

from check_commits import check_range, resolve_commit


OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def is_zero(oid):
    return not oid.strip("0")


def new_branch_base():
    """Prefer origin/dev, falling back to local dev; never skip validation."""
    for ref in ("refs/remotes/origin/dev", "refs/heads/dev"):
        try:
            return resolve_commit(ref)
        except subprocess.CalledProcessError:
            pass
    raise ValueError(
        "New refs need a local dev or origin/dev baseline. "
        "Create one before pushing; this hook does not fetch."
    )


def check_push(lines):
    """Check each local-ref/local-OID/remote-ref/remote-OID input record."""
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("Expected four fields per pre-push input line.")
        local_ref, local_oid, remote_ref, remote_oid = fields
        if not OID.fullmatch(local_oid) or not OID.fullmatch(remote_oid):
            raise ValueError("Invalid object ID in pre-push input.")
        if is_zero(local_oid):
            if remote_ref in ("refs/heads/main", "refs/heads/dev"):
                raise ValueError(f"Deleting {remote_ref.rsplit('/', 1)[1]} is not permitted.")
            continue
        # Use the supplied object IDs, not HEAD or a possibly stale tracking ref.
        local_commit = resolve_commit(local_oid)
        if is_zero(remote_oid):
            base = new_branch_base()
        else:
            base = resolve_commit(remote_oid)
            if remote_ref == "refs/heads/main":
                ancestor = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", base, local_commit],
                    capture_output=True, text=True,
                )
                if ancestor.returncode == 1:
                    raise ValueError("Force pushes to main are not permitted.")
                ancestor.check_returncode()
        print(f"Checking {local_ref} -> {remote_ref}")
        check_range(base, local_commit, allow_empty=True)


if __name__ == "__main__":
    try:
        check_push(sys.stdin)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Push check failed: {error}", file=sys.stderr)
        sys.exit(1)
