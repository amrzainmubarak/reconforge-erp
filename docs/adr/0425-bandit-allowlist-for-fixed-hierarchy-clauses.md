# ADR 0425: Document fixed hierarchy SQL clauses for Bandit

- **Status**: accepted
- **Date**: 2026-08-07
- **Scope**: PostgreSQL PPA, impairment, and deferred-tax repositories

## Context

Bandit B608 flagged string composition in eight scoped reads. The dynamic
portion is the repository's private `_scope_where()` result, selected only from
fixed hierarchy-column clauses; all identifiers are internal and all external
values remain `%s` parameters. The scanner cannot infer that contract.

## Decision

Add line-level `# nosec B608` annotations with an explicit rationale on those
eight calls. Do not disable B608 globally, add user-controlled SQL, or weaken
parameter binding. Future changes to `_scope_where()` must keep the fixed
allowlist contract and retain focused scope tests.

## Verification and boundary

Full Bandit over `reconforge` reports no failed findings (existing reviewed
`nosec` warnings remain informational); Ruff, Mypy, focused repository/security
tests, and the existing full regression remain green. This is scanner-coverage
evidence, not independent penetration testing or production security
assurance.
