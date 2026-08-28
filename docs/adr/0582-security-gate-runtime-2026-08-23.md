# ADR 0582: Current static security gate runtime

## Status

Accepted — 2026-08-23

## Decision

Keep the managed-key CLI's `secret_material_present` field as an explicit
Boolean evidence flag and annotate the intentional Bandit B105 false-positive
boundary. Re-run Bandit, local pip-audit, and focused deployment/security tests
as one current gate.

## Limits

Bandit and pip-audit are static/dependency checks. The local project package is
not published on PyPI and is therefore not audited by pip-audit; no claim of
complete reachability, malware, license, hosted CI, penetration testing, or
production security assurance follows.
