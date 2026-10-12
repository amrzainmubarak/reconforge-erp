# ADR 0741: PostgreSQL scheduler workers consume verified permission manifests

- **Status:** Accepted
- **Date:** 2026-08-28
- **Decision owners:** Platform Security / Scheduling Runtime Governance

## Context

`PostgresSchedulerWorker` already performed a policy check before opening a
database connection and re-evaluated policy immediately before dispatch. Both
checks used the same independently configured permission, though, and the
worker identity was not bound to the offline permission manifest. This left
lane discovery and dispatch configuration weaker than the reviewed evidence.

## Decision

When a scheduler worker configures a policy supplier,
`PostgresSchedulerWorkerSettings` must include a verified
`WorkerPermissionManifest`. The settings bind:

- the manifest worker ID to `settings.worker_id`;
- the manifest principal ID to `settings.audit_actor_id`;
- the manifest discovery permission to the explicit
  `discovery_policy_permission`; and
- the manifest execution permission to `policy_permission`.

The first policy decision for each lane uses the discovery permission before
connection access. The second decision uses the execution permission before
dispatch. Both decisions retain the existing service-account, scope, central
policy, and RLS boundaries.

## Security consequences

- A missing manifest or configuration drift fails before a connection opens.
- A scheduler cannot replace the reviewed discovery or execution grant with an
  arbitrary permission through settings.
- Revocation remains checked at the dispatch boundary, and lane scope remains
  checked dynamically by the central policy helper.
- The explicit unbound local compatibility mode remains unchanged when no
  policy supplier is configured.

## Boundaries

This is local synthetic evidence for scheduler configuration and policy
composition. It does not provision service accounts, query an external IdP,
prove all scheduler deployments use the setting, provide distributed
revocation, or establish provider, HA/DR, or production authorization
assurance.

## Compatibility and rollback

The stricter contract applies only to policy-supplier-backed PostgreSQL
scheduler workers. No database schema or migration changes. Revert E-1081,
this ADR, the manifest entry, tests, and execution records together if a
replacement binding contract is required.

## Verification

- `python -m pytest tests/test_postgres_scheduler_worker.py -q --tb=short`
  -> 10 passed.
- Full Python/static/security/package/YAML/diff gates are required for E-1081.
