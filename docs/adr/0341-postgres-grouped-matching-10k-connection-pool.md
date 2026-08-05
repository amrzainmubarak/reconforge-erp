# ADR 0341: Bound PostgreSQL connection reuse for grouped-matching scale

- Status: accepted
- Date: 2026-08-05
- Scope: `P4-MAT-001`, `P4-SCL-001`

## Decision

Add a small `PostgresConnectionPool` adapter around the existing connection
factory. The pool has an explicit maximum size and acquisition timeout,
returns connections to the pool when the tenant boundary calls `close`,
performs a defensive rollback before reuse, and closes idle/returned
connections after `close()`. It does not change the transaction-local RLS
scope contract or introduce an external pooling dependency.

Use the pool in the bounded PostgreSQL grouped-matching scale harness and add
`postgres-grouped-matching/10k-partitions-v1`: 16 worker tasks, 1,000 runs,
10 partitions per run, five synthetic modes, 24,000 expected result rows.

## Rationale

The first 10K probe failed closed after Windows ephemeral-port exhaustion
because each worker phase opened a fresh TCP connection. A bounded pool keeps
the resource ceiling explicit and makes connection reuse testable without
silently weakening tenant isolation or changing application transaction
boundaries.

## Evidence boundary

The local 10K result is a one-host synthetic correctness/concurrency run. It
does not establish throughput, capacity, soak, cross-host fairness, queue HA,
automatic failover, host-loss recovery, provider interoperability, statutory
posting, write-back, or production sizing.

## Rollback

Remove `PostgresConnectionPool`, its foundation tests, the 10K profile/test,
artifact, benchmark note, workflow selector, ADR, manifest entries, and
execution records. Existing unpooled PostgreSQL boundaries and the 500-
partition grouped-matching gate remain unchanged.
