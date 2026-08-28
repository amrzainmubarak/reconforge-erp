# ADR 0746: Bound policy-decision cache freshness

- Status: Accepted
- Date: 2026-08-28
- Decision owners: identity-governance and security maintainers

## Context

The opt-in policy-decision cache already stored only allowed, non-delegated
decisions and supported explicit scope invalidation plus a shared generation
store. Without an independent age limit, an invalidation omission or an
unavailable policy-change signal could leave an allowed decision reusable for
the life of the bounded in-process cache.

## Decision

Give every cached allowed decision a validated maximum age. The default is 30
seconds, with accepted configuration bounded to 1 through 3,600 seconds. Use a
monotonic clock, remove an entry before reuse when it has reached the TTL, and
inject the clock only for deterministic tests. Keep denials and delegated
evaluations uncached. Retain shared-generation invalidation as the primary
cross-process freshness mechanism and request-time policy evaluation as the
authorization authority.

## Consequences and boundaries

This limits the lifetime of a stale positive cache entry and provides a
defense-in-depth control without changing the default-disabled cache posture.
It may increase policy-engine evaluations after expiry, which is an accepted
security-over-performance tradeoff. TTL does not provide instant revocation,
distributed IAM, cross-process coordination by itself, or production
effectiveness evidence. A failed shared-generation read already bypasses the
cache; deployments must still configure and monitor their shared invalidation
boundary when the cache is enabled.

## Verification and rollback

`tests/test_policy_cache.py` covers boundary expiry, configuration limits,
scope invalidation, shared generation, denial/delegation bypass, and shared
store outage fallback. The full Python regression and release-quality gates
remain required. Rollback is a source-level revert of the cache TTL change,
tests, execution records, manifest entry, and this ADR; no database migration
or persisted-data change is involved.
