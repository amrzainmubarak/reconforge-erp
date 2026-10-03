# ADR 0785: Remediate October disclosures in locked dependencies

- Status: Accepted
- Date: 2026-10-03
- Owners: Supply Chain

## Context

The reproducible October baseline reported Python findings in urllib3 2.7.0 and
virtualenv 21.7.0, and npm findings in development dependencies. Historical clean
audits did not describe current advisories.

## Decision

Advance the explicit resolution cutoff to 2026-10-03T00:00:00Z. Upgrade urllib3 to
2.8.0, virtualenv to 21.14.5 and its required python-discovery to 1.6.1.
Update the Vitest family to 4.1.11 and undici to 7.30.0 within current package
constraints; retain the resulting reviewed test dependency lock tree and integrity
hashes. Keep uv pinned to 0.11.32 and preserve the pre-fix findings.

The virtualenv choice accounts for disclosures newer than the oldest fixed floor:
[official changelog](https://virtualenv.pypa.io/en/latest/changelog.html).
Lockfile audits, all-extra environments and application compatibility checks are
required evidence; an audit result is bounded by its database and execution date.

## Verification and rollback

The isolated locked audits for the Python 3.11 and 3.12 profiles report zero known
findings; the unpublished project itself has no PyPI advisory result. Both full
and production-only npm audits report zero findings. Supply-chain policy and
dependency contracts pass. Application regression/build results are recorded
separately in execution evidence.

Rollback requires restoring both manifest/cutoff and corresponding lock files.
Doing so reintroduces the baseline disclosures; do not label an old lock secure.
