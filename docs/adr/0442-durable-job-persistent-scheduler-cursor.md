# ADR 0442: Durable-job scheduler cursor is tenant-scoped and lane-digest bound

## Status

Accepted for the bounded execution slice; distributed production scheduling remains open.

## Context

The existing round-robin scheduler keeps its cursor in one process. Restarting
or running a second scheduler therefore resets the sequence and can repeatedly
prefer the first lane. Queue claims are lease-fenced, but lane selection was
not shared state.

## Decision

Add a tenant-scoped `durable_job_scheduler_cursors` record in SQLite migration
34 and PostgreSQL migration `0079_pg_job_cursor`. A scheduler key is bound to
the SHA-256 digest and count of its ordered lane contract. Each reservation
locks or serializes the cursor, returns the current index, and advances the
next index. Reusing a key with a changed lane set fails closed. The persistent
scheduler accepts lanes from one tenant only so the cursor remains compatible
with tenant RLS and service-account scope.

## Evidence and boundary

The SQLite restart contract proves two scheduler instances continue the same
lane sequence and reject lane drift. PostgreSQL schema, RLS, Alembic, grants,
and repository contracts are covered statically; live PostgreSQL execution is
capability-gated. This is bounded shared-cursor coordination evidence, not a
claim of distributed throughput, automatic failover, queue HA, cross-host
fairness SLOs, or production capacity.

## Rollback

Do not reuse a cursor key with a different lane set. A migration downgrade
refuses non-empty PostgreSQL cursor state; SQLite backup/restore includes the
cursor table. Operators may drain the scheduler, export the database, and use
an approved empty-state downgrade only after the cursor rows are removed under
the normal retention and audit procedure.
