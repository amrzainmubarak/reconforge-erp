# ADR 0304: Use a Redis generation for explicit policy-cache invalidation

- Status: accepted
- Date: 2026-08-04
- Scope: `P4-IAM-001`

## Decision

When the API explicitly enables the policy decision cache and configures the
optional Redis server profile, each process includes a Redis-backed monotonic
generation in its local cache key. A non-safe HTTP request increments the
generation and clears the local entries. Other processes observe the new
generation on their next authorization evaluation, without storing policy
decisions or credentials in Redis.

If the generation service cannot be read, authorization is evaluated directly
and the local cache is not used. If an invalidation increment cannot be
completed, the local cache is still cleared; operators must treat the shared
invalidation boundary as degraded and keep the cache disabled until Redis is
healthy again.

## Rationale

The existing cache was deliberately process-local. That is safe only when all
mutations invalidate the same process. A shared generation gives explicitly
configured multi-worker deployments a small, inspectable cross-process
invalidation contract while preserving the local-first default and keeping
authorization decisions out of the shared store.

## Evidence boundary

Unit contracts prove independent cache instances stop reusing an allowed
decision after a generation bump and bypass caching during a version-store
failure. The live Redis server-boundary test proves two clients observe atomic
generation changes and cleans up its synthetic key. This is not a complete
distributed policy service: global invalidation is intentionally coarse,
Redis replication/failover and outage recovery are not measured, and route,
job, export, UI, federation, and provider policy coverage remain separate
gates.

## Rollback

Remove `RedisPolicyCacheVersionStore`, the cache version-store hook, tests, ADR,
and execution records. The existing process-local opt-in cache and local-first
default remain unchanged.
