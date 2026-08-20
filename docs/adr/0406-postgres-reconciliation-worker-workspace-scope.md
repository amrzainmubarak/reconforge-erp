# ADR 0406: Carry PostgreSQL reconciliation worker workspace scope end to end

- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: The hosted reconciliation worker already used an optional
  service-account policy, but its policy and every transaction were tenant-only.
  The workspace-attribution migration and RLS policy existed, yet a worker
  could not safely claim a workspace-attributed run without carrying that scope
  through discovery, claim, streaming, checkpoints, heartbeats, persistence,
  cancellation, and failure handling.
- **Decision**: Keep the existing one-argument tenant policy supplier for
  legacy/unscoped runs and add an explicit three-argument scope supplier for
  `(tenant_id, workspace_id, entity_id)`. A scoped run requires that supplier,
  an exact central-policy context, and a workspace-scoped
  `PostgresTenantBoundary` transaction for every I/O phase. The worker reads
  `workspace_id` only after tenant policy authorization and verifies any caller
  supplied scope against the persisted attribution. Reconciliation runs do not
  yet carry an authoritative `entity_id`; the worker therefore passes `None`
  and refuses a context that claims another entity.
- **Verification**: Repository contract tests cover workspace attribution
  lookup and worker tests prove exact policy scope, workspace GUC propagation,
  successful scoped completion, and fail-closed rejection of a legacy
  tenant-only supplier. Existing tenant-only worker tests remain green.
- **Boundary**: This closes one PostgreSQL reconciliation-worker scope lane
  only. Scheduler/outbox, export/UI, federation, distributed policy
  invalidation, entity attribution, live hosted PostgreSQL, high-volume
  benchmarks, HA/DR, and production readiness remain open.
- **Reversibility**: Remove the scope supplier, attribution lookup, transaction
  arguments, tests, documentation, and manifest entry without a data rewrite;
  existing tenant-only callers remain source-compatible.
