# ADR0868: Await the existing error-focus effect in component tests

Date: 2026-10-18
Status: accepted

## Context

PR141's documentation head4ff88aff passes the Python, Security, Docker and
CodeQL checks, but CI39109318110's web job fails one of1111 component cases.
The retry button and alert exist before React's existing passive effect focuses
the alert. The test immediately asserts focus after finding the retry button.
The same immediate assertion occurs in the adjacent conflict and aging cases.
This is an observation-order race, not evidence to remove the accessibility
requirement. Both files already contain local edits when this review starts;
their originals and a binary patch are preserved before validation.

## Decision

Use the existing Testing Library `waitFor` around the three focus assertions.
Retain the exact alert, focus, privacy, command-body and human-retry expectations.
Do not change the component effect, global timeout, runner retry count or any
financial or authorization behavior. This waits for the existing effect within
the existing assertion deadline; it does not rerun failed test cases.

Keep all work in the primary checkout. PR141 is retargeted from its integration
parent to main at the user's explicit request. Integrate current main into this
branch before the final CI candidate; the preliminary merge-tree check has no
conflict and produces the same tracked file tree as the existing candidate.
Use a merge commit when accepting the PR to retain the integrated history.
Merge only when the final candidate's actual required checks pass, with no
administrative bypass, and fast-forward the local main afterward.

## Evidence and rollback

The original failed hosted log and preexisting local edits are retained under
`output/pr141-merge-review`. The two component files pass33 cases in12.26s and
TypeScript checking and production build pass. The complete component suite
passes1111 cases across103 files in98.05s, without rerunning a failed case.
Final candidate CI evidence is retained separately; earlier099d evidence is not
relabeled as a later-head run.
Revert only these three assertion waits to restore the earlier test behavior;
there is no application or data migration.
