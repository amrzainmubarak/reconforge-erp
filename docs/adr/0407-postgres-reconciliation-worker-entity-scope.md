# ADR 0407: Add legal-entity scope to PostgreSQL reconciliation workers

- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: ADR 0406 carried workspace scope through the reconciliation
  worker, but the platform's policy model also supports legal-entity scope.
  Leaving runs entity-agnostic would allow a workspace-authorized worker to
  process multiple legal entities without an exact policy decision.
- **Decision**: Add nullable, defaulted `organization_id` and `legal_entity_id`
  attribution to PostgreSQL reconciliation runs through migration
  `0072_pg_recon_entity_scope`. The columns are protected by tenant-safe
  foreign keys, an organization/entity lookup index, and RLS predicates tied
  to `app.organization_id` and `app.legal_entity_id`. Worker discovery reads
  all three hierarchy fields after tenant authorization; claim SQL requires
  the exact workspace, organization, and legal entity (or NULL for legacy
  runs); and every subsequent transaction sets the exact scope. Entity scope
  without workspace and organization scope is rejected before database I/O.
  Existing tenant-only and workspace-only callers remain compatible.
- **Verification**: Static migration contracts prove revision lineage,
  reversible downgrade, FK/index/policy declarations, and source-distribution
  membership. Worker contracts prove exact policy/entity context,
  `app.organization_id` and `app.legal_entity_id` propagation, scoped
  completion, and rejection of an entity-only request.
- **Boundary**: This closes entity scope for one PostgreSQL reconciliation
  worker lane only. Other workers, exports/UI, federation, distributed policy
  invalidation, live providers, HA/DR, high-volume sizing, and production IAM
  remain open.
- **Reversibility**: Downgrade removes only the organization/entity
  attribution columns, index, foreign keys, and entity-aware policy; legacy
  run data remains intact and tenant/workspace behavior is restored.
