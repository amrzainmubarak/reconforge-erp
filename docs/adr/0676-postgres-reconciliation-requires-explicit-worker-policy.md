# ADR 0676: PostgreSQL Reconciliation requires an explicit worker policy supplier

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1016
- **Scope**: PostgreSQL Reconciliation worker discovery, claim, and execution

## Context

The shared worker guard preserves a legacy no-op when a hosted worker omits
every policy supplier. That compatibility behavior is unsafe for PostgreSQL
Reconciliation: discovery, claim, heartbeat, and completion are financial
control effects, and an omitted configuration could allow a worker to reach a
database transaction without a service-account decision.

## Decision

`PostgresReconciliationWorker` now fails closed before connection access when
an authorization lane has no policy supplier. The existing tenant, scope,
discovery, claim, and recheck calls all pass through the same fail-closed
boundary. `PostgresReconciliationWorkerSettings` exposes an explicit
`allow_unbound_hosted_policy` compatibility flag, disabled by default. It is
limited to bounded migration/benchmark/legacy fixtures; hosted production
configuration must provide a tenant or exact-scope policy supplier.

The local matcher and persistence contracts are unchanged. No database
schema, reconciliation payload, result format, or matcher API changes.

## Consequences and boundaries

Missing hosted Reconciliation policy can no longer silently become an
authorization no-op. This slice does not prove external IAM, distributed
revocation, provider delivery, HA/DR, production SLOs, or production
readiness. The compatibility flag is an explicit migration aid and is not
evidence of an ungoverned production configuration.

## Verification

- `python -m pytest -q tests/test_postgres_reconciliation.py tests/test_postgres_reconciliation_persisted_json.py tests/test_postgres_grouped_matching_runtime.py`
- `python -m ruff check reconforge/workers/postgres_reconciliation.py reconforge/benchmark/postgres_grouped_matching_scale.py tests/test_postgres_reconciliation.py tests/test_postgres_reconciliation_persisted_json.py tests/test_postgres_grouped_matching_runtime.py`
- `python -m mypy reconforge/workers/postgres_reconciliation.py`
- `python -m pytest -q`
- `python -m build --no-isolation`

## Rollback

Revert E-1016 worker/settings/test/benchmark/manifest/execution-document
changes. The rollback restores the legacy optional policy behavior and does
not alter persisted reconciliation data.
