# ADR 0390: Expose duplicate detection through Reconciliation-as-Code

- **Date:** 2026-08-06
- **Status:** Accepted
- **Scope:** Reconciliation-as-Code matching adapter selection and golden tests

## Context

ADR 0389 introduced an experimental bounded duplicate-detection strategy, but
it was only addressable through the low-level matching strategy contract. A
control pack author could not select it in a versioned Reconciliation-as-Code
document or verify duplicate evidence in an embedded synthetic test.

## Decision

Extend the v1 Reconciliation-as-Code contract with
`strategy_type: duplicate_detection`, `mode: duplicate-detection`, and the
`bounded-duplicate-detection` strategy identity. The adapter runner dispatches
to the existing strategy without changing its financial semantics. Embedded
expected results gain an additive `duplicate_group_count` field; duplicate
groups are never relabeled as matched records, and ambiguous budget outcomes
remain explicit. Existing strategy types default to zero duplicate groups and
retain their compatibility behavior.

The closed JSON Schema is updated together with the Pydantic contract. A
synthetic golden case proves Decimal-equivalent duplicate amounts, side-scoped
grouping, and deterministic strategy selection.

## Verification

`tests/test_reconciliation_as_code_duplicate_detection.py`, the Phase 2
deliverable suite, and the existing matching contracts pass. The golden RAC
document validates against `docs/schemas/reconciliation_as_code.schema.json`,
executes through the public embedded-test runner, and reports one duplicate
group with zero financial matches. Ruff and Mypy pass on the changed surface.

## Boundary

This is a safe declaration and simulation adapter only. It does not approve,
merge, delete, post, or classify duplicate records as fraud. Provider
connectors, live data, PostgreSQL execution, and production readiness remain
separate gates.

## Reversibility

Remove the additive schema fields, dispatch branch, tests, ADR, and manifest
entry. Existing RAC documents and matching strategies remain readable without
a database migration.
