# ADR 0408: Carry workspace/entity scope through PostgreSQL scheduler workers

- **Date**: 2026-08-06
- **Status**: Accepted
- **Context**: The PostgreSQL scheduler persisted workspace and generic entity
  attribution on schedule versions, but its polling worker authorized only a
  tenant and then evaluated every due schedule in that tenant. A configured
  service identity could therefore widen a scheduled lane beyond its exact
  policy scope.
- **Decision**: Add an optional deterministic scope-lane supplier returning
  `(tenant_id, workspace_id, entity_id)` tuples and an explicit three-argument
  worker policy supplier. Scoped lanes require workspace when an entity is
  supplied, authorize before opening a connection, and pass the same filters
  into `SchedulerApplicationService` and `PostgresScheduleRepository`. The
  repository applies the workspace/entity predicates in the row-lock query
  and restores the same session scope for all dispatch, durable-job, and
  notification writes. Existing tenant-only polling remains source-compatible.
- **Verification**: Worker contracts prove exact policy context, stable lane
  ordering, pre-connection rejection, and scope propagation. Repository and
  application contracts retain the existing deterministic claim/evaluation
  behavior; the live PostgreSQL schedule/RLS test remains capability-gated.
- **Boundary**: This closes scoped authorization for one scheduler lane. The
  transactional outbox remains tenant-only in this slice; universal worker,
  export/UI, federation, distributed invalidation, live provider, scale,
  HA/DR, and production IAM assurance remain open.
- **Reversibility**: Remove the optional lane supplier, policy supplier,
  filter arguments, tests, ADR, and manifest entry; tenant-only scheduling
  behavior and stored schedule rows remain unchanged.
