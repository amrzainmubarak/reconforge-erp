# Repository Settings

Use this checklist for GitHub settings that cannot be fully enforced from tracked files.

## Branch Protection

Protect `main` with a branch protection rule or repository ruleset:

- Block force pushes.
- Block branch deletion.
- Require pull requests before merging.
- Require at least two approving human reviews when enough maintainers are available.
- Require review from Code Owners.
- Dismiss stale approvals when new commits are pushed.
- Require approval of the most recent reviewable push.
- Require status checks for CI, security, CodeQL, Docker, and Scorecard workflows when available.
- Require branches to be up to date before merging.
- Apply the rule to administrators unless a documented emergency process is being used.
- Avoid bypass actors unless they are documented for a narrow emergency process.

These settings support the repository's code-review posture. OpenSSF Scorecard's `Branch-Protection` check gives its highest score only when force-push/deletion blocking, pull-request review, status checks, code-owner review, stale-review dismissal, most-recent-push approval, and administrator enforcement are in place. Scorecard's `Code-Review` check also considers recent merged history, so the score may not improve until future changes are merged through approved pull requests.

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

- `Maintained` depends on repository age, recent commit activity, and maintainer issue activity over the previous 90 days.
- `Code-Review` depends on reviewed pull-request history or equivalent enforced review behavior.
- `Branch-Protection` depends on GitHub branch protection or repository ruleset settings; some details may require maintainer/admin visibility for Scorecard to report accurately.
- `CII-Best-Practices` depends on OpenSSF Best Practices badge status for this Git repository URL.
- `Security-Policy`, `Token-Permissions`, `Pinned-Dependencies`, and `Fuzzing` can be substantially improved through tracked repository files.

Use [Scorecard alert triage](scorecard-alert-triage.md) when new Scorecard code-scanning alerts appear.

Keep Scorecard findings as visibility aids. They are not security certifications or audit opinions.
