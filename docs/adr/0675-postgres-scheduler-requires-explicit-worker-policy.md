# ADR 0675: PostgreSQL Scheduler requires an explicit worker policy supplier

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1015
- **Scope**: PostgreSQL Scheduler worker claim and dispatch boundary

## Context

The shared worker guard preserves a legacy no-op when a hosted worker omits
every policy supplier. That compatibility behavior is unsafe for the
PostgreSQL Scheduler: a missing configuration could enumerate a valid lane,
open a connection, and process due schedules without a service-account
decision.

## Decision

`PostgresSchedulerWorker` now fails closed before connection access when a
lane has no policy supplier. `PostgresSchedulerWorkerSettings` exposes an
explicit `allow_unbound_hosted_policy` compatibility flag, disabled by
default. It is limited to bounded migration/benchmark/legacy fixtures;
hosted production configuration must provide a tenant or exact-scope policy
supplier.

The existing pre-connection and pre-dispatch policy checks remain in place.
The local Community worker contract is unchanged. No database schema,
schedule payload, or dispatch API changes.

## Consequences and boundaries

Missing hosted Scheduler policy can no longer silently become an
authorization no-op. This slice does not change the analogous optional-policy
behavior in PostgreSQL Reconciliation workers; that remains a separate slice.
It does not prove external IAM, distributed revocation, provider delivery,
HA/DR, production SLOs, or production readiness.

## Verification

- `python -m pytest -q tests/test_postgres_scheduler_worker.py tests/test_postgres_notifications.py`
- `python -m ruff check reconforge/workers/postgres_scheduler.py tests/test_postgres_scheduler_worker.py tests/test_postgres_notifications.py`
- `python -m mypy reconforge/workers/postgres_scheduler.py`
- `python -m pytest -q`
- `python -m build --no-isolation`

## Rollback

Revert E-1015 worker/settings/test/manifest/execution-document changes. The
rollback restores the legacy optional policy behavior and does not alter
persisted schedule or dispatch data.
