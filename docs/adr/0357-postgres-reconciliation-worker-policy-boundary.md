# ADR 0357: PostgreSQL reconciliation worker policy boundary

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Add an optional policy context supplier and permission contract
  to `PostgresReconciliationWorkerSettings`. When configured, the worker
  re-evaluates the central policy for each tenant before listing runs and again
  before claiming a run. Only a service-account context whose identity matches
  the worker audit actor and whose scope is exactly the tenant may proceed.
- **Rationale:** The PostgreSQL reconciliation worker is a real execution
  surface, separate from the API submit/cancel routes. It must not read or
  claim tenant work solely because a process has a database connection.
- **Security:** Missing permission, human principal, actor mismatch, scope
  mismatch, and context-supplier failures fail closed before connection access.
  Policy decisions emit sanitized audit metadata; no financial rows are logged.
- **Compatibility:** Existing workers remain unchanged when no supplier is
  configured. The current reconciliation schema is tenant-scoped and has no
  workspace/entity columns, so this slice intentionally enforces tenant-only
  scope and does not invent narrower scope.
- **Limitations:** This is not universal worker/export/UI adoption, dynamic
  revocation during an already-running lease, distributed cache invalidation,
  federation, independent HA/DR, or production IAM assurance.
- **Rollback:** Remove the optional settings and policy supplier from the
  deployment; no schema or data migration is required.
