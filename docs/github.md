# Configure GitHub checks

A repository administrator configures the branch settings separately from the workflow files.

## Protect main

Configure the `main` ruleset to:

- Require a PR and one peer approval of the latest changes.
- Dismiss stale approvals and require review thread resolution.
- Require `PR policy`, `Commit policy`, and `Repository checks` from GitHub Actions.
- Allow rebase merges only and require linear history.
- Block branch deletion and force pushes.
- Leave the bypass list empty.

For release PRs, the validator requires `dev` to target `main` within the same repository and a version-scoped title. Versions are `vX.0.Y`: `Y` starts at zero and increments exactly one for each later package release or hotfix for that lab. The `PR policy` job rejects gaps, invalid prior `v` tags, and reuse for another commit; it never retags existing history.

## Configure dev

Require the same approvals and checks as `main`. Allow squash merges only, require linear history, block deletion, and allow force pushes.

Keep the Sync App's always-on bypass on `dev` so the sync workflow can update the branch. Do not give it a bypass on `main`. Developers without a `dev` bypass still need PRs.

The sync workflow uses these repository Actions secrets:

- `SYNC_APP_ID` is the GitHub App's ID.
- `SYNC_APP_PRIVATE_KEY` is the private key generated for that App.

The App needs Contents write access to this repository.

## Check workflow changes

`pr-policy.yml` and `repository-checks.yml` run through `pull_request` with read-only tokens, no deployment secrets, and no private submodule checkout. Local hooks and CI use the same validators.

A required check name does not prevent someone from weakening its script. Review validator and workflow changes before approving the PR. Local hooks do not validate approvals or repository settings.

`release.yml` runs on pushes to `main` with `contents: write` and `pull-requests: read`. GitHub supplies its token automatically. The workflow creates annotated tags and GitHub releases without checking out private submodules. CPR does not build container images.
