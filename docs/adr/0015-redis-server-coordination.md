# ADR 0015: Optional Redis Server Coordination Boundary

- Status: Accepted as a foundation; application integration pending
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The local API currently stores sessions in SQLite and throttles failed logins in
process memory. Those choices are appropriate for the local edition but are not
safe coordination primitives for multiple API or worker processes.

## Decision

Add `redis-py` to the optional `server` dependency group and lazy-load it through
`RedisConnectionFactory`. TLS is required by default (`rediss://`); disabling it
is an explicit local-development choice. Redis connection settings redact the
URL from representations and configure bounded socket and health-check timeouts.

`TenantRedisStore` provides:

- Session metadata stored under tenant-prefixed keys with TTLs. Only a token
  digest may be stored; raw bearer tokens are not accepted.
- Session and token revocation markers with expiry.
- Atomic Lua rate-limit increments whose expiry is set only on the first write.
- Expiring tenant-scoped locks with compare-and-delete release, preventing one
  worker from releasing another worker's lock.
- A health check that does not expose connection details.

Subjects and lock names are hashed before becoming key components. Tenant IDs
use the same conservative validation as the PostgreSQL boundary. A tenant is
therefore part of every session, revocation, rate-limit, and lock key.

## Consequences

- The local SQLite session and in-process throttling behavior remains unchanged.
- The adapter is ready for explicit server-profile integration but is not
  silently activated by importing the package.
- API authentication, background workers, session rotation, lock recovery, and
  outage behavior must be integrated and tested before claiming multi-worker or
  hosted readiness.
- Redis persistence/availability policy, encryption at rest, and operational
  failover remain deployment responsibilities.

## Rejected alternatives

- Process-local dictionaries for multi-worker rate limits: state diverges across
  workers.
- Storing raw session tokens in Redis: unnecessary exposure if digests are used.
- Unconditional `DEL` for locks: a timed-out owner could delete a lock acquired
  by a newer worker.
