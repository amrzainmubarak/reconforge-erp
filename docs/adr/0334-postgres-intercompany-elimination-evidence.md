# ADR 0334: PostgreSQL intercompany elimination evidence is replay-verified and non-posting

- Status: accepted
- Date: 2026-08-05

## Decision

The server profile exposes `POST /api/v1/consolidation-intercompany-eliminations`
and a tenant/workspace-scoped read endpoint. The API computes the deterministic
proposal from typed source lines; callers cannot submit a precomputed result.
The PostgreSQL adapter stores the exact source request and result JSONB payloads,
request/result digests, authenticated preparer, workspace, and audit event in a
forced-RLS immutable table. Reads replay the result against the persisted source
lines and fail closed on any digest or payload mismatch.

The artifact is explicitly non-posting. It does not infer accounts, perform FX,
apply tolerances, approve a journal, or write to a statutory ledger. Any future
posting path requires an independent maker/checker control and a separate ADR.

## Evidence boundary

The local schema/API contracts and focused tests prove strict ingress, replay,
idempotent artifact identity, tenant/workspace isolation at the server boundary,
and append-only database behavior. Hosted CI must exercise the live PostgreSQL
adapter before this row is promoted beyond `live_test_available`. This does not
prove statutory consolidation, provider write-back, HA/DR, throughput, or
production readiness.

## Rollback

Revert the API/adapter and migration in a controlled downgrade. The downgrade
refuses to discard any stored artifacts; an operator must first make an explicit
data-retention decision outside this change.
