# ADR 0359: Hosted scheduler and outbox worker policy boundary

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Add an opt-in central-policy guard to the PostgreSQL scheduler
  and transactional-outbox workers. Before opening a tenant connection, a
  configured worker must provide a service-account context whose actor matches
  the worker identity, whose tenant scope matches the lane, and whose
  non-human permission is granted (`schedule.run` or `outbox.publish`).
- **Compatibility:** Existing Community/SQLite and unconfigured PostgreSQL
  workers keep their current constructor and runtime behavior. The guard is
  additive and disabled only when no context supplier is configured.
- **Security:** Denials are fail-closed and occur before repository I/O. The
  central policy decision is audited without raw tenant or financial data.
- **Boundary:** This closes only the two hosted worker entry points. It does
  not prove universal route/export/UI adoption, workspace/entity-aware worker
  scope (the current scheduler/outbox rows are tenant-scoped), revocation
  re-evaluation, federation, distributed invalidation, provider delivery,
  HA/DR, or production IAM effectiveness.
- **Rollback:** Remove the additive settings fields, shared guard, and focused
  tests; existing unconfigured worker behavior remains the compatibility path.
