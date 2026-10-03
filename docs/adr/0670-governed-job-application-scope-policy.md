# ADR 0670: Govern durable-job application reads and requeue by exact scope

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1010
- **Scope**: local application facade and its backend-neutral repository boundary

## Context

`GovernedDurableJobApplicationService` already protected job submission and
cancellation, but queue projection and requeue were still available through
the underlying service without the same explicit policy context. A caller
could therefore use a different path for queue visibility or terminal-job
recovery. The worker lifecycle policy in ADR 0669 also requires the application
boundary to bind decisions to the actual object and action.

## Decision

The governed application facade now owns policy-gated `queue_snapshot` and
`requeue` operations in addition to submit and cancel:

1. Authorization is evaluated before repository lookup or mutation.
2. Tenant, workspace, organization, and entity scope must exactly match the
   requested operation; missing or mismatched entity scope fails closed.
3. The evaluated context is derived with the actual durable-job or queue
   object identifier and action, including `read` for queue projection.
4. Requeue performs a second persisted-scope check before delegating to the
   lifecycle service, preventing a policy/request scope from being applied to
   a different stored job.
5. Every application decision is sent through the existing append-only policy
   decision audit path and accepts a caller-supplied request ID.
6. The raw backend-neutral service remains reusable for trusted internal
   infrastructure paths; externally exposed application paths must use the
   governed facade.

## Consequences and boundaries

This closes the local application-facade bypass for queue visibility and
requeue and makes the object/action binding testable. It does not establish
external IAM, distributed revocation or cache invalidation, multi-host worker
coordination, provider behavior, HA/DR, production SLOs, or production
authorization effectiveness. API route adoption and broader application
service inventory remain separate work when those surfaces are in scope.

## Verification

- `python -m pytest -q tests/test_governed_jobs_policy.py tests/test_governed_worker_policy.py`
- `python -m pytest -q tests/test_postgres_durable_jobs.py tests/test_durable_job_application.py tests/test_api_operations.py`
- `python -m ruff check reconforge/application/jobs.py tests/test_governed_jobs_policy.py tests/test_governed_worker_policy.py`
- `python -m mypy reconforge/application/jobs.py`

## Rollback

Revert the E-1010 code, test, manifest, and execution-document changes. The
rollback is additive and does not alter migrations or user data. Do not remove
unrelated user-created untracked files in the working tree.
