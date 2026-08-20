# ADR 0284: Expose acquisition PPA evidence only through the PostgreSQL server profile

- **Status:** Accepted (bounded E-333 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

E-332 made the deterministic acquisition purchase-price allocation (PPA)
artifact durable in PostgreSQL. The artifact is intentionally non-posting, but
without an authenticated API it could not be consumed by a controlled server
workflow. The local SQLite service must remain compatible and must not be
silently treated as an enterprise ledger.

## Decision

Add two additive `/api/v1/consolidation-ppa` routes in the explicit PostgreSQL
server profile:

- `POST /api/v1/consolidation-ppa` prepares and persists one artifact.
- `GET /api/v1/consolidation-ppa/{artifact_id}` returns a replay-verified artifact.

Mutation bodies are strict Pydantic models with canonical `Money` values and
`extra="forbid"`. The preparer is always the authenticated principal; the
domain/application service rejects self-approval and malformed financial
values. The route requires `finance_core.manage` for preparation and
`finance_core.read` or `finance_core.manage` for reads. Every operation runs
inside the existing tenant transaction/RLS boundary and uses the PostgreSQL
PPA repository, which recomputes the digest and retains `posted: false`.

## Security and compatibility

The route has no local fallback, no arbitrary connector or provider call, and
no journal/write-back side effect. The existing authorization inventory is
updated with the two permission-bearing routes. Unknown body fields and
unauthenticated/local-mode requests fail closed. Removing the routes is a
reversible code rollback; migration `0060_pg_consolidation_ppa` remains governed
by ADR 0283 and its data-preserving downgrade guard.

## Evidence and limits

Local API contract tests cover authentication, permission shape, actor binding,
typed reconstruction, GET replay, and unknown-field rejection. The underlying
PostgreSQL adapter is live-verified only by the synthetic single-node CI gate
recorded for E-332. This ADR does not claim statutory acquisition accounting,
tax/deferred tax, impairment, legal-book posting, live provider integration,
source write-back, restore, HA/DR, or production readiness.
