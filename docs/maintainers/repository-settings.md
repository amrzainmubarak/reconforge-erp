# Repository Settings

Use this checklist for GitHub settings that cannot be fully enforced from tracked files.

## Branch Protection

Protect `main` with a branch protection rule or repository ruleset:

- Require pull requests before merging.
- Require at least one approving human review.
- Require review from Code Owners.
- Dismiss stale approvals when new commits are pushed.
- Require status checks for CI, security, CodeQL, Docker, and Scorecard workflows when available.
- Apply the rule to administrators unless a documented emergency process is being used.

These settings support the repository's code-review posture. OpenSSF Scorecard's `Code-Review` check also considers recent merged history, so the score may not improve until future changes are merged through reviewed pull requests.

## Actions And Token Defaults

- Set the default `GITHUB_TOKEN` workflow permission to read-only in repository Actions settings.
- Keep workflow-level `permissions` blocks checked in.
- Add write permissions only at the job level for jobs that upload SARIF or publish signed release artifacts.
- Keep checkout credentials disabled with `persist-credentials: false` unless a job explicitly needs them.

## Security Features

Enable or keep enabled:

- GitHub private vulnerability reporting.
- Code scanning alerts.
- Dependabot alerts and Dependabot updates for Python and GitHub Actions.
- Secret scanning when available for the repository plan.

The private vulnerability reporting URL advertised in `SECURITY.md` should continue to point to this repository.

## Scorecard Notes

Some OpenSSF Scorecard checks are partly or entirely based on repository metadata rather than files:

- `Maintained` depends on recent commit and maintainer issue activity over the previous 90 days.
- `Code-Review` depends on reviewed pull-request history or equivalent enforced review behavior.
- `Security-Policy`, `Token-Permissions`, `Pinned-Dependencies`, and `Fuzzing` can be substantially improved through tracked repository files.

Keep Scorecard findings as visibility aids. They are not security certifications or audit opinions.
