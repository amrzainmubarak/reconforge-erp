# ADR 0372: Bind intercompany evidence to the business period name

- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: PostgreSQL consolidation-close runs store an internal period-row
  identity (`PGCCP-*`) in `run.period_id`, while intercompany source evidence
  stores the accounting period name (for example, `2026-08`). Comparing those
  values rejected valid artifact links.
- **Decision**: Validate intercompany artifact `period_name` values against the
  replay-verified worksheet's business `period_id`, not the internal database
  row identity. Keep the internal identity for relational lookup and scope.
- **Verification**: The isolated PostgreSQL 17.10 runtime passed ownership,
  consolidation-close including intercompany linking/certification/reversal,
  PPA, and deferred-tax contracts 18/18 with the non-privileged role.
- **Boundary**: This fixes the local PostgreSQL evidence-binding invariant. It
  does not establish statutory accounting, hosted CI, live ERP/bank write-back,
  HA/DR, or production readiness.
- **Rollback**: Revert the comparison to the internal identifier only if a
  versioned schema explicitly changes the artifact contract; no data migration
  is required because persisted values remain unchanged.
