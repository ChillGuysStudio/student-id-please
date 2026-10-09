# Configure GitHub checks

These branch settings apply to CPR. A repository administrator configures them separately from the workflow files. Private organization-owned service repositories are exempt from enforcing branch rulesets or branch protection because those features require a paid subscription.

## Protect main

Configure the CPR `main` ruleset to:

- Require a PR and one peer approval of the latest changes.
- Dismiss stale approvals and require review thread resolution.
- Require `PR policy`, `Commit policy`, and `Repository checks` from GitHub Actions.
- Allow rebase merges only and require linear history.
- Block branch deletion and force pushes.
- Leave the bypass list empty.

For release PRs, require `dev` to target `main` within the same repository and a version-scoped title. Versions follow the repository's `vX.0.Y` sequence, starting at `vX.0.0` and advancing one release at a time. New versions must be unused and greater than existing release versions. The [release procedure](releases.md) defines the sequence and optional release notes.

## Configure dev

On CPR `dev`, require the same approvals and checks as `main`. Allow squash merges only, require linear history, block deletion, and allow force pushes. Service repositories do not require reviews or approvals.

Keep the Sync App's always-on bypass on `dev` so the sync workflow can update the branch. Do not give it a bypass on `main`. Developers without a `dev` bypass still need PRs.

The sync workflow uses these repository Actions secrets:

- `SYNC_APP_ID` is the GitHub App's ID.
- `SYNC_APP_PRIVATE_KEY` is the private key generated for that App.

The App needs Contents write access to this repository.

## Check workflow changes

`pr-policy.yml` and `repository-checks.yml` run through `pull_request` with read-only tokens, no deployment secrets, and no private submodule checkout. Local hooks and CI use the same validators.

A required check name does not prevent someone from weakening its script. Review validator and workflow changes before approving the PR. Local hooks do not validate approvals or repository settings.

`release.yml` runs on pushes to `main` with `contents: write` and `pull-requests: read`. GitHub supplies its token automatically. The workflow creates annotated tags and GitHub releases without checking out private submodules. CPR does not build container images.
