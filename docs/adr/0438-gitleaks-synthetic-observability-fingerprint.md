# ADR 0438: Suppress one exact synthetic observability fixture fingerprint

- Status: accepted
- Date: 2026-08-07
- Scope: `P0-SEC-008`, `release_operations`

## Context

The checksum-verified Gitleaks 8.30.1 history scan identified the literal
`SECRET-FAIL-JOB-ID`, `REDACTED` observability test fixture as
`generic-api-key`. The fixture is deliberately synthetic and the test asserts
that its identifiers never appear in telemetry output. No credential,
provider token, or customer data is present.

## Decision

Keep the fixture because it tests sensitive-identifier redaction, and suppress
only the exact historical commit/path/rule/line fingerprint plus its exact
checked-tree counterpart in `.gitleaksignore`. Do not add a rule, path,
commit-range, regex, or broad baseline allowlist.

## Evidence boundary

Gitleaks 8.30.1 history scanning exits clean after the exact fingerprint is
recorded. A clean `git archive` checkout scan exits clean as well. The local
workspace scan is not used as release evidence when generated environments
cause it to exceed the scanner timeout; the CI checkout contains no such
generated environment. Hosted security execution remains separate evidence.

## Rollback

Remove the two exact fingerprints and this ADR, then either rename the
synthetic fixture or accept the scanner finding for a reviewed remediation.
