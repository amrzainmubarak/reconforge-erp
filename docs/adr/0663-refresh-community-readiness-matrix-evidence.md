# ADR 0663: Refresh the readiness matrix with current Community Compose evidence

- Status: Accepted
- Date: 2026-08-26
- Owners: Platform / DevSecOps

## Context

The mode-specific readiness matrix was last reviewed on 2026-08-23. E-968
subsequently added a checked-in Community Compose profile with a live local
SQLite smoke, but the centralized matrix did not identify that current
deployment surface.

## Decision

Refresh the matrix review date to 2026-08-26 and add the Compose artifact,
contract test, and E-968 ADR to the Community
`external_dependency_boundary` gate only. Keep Community readiness partial and
keep Team, Enterprise, and Regulated gates unchanged. The gate boundary must
continue to say that local Compose evidence is not host-firewall,
backup/restore, HA/DR, or production evidence.

## Consequences and rollback

Operators can find the current Community deployment evidence from the central
readiness reader without inferring that other editions are ready. The matrix
digest changes because its reviewed date and evidence references change; any
consumer must recompute the digest rather than reuse a stale value. Rollback
is a metadata/test/ADR revert with no database or deployment-state mutation.
