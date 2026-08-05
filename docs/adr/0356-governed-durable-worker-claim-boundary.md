# ADR 0356: Governed durable-worker claim boundary

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Add an explicit `GovernedDurableJobWorkerService` facade around
  the backend-neutral durable-job worker. The facade must evaluate the central
  policy before claiming a lane, require a `service_account` principal whose
  identity equals `worker_id`, and require exact tenant/workspace/entity scope
  agreement before the repository is touched.
- **Rationale:** API mutation routes already re-evaluate server policy, but a
  worker process can otherwise call the lease primitive directly. A fail-closed
  claim boundary makes worker authorization an explicit adoption choice without
  changing existing local/community worker compatibility.
- **Security:** Missing permissions, human principals, identity mismatch, and
  sibling tenant/workspace/entity scopes deny before claim. Decisions emit only
  sanitized policy audit metadata. Lease fencing remains the persistence guard.
- **Compatibility:** The existing `DurableJobWorkerService` API is unchanged;
  deployments opt into the governed facade and choose the non-human permission
  contract appropriate to the job (for example `match.run`).
- **Limitations:** This slice does not migrate every worker, export, or UI
  caller, and it does not provide distributed cache invalidation, provider
  federation, HA/DR, or production IAM assurance. Deployments must re-evaluate
  at their claim boundary after policy changes.
- **Rollback:** Stop using the facade and retain the existing worker service;
  no schema or data migration is required.
