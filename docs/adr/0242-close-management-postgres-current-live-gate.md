# ADR 0242: Promote Close Management after a current PostgreSQL runtime gate

- Status: accepted
- Date: 2026-08-02

## Decision

Classify `CloseManagementApplicationService` as `live_verified_current` after
the CI non-privileged PostgreSQL runtime contract passes for period/task/
dependency lifecycle, readiness, lock/reopen, audit/outbox evidence, and
tenant isolation. Record the gate separately from the historical broad parity
gate and keep its single-node limitations explicit.

## Boundary

This promotes Close Management lifecycle parity only. It does not promote the
absent `ConsolidationCloseApplicationService`, nor prove consolidation journal
posting, eliminations/NCI, statements, restore, HA/DR, or RPO/RTO.

## Rollback

Restore the inventory row to `live_test_available` and remove this gate,
tests/docs, without changing runtime code or external state.
