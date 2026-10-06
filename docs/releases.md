# Release CPR

1. Verify the lab deliverables and the public images for the service SHAs recorded by CPR. State any remaining mocks or disconnected services in the release description.
2. Open a PR from `dev` into `main`. Use a title such as `chore(v1.0.0): release lab 1`.
3. Obtain a peer approval, resolve review threads, and pass the required PR checks.
4. Rebase the PR into `main`.
5. Update your local release branch without fetching private sources:

	```sh
	git fetch --no-recurse-submodules origin main dev
	git switch main
	git pull --ff-only --no-recurse-submodules
	```

6. Create an annotated tag on `main`:

	```sh
	git tag -a v1.0.0 -m "Lab 1 completion"
	git push origin v1.0.0
	```

Use `vX.0.0` for a completed lab and `vX.0.Y` for a hotfix. The release PR scope and tag must identify the same version.

## Reconcile dev without deleting work

Rebase merging can change commit SHAs, so `main` and `dev` may contain the same work with different history.

Before resetting `dev`, fetch both branches and compare their trees:

```sh
git fetch --no-recurse-submodules origin main dev
git diff --exit-code origin/main origin/dev
```

If the diff is empty and the team has no unmerged work on `dev`, reconcile the branch with:

```sh
git push --force-with-lease=refs/heads/dev:$(git rev-parse origin/dev) origin origin/main:refs/heads/dev
```

If the trees differ, do not reset `dev` to `main`. Preserve the integration commits and coordinate a rebase with the team.

## Update a service pointer

1. Obtain the service's published `main` SHA and matching public image.
2. Update only the service checkout you can access. Leave the others uninitialized.
3. Include the source SHA, image reference, and verification result in the CPR PR description.

Private repository owners choose their own publishing workflow. The shared requirement is an image for every new `main` HEAD, including documentation-only updates. An image labelled with its source SHA makes that requirement possible to check without private-source access.

For a repeatable CPR release, record immutable image digests. The development Compose defaults use `latest`, which can change independently of CPR's service pointers. Container startup alone does not prove that an image matches a recorded source SHA.
