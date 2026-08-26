# ADR 0669: Re-evaluate governed worker policy at every lifecycle boundary

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution track
- **Related execution task:** E-1008

## Context

`GovernedDurableJobWorkerService` already evaluated a service-account policy
before claiming a durable job. The underlying lease worker then allowed the
same claimed lease to heartbeat, checkpoint, read prior effects, commit an
effect, complete, retry, fail, pause, or cancel without a new policy context.
That created a revocation window: a permission change after claim could leave a
worker able to extend or finalize work until the lease expired. The claim also
allowed a context with no entity identifier to accompany an entity-scoped lane,
which was weaker than the hierarchy contract used by the newer worker lanes.

## Decision

Keep the backend-neutral `DurableJobWorkerService` reusable for local callers,
and make `GovernedDurableJobWorkerService` the explicit server/service-account
facade for governed execution. Require `PolicyEvaluationContext` and the
required permission on every governed lifecycle method:

- claim;
- partition-effect reads;
- heartbeat;
- checkpoint;
- partition-effect commit;
- completion and final partition completion;
- retry;
- failure;
- pause; and
- cancellation.

Before delegation, the facade must verify exact equality of the context and
requested tenant, workspace, organization, and entity scope. Entity omission is
therefore denied for an entity-scoped job. For post-claim operations, the
facade derives a bound context with the actual durable-job ID and lifecycle
action; callers cannot substitute a different object in the auditable policy
evidence. The decision is then sent to the existing closed
`audit_policy_decision` path before repository access.

## Consequences

Positive consequences:

- Permission revocation is observed at each governed boundary rather than only
  at claim time.
- Lease renewal and financial-effect completion fail closed before repository
  mutation when the fresh context is denied.
- Policy evidence identifies the durable job and lifecycle action that were
  actually evaluated.
- The signature regression test makes omission of the explicit policy inputs
  visible when a future lifecycle wrapper is added.
- Community/local callers retain the existing ungoverned primitive and are not
  silently upgraded to an unavailable hosted IAM dependency.

Remaining boundaries:

- The context is supplied by the hosting caller; this does not authenticate an
  external IdP or provision service-account permissions.
- Revocation coordination is only as fresh as the supplied policy context and
  the configured local policy source; distributed cache invalidation remains a
  separate gate.
- The tests use local SQLite and synthetic jobs. They do not prove multi-host
  coordination, provider behavior, HA/DR, production SLOs, or production IAM
  effectiveness.

## Verification

- `python -m pytest -q tests/test_governed_worker_policy.py tests/test_durable_job_application.py tests/test_governed_jobs_policy.py`
- `python -m ruff check reconforge/application/jobs.py tests/test_governed_worker_policy.py`
- `python -m mypy reconforge/application/jobs.py`
- `git diff --check`

The focused worker/application tests pass, and the static checks pass on the
current tree.

## Rollback

Revert the E-1008 application/test changes, remove this ADR and its manifest
entry, and remove the E-1008 entries from `BACKLOG.yaml`, `STATE.md`,
`EVIDENCE.md`, and `CLAIMS_EVIDENCE_MATRIX.md`. This returns the governed facade
to claim-only policy evaluation while leaving the backend-neutral worker
primitive and existing API policy contracts unchanged. Rollback must not remove
historical evidence or user-created untracked execution files.
