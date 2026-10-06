# Release CPR and services

CPR releases do not build container images. Like service repositories, CPR automatically creates the release tag and GitHub release from the version in the release PR title. Service repositories also build and publish DockerHub images.

## Release from dev into main

Use the same release process for CPR and service repositories:

1. Verify the lab deliverables.
2. Open a PR from `dev` into `main`. Use `chore(vX.0.0): some description` for a lab release or `fix(vX.0.Y): some description` for a hotfix/patch of the lab.
3. Obtain the repository's required approvals, if needed, resolve review threads, if any, and pass its required checks.
4. Rebase the PR into `main`.
5. Wait for the Release and Sync Dev with Main workflows to finish.

Use `vX.0.0` for a completed lab and `vX.0.Y` for a hotfix. Each release needs an unused version greater than the existing release tags. PR checks validate the version before merge.

## Automatic releases

The [Release workflow](../.github/workflows/release.yml) runs on each push to `main`, including documentation-only updates. It finds the merged release PR and reads its exact version. A title such as `chore(v2.0.0): release lab 2` creates the annotated tag `v2.0.0` on the released commit and a matching GitHub release.

The workflow sets the tag message, release name, and release notes to `Lab X completion` for `vX.0.0` or `Lab X hotfix` for a hotfix. It marks the GitHub release as latest. The PR title supplies the version; the release text is generated automatically.

In service repositories, the workflow also builds and pushes `<repository>:X.Y.Z` and `<repository>:sha-<full-source-sha>`. It labels the image with `org.opencontainers.image.revision` and `org.opencontainers.image.version`, then updates `<repository>:latest` to the published image digest. The DockerHub steps are commented out in CPR's workflow.

The SHA tag supports image pulls by source commit. The `org.opencontainers.image.revision` label records that commit for comparison with CPR's submodule pointer without private-source access. The `org.opencontainers.image.version` label identifies the release even for images pulled as `latest` or by digest.

A workflow rerun reuses an existing tag only when it points to the same released commit. It does not create another version or move the tag. An older run cannot replace latest after a newer `main` update.

## Required GitHub secrets

Each service repository needs these three GitHub Actions secrets:

| Secret | Purpose |
| --- | --- |
| `DOCKERHUB_USERNAME` | DockerHub login user |
| `DOCKERHUB_TOKEN` | DockerHub access token with write access to the target repository |
| `DOCKERHUB_REPOSITORY` | Full target image name, such as `maxnoragami/server-rules-service` |

GitHub supplies `GITHUB_TOKEN` automatically. The release job needs `contents: write` to create tags and releases, and `pull-requests: read` to resolve the release PR. PR validation runs with read-only permissions and does not need DockerHub secrets.

## Automatic dev sync

After a release PR is rebase-merged into `main`, the Sync Dev with Main workflow uses the Sync App to reset `dev` to `main`. No manual reconciliation is needed. The workflow can also be run from GitHub Actions.

## Update a service pointer

1. Obtain the service's published `main` SHA and matching public image.
2. Update only the service checkout you can access. Leave the others uninitialized.
3. Include the source SHA, image reference, and verification result in the CPR PR description.

Private repository owners choose their own publishing workflow. The shared requirement is an image for every new `main` HEAD, including documentation-only updates. An image labelled with its source SHA makes that requirement possible to check without private-source access.

For a repeatable CPR release, record immutable image digests. The development Compose defaults use `latest`, which can change independently of CPR's service pointers.
