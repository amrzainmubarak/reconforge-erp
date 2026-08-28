# ADR 0740: PostgreSQL reconciliation workers consume verified permission manifests

- **Status:** Accepted
- **Date:** 2026-08-28
- **Decision owners:** Platform Security / Reconciliation Runtime Governance

## Context

The PostgreSQL reconciliation worker already had central policy re-evaluation,
exact tenant/workspace/entity checks, and separate discovery and execution
permissions. Those controls were configured independently, however. A worker
with a policy supplier could omit the reviewed worker-permission manifest, and
private callers could pass a different permission to the shared policy guard.
That left runtime configuration weaker than the local deployment evidence.

## Decision

When a `PostgresReconciliationWorker` uses a policy context supplier, its
`PostgresReconciliationWorkerSettings` must carry a verified
`WorkerPermissionManifest`. Configuration and every policy boundary enforce:

- `manifest.worker_id == settings.worker_id`;
- `manifest.principal_id == settings.audit_actor_id`;
- `manifest.execution_permission == settings.policy_permission`;
- `manifest.discovery_permission == settings.discovery_authorization_permission`;
- every requested discovery or execution permission belongs to that exact
  manifest grant pair; and
- the dynamic policy context still matches the requested tenant/workspace/
  organization/entity namespace through the existing central policy guard.

The explicit `allow_unbound_hosted_policy` path remains available only for the
existing local compatibility/test boundary when no policy supplier is present.
The backend-neutral local worker and its storage contract are unchanged.

## Security consequences

- Missing manifest configuration fails before a connection is opened.
- Worker and audit-principal drift fails before discovery or claim.
- Discovery permission cannot be substituted with an arbitrary execution or
  administrative permission, and execution cannot be downgraded or replaced
  per call.
- Central dynamic policy and PostgreSQL RLS remain the authorities for current
  namespace grants; the manifest does not replace revocation or IAM checks.

## Boundaries

This is local synthetic evidence for the PostgreSQL reconciliation worker
configuration and policy boundary. It does not provision service accounts,
query an external identity provider, prove all worker deployments use the
setting, provide distributed revocation, or establish provider/HA/DR or
production authorization assurance.

## Compatibility and rollback

The stricter requirement applies only when a PostgreSQL reconciliation worker
configures a policy supplier. The raw local worker and explicit unbound local
compatibility path remain unchanged. No schema or migration is needed. Roll
back the E-1080 code, tests, manifest entry, and execution records together;
do not reintroduce unbound policy-permission substitution without a replacement
artifact binding.

## Verification

- `python -m pytest tests/test_postgres_reconciliation.py -q --tb=short`
  -> passes with one declared capability skip.
- Full Python/static/security/package/YAML/diff gates are required for E-1080.
