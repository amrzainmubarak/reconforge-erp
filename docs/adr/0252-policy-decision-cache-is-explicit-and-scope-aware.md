# ADR 0252: Policy decision caching is explicit and scope-aware

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Provide an opt-in bounded `PolicyDecisionCache` for callers that can pair
policy mutations with invalidation. The key includes every
`PolicyEvaluationContext` field, the required permission, enforcement flags,
and policy version. Only allowed non-delegated decisions may be cached.

## Boundary

Existing API, worker, export, and UI routes remain uncached until each caller
has an explicit invalidation owner. Denials and delegated decisions always
evaluate through the supplied policy evaluator. Tenant/workspace/global
invalidation is explicit and workspace invalidation requires a tenant.

## Reversibility

The module is additive; removing it does not change current authorization
behavior because no existing caller enables it implicitly.
