# ADR 0475: Expose sanitized durable-job queue health through the API

## Status

Accepted locally; GitHub publication is intentionally deferred by owner policy.

## Context

The durable-job queue already had a backend-neutral health projection and a
local CLI. Authenticated API operators had no equivalent read-only view, while
the PostgreSQL metrics wrapper contained a stale `postgres_pool` lookup that did
not match the configured pooled identity factory.

## Decision

- Add `GET /api/v1/ops/durable-jobs/queue` behind `ops.read`.
- In local mode, require an explicit `tenant_id` query and use SQLite. In
  server mode, derive the tenant only from `X-ReconForge-Tenant`, re-evaluate
  the tenant permission, and use the configured PostgreSQL factory with the
  existing RLS boundary.
- Return only fixed status counts, queue/total depth, lease count, scope, and
  oldest timestamps. Job IDs, idempotency keys, digests, and financial payloads
  are never serialized.
- Repair Metrics to use `get_postgres_identity_factory()` and
  `PostgresTenantBoundary`.

## Evidence and limits

Focused API operations/metrics tests, the authorization inventory, Ruff, and
Mypy pass. This proves a bounded local/server route and removes the stale pool
lookup; it does not prove distributed authorization invalidation, queue HA,
throughput, provider behavior, or production SLOs.

## Rollback

Revert the operations router, authorization-inventory digest update, metrics
wrapper change, focused tests, and documentation. No database migration or
stored data format changes are introduced.
