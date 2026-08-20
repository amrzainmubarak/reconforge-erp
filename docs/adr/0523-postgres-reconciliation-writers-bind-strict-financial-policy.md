# ADR 0523: PostgreSQL reconciliation writers bind strict financial policy

- Status: accepted
- Date: 2026-08-11
- Scope: PostgreSQL reconciliation rule persistence

## Context

The HTTP submission route already requires `strict-financial-input-v2`, but
direct repository callers could create a new PostgreSQL reconciliation run
without a `financial_input_policy` field. The worker intentionally preserves a
legacy reader for rows written by older releases, so an omitted field at a new
write boundary could otherwise be mistaken for historical data.

## Decision

`PostgresReconciliationRepository.create_run` copies the supplied rule and
adds `strict-financial-input-v2` when the field is absent before canonical JSON
encoding and persistence. An explicitly supplied policy is preserved for
validation and idempotency comparison. The worker's missing-field branch is
named and documented as an historical compatibility reader; it is reachable
only for pre-existing rows or deliberately constructed replay fixtures.

## Verification

The repository contract asserts that an omitted policy is persisted as strict
v2. The worker/reconciliation policy tests continue to prove explicit strict
and historical legacy behavior. Ruff, Mypy, and the focused PostgreSQL,
persisted-JSON, and financial-input suites pass.

## Compatibility and rollback

Existing rows are not rewritten. Rows without a policy retain their explicit
legacy replay semantics; new writes cannot create another implicit legacy row.
Revert the writer normalization, named reader helper, test, and execution
records together if compatibility evidence requires it.

## Boundary

This closes the new PostgreSQL repository writer boundary only. It does not
prove live PostgreSQL execution, statutory accounting, source authenticity,
backend parity, HA/DR, or production readiness.
