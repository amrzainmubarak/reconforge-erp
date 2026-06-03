# Scorecard Alert Triage

Use this runbook when OpenSSF Scorecard creates code-scanning alerts with no source file attached. Many Scorecard checks are based on GitHub repository settings, project age, or external OpenSSF services rather than code in the repository.

Scorecard alerts are visibility aids. Do not describe a dismissed or improved Scorecard finding as a security certification, compliance result, audit opinion, or proof of production readiness.

## Current Metadata-Driven Alerts

| Check | Why it appears | Where to remediate | Expected resolution |
| --- | --- | --- | --- |
| `Maintained` | The repository is less than 90 days old or lacks enough recent maintainer activity. | Project history and maintainer activity. | No immediate source-file fix. Re-run Scorecard after the repository is older than 90 days and has steady commit or maintainer issue activity. |
| `Code-Review` | Recent merged changes do not show approved human reviews, or enforced review behavior is not visible. | Pull-request practice and GitHub branch rules. | Merge future changes through PRs with human approvals. The score improves only after Scorecard can see reviewed merge history or strict branch rules. |
| `Branch-Protection` | `main` is protected but not at the strictest Scorecard tier. | GitHub branch protection or repository rulesets. | Enable stricter rules, then re-run the Scorecard workflow on `main`. |
| `CII-Best-Practices` | No OpenSSF Best Practices badge progress is associated with this Git repository URL. | https://www.bestpractices.dev | Create the project record and work through the badge criteria. Add a badge to docs only after the external status exists. |

## Branch Protection Settings

In GitHub, use either repository rulesets or branch protection for `main`:

- Block force pushes and branch deletion.
- Require pull requests before merging.
- Require at least two approving human reviews when enough maintainers are available.
- Require Code Owners review using `.github/CODEOWNERS`.
- Dismiss stale approvals when new commits are pushed.
- Require approval of the most recent reviewable push.
- Require branches to be up to date before merging.
- Require status checks for CI, security, CodeQL, Docker, and OpenSSF Scorecard once their check names are stable.
- Include administrators.
- Avoid bypass actors unless there is a documented emergency process.

If GitHub plan or maintainer capacity prevents one of these settings, document the reason in a maintainer issue and keep the alert open or dismiss it with a precise GitHub dismissal note.

## Code Review Practice

For non-emergency changes:

- Open a pull request from a branch.
- Request review from a human maintainer or Code Owner.
- Wait for an explicit GitHub review approval before merging.
- Re-request approval after meaningful follow-up commits.
- Avoid merging your own unreviewed administrative changes into `main`.

For a small or single-maintainer project, the practical remediation is to recruit at least one additional reviewer. Until that happens, the alert can remain true even when the local source tree is healthy.

## Maintained Check

The `Maintained` check cannot be fixed by adding a file. Keep normal project activity visible:

- Handle issues and pull requests in public when they do not contain sensitive data.
- Keep dependency and security workflow findings triaged.
- Use release notes and changelog entries for real releases.
- Re-run Scorecard after the repository is older than 90 days.

Do not create artificial commits or issues only to change the score.

## OpenSSF Best Practices Badge

To improve `CII-Best-Practices`:

1. Create or claim the project at https://www.bestpractices.dev.
2. Link the Git repository URL for ReconForge ERP.
3. Complete the criteria using implemented behavior and existing docs.
4. Track any unmet criteria as maintainer issues.
5. Add a README badge only after the external project record exists.

Keep wording conservative. An in-progress, passing, silver, or gold badge is not a legal, compliance, audit, or production-readiness claim.

## Re-Running And Closing Alerts

After repository settings or badge status changes:

1. Run the `OpenSSF Scorecard` workflow manually on `main`.
2. Review the generated SARIF/code-scanning alerts.
3. Close resolved GitHub alerts only after a newer run no longer reports the finding.
4. For findings that remain accurate but accepted, use a GitHub dismissal reason that names the constraint, such as "repository is younger than 90 days" or "single-maintainer project while reviewer recruitment is in progress".

Do not close alerts by claiming a source fix when the remediation was a GitHub setting, project-history change, or external badge update.
