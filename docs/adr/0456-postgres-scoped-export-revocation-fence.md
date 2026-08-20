# ADR 0456: Recheck scoped-export policy before object publication

- **Status:** Accepted
- **Date:** 2026-08-09
- **Decision owners:** ReconForge maintainers

## Context

The PostgreSQL scoped-export publisher already authorizes the requested
tenant/workspace/entity before taking a snapshot. A permission can be revoked
while the bounded snapshot is being serialized, however, leaving a stale
authorization decision immediately before the object-store write.

## Decision

Keep the initial hierarchy and permission check, and optionally re-evaluate a
fresh `PolicyEvaluationContext` immediately before the external object-store
write. A denied or invalid recheck stops publication and writes no artifact.
The publisher does not attempt a second check after a successful object-store
effect because a completed external write cannot be safely undone and a retry
could create a duplicate side effect.

The recheck is opt-in through `policy_context_supplier` so existing callers
remain compatible. Deployments with a revocation-aware policy source must use
the supplier; a static context is intentionally not represented as distributed
cache-invalidation evidence.

## Consequences

- The last safe authorization window before publication is covered by a
  deterministic failure-injection regression.
- Snapshot work may complete without publication when a revocation occurs;
  this is the fail-closed behavior.
- Distributed policy-cache invalidation, live object storage, PostgreSQL
  runtime, provider semantics, HA/DR, and production IAM remain unproven.
