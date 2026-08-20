# ADR 0423: Bound PostgreSQL server-profile connection reuse

- **Status**: accepted
- **Date**: 2026-08-07
- **Scope**: server-profile API PostgreSQL factory and high-volume request boundaries

## Context

Request-scoped PostgreSQL boundaries correctly close each leased connection,
but a direct factory opens a new physical connection for every request. Under
many concurrent partitions or API calls that can churn sockets and exhaust a
host's ephemeral-port budget even when each transaction is short.

## Decision

Use `PostgresPooledConnectionFactory` for `create_api_app` server profiles.
It subclasses the existing factory to preserve capability checks, leases
through the dependency-free `PostgresConnectionPool`, retains rollback-on-
release and transaction-local RLS settings, and registers an application
shutdown handler. Pool size and acquire timeout are explicit factory arguments
(`8` and `30` seconds by default); callers can choose a smaller bound or `1`
for effectively unpooled operation.

The pool is a resource bound, not a throughput promise. It does not change
transaction semantics, make a worker distributed, or provide HA, failover, or
capacity evidence.

## Verification and rollback

Foundation and API contracts prove reuse, bounded configuration, subtype
compatibility, shutdown registration, and no regression in local behavior.
The local full gate remains required after this slice. Revert the factory,
app wiring, tests, and ADR to return to direct per-request connections; no
database or external service is mutated by this decision.
