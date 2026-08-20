# ADR 0524: PostgreSQL reconciliation writers reject legacy financial policy

- Status: accepted
- Date: 2026-08-11
- Scope: PostgreSQL reconciliation rule creation

## Context

ADR 0523 made omitted policy metadata strict at the PostgreSQL repository
writer, but an explicit legacy or unknown policy could still reach the low-level
writer. The HTTP route already rejects both cases. Allowing a direct caller to
create a new legacy run would leave two inconsistent write contracts.

## Decision

`PostgresReconciliationRepository.create_run` validates the policy before any
idempotency lookup or database statement. It accepts only
`strict-financial-input-v2`; omitted policy is normalized to that value, while
legacy and unsupported policies fail with a validation error. Historical rows
without a policy remain readable only through the explicitly named worker
compatibility reader.

## Verification

Parameterized repository tests prove legacy and unknown policies fail before
the fake connection records a statement. The strict-default, reconciliation
policy, persisted-JSON, Ruff, and Mypy gates pass; the full local regression
and package/security gates remain required for the final slice record.

## Compatibility and rollback

This tightens only new PostgreSQL writes. It does not rewrite or reject old
rows during reads and does not change SQLite behavior. Revert the writer
validation, tests, ADR, and E-714 records together if a separately approved
legacy creation migration is needed.

## Boundary

This is a local writer contract. It does not establish live PostgreSQL,
statutory accounting, source authenticity, backend parity, HA/DR, or
production readiness.
