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

The PR validator accepts only this repository's `dev` as the release source. It requires a version-scoped title.

## Configure dev

Require the same approvals and checks as `main`. Allow squash merges only, require linear history, block deletion, and allow force pushes.

Keep the Sync App's always-on bypass on `dev` so the sync workflow can update the branch. Do not give it a bypass on `main`. Developers without a `dev` bypass still need PRs.

## Check workflow changes

`pr-policy.yml` and `repository-checks.yml` run through `pull_request` with read-only tokens, no deployment secrets, and no private submodule checkout. PR CI and local hooks use the same proposed validators.

A required check name does not prevent someone from weakening its script. Review validator and workflow changes before approving the PR. Local hooks do not validate approvals or repository settings.
