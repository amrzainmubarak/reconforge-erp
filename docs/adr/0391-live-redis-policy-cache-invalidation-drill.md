# ADR 0391: Live Redis policy-cache invalidation drill

- **Date:** 2026-08-06
- **Status:** Accepted
- **Scope:** Optional Redis-backed policy-decision cache generation and live
  single-node verification

## Context

The policy decision cache is opt-in and caches allowed, non-delegated decisions
only. A shared generation store is intended to make a global policy mutation
invalidate local entries in other worker processes. Unit tests covered the
protocol with an in-memory version store, while the existing Redis drill only
proved that two clients could observe an integer generation.

## Decision

Extend the disposable live Redis drill to construct two independent
`PolicyDecisionCache` instances backed by separate Redis connection factories.
The drill evaluates a synthetic allowed context in both caches, confirms a
repeat in the second cache is local-cache served, calls global invalidation in
the first cache, and confirms the second cache evaluates again after the shared
generation advances. The synthetic evaluator exposes only call counts; Redis
stores the generation integer and no authorization decision or identity data.

The report adds the observed
`policy_cache_cross_process_invalidation` boolean. Historical v1 reports that
predate this observation remain readable; newly generated reports must include
the invariant and set it to true.

## Verification

The live script passed against the local `redis:7-alpine` image digest
`sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`.
The current report records tenant isolation, hashed-token storage, shared
generation, cross-process cache invalidation, and cleanup as true, with report
digest `b7f35cc2e9741cf06587f951a57048f3b5f454e51b558e1e52dc41284d48091e`.
Focused Redis/policy tests pass; full local gates are recorded separately as
E-504.

## Boundary

This is bounded single-node synthetic evidence for the optional cache
optimization. It does not prove Redis replication, Sentinel/Cluster failover,
durability, cross-site recovery, complete route/job/export adoption, identity
federation, or production IAM assurance.

## Reversibility

Remove the live drill branch, report field/schema compatibility, tests/docs,
and this ADR. No database migration or persisted application-data change is
required.
