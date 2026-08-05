# ADR 0335: Activate the tenant/workspace Finance Core server adapter

## Status

Accepted — 2026-08-05.

## Context

The server API already had a complete forced-RLS PostgreSQL Finance Core
repository, but several `/api/v1/finance-core` collections still returned a
bounded `501` response or used the older posted-ledger adapter. That left
charts, account hierarchy, dimensions, journals, and draft/validated/voided
entry lifecycle unavailable through the authenticated workspace boundary.

## Decision

Add a request-scoped `server_finance_core` executor. It carries the
authenticated tenant/workspace/organization/entity hierarchy through
`PostgresTenantBoundary` and constructs `PostgresFinanceCoreRepository` only
inside that transaction. The routes re-evaluate `finance_core.read`,
`finance_core.manage`, or `finance_core.validate` immediately before adapter
access and reject sibling-workspace payloads.

The richer adapter is used for chart/account/dimension/journal/snapshot
operations and for entries that explicitly carry entity, period, and journal
references. The older posted-ledger path remains available for its existing
minimal server contract, preserving backward compatibility while callers
migrate to the governed Finance Core contract. New Finance Core entry IDs are
distinguished by the existing `GLE-` deterministic identity so validation and
void operations cannot accidentally target a legacy posted entry.

## Consequences

This closes an authenticated API and workspace-isolation boundary; it does not
claim statutory consolidation, legal-book posting, live ERP/bank connectors,
write-back, throughput, HA/DR, or production readiness. A PostgreSQL schema
and non-privileged application role are still deployment prerequisites.

## Rollback

Unset `app.state.postgres_finance_core_factory` for a deployment that must keep
the legacy bounded server-ledger surface. The additive repository and route
executor can then be removed in a subsequent migration after all clients have
returned to the legacy contract.
