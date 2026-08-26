# ADR 0674: PostgreSQL Outbox requires an explicit worker policy supplier

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1014
- **Scope**: PostgreSQL Outbox worker publishing boundary

## Context

`require_service_worker_policy` intentionally preserved a legacy no-op when a
worker supplied no policy context. That compatibility behavior was unsafe for
the PostgreSQL Outbox worker: a missing configuration could still claim and
publish events to an external publisher without a service-account decision.

## Decision

`PostgresOutboxWorker` now fails closed before connection access when all policy
suppliers are absent. `OutboxWorkerSettings` exposes an explicit
`allow_unbound_hosted_policy` compatibility flag, disabled by default. It is
only for bounded migration/benchmark/legacy fixtures and is rejected by the
local SQLite `OutboxWorker`; production hosted configuration must provide an
explicit tenant, scope, or hierarchy policy supplier.

The existing policy guard remains provider-neutral and the local Community
worker keeps its existing contract. No database schema, outbox payload, or
publisher API changes.

## Consequences and boundaries

Missing hosted Outbox policy can no longer silently become an authorization
no-op. This slice does not yet change the analogous optional-policy behavior in
PostgreSQL Scheduler or Reconciliation workers; those remain separate slices.
It does not prove external IAM, distributed revocation, provider delivery,
HA/DR, production SLOs, or production readiness.

## Verification

- `python -m pytest -q tests/test_postgres_outbox.py tests/test_postgres_outbox_payload_json.py tests/test_postgres_notifications.py`
- `python -m pytest -q tests/test_outbox_worker.py`
- `python -m ruff check reconforge/workers/outbox.py reconforge/workers/postgres_outbox.py tests/test_postgres_outbox.py tests/test_postgres_outbox_payload_json.py tests/test_postgres_notifications.py reconforge/benchmark/postgres_outbox_scale.py`
- `python -m mypy reconforge/workers/outbox.py reconforge/workers/postgres_outbox.py`

## Rollback

Revert E-1014 worker/settings/test/benchmark/manifest/execution-document
changes. The rollback restores the legacy optional policy behavior and does
not alter persisted outbox data.
