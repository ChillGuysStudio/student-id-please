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

Configure ordinary task PRs to require the same approvals and checks. Allow squash merges only. Block branch deletion and require linear history.

Remove the non-fast-forward restriction if you allow force pushes. GitHub's PR requirement still blocks direct rewrites unless the caller has a bypass. Give the team a `dev`-only bypass if team members must perform those rewrites. Never give that bypass access to the `main` ruleset.

A bypass can skip `dev` checks. Hooks check local pushes, but contributors can disable hooks. The required release PR checks on `main` validate every introduced commit again. This is the enforcement limit of allowing direct `dev` rewrites.

Limit `dev` bypass access to the people who coordinate branch rewrites. Remove unused bypass actors.

## Check workflow changes

Both workflows run through `pull_request` with read-only tokens, no deployment secrets, and no private submodule checkout. PR CI and local hooks use the same proposed validators.

A required check name does not prevent someone from weakening its script. Review validator and workflow changes before approving the PR. Local hooks do not validate approvals or repository settings.

