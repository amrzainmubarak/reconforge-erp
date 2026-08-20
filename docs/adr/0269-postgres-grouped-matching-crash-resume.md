# ADR 0269: PostgreSQL grouped matching crash resume

## Status

Accepted as a bounded live failure-recovery evidence slice.

## Context

The grouped PostgreSQL worker already persists each partition atomically and
skips completed checkpoint keys. Local contracts covered an unhandled process
crash, but the live grouped runtime gate only exercised one partition and did
not prove lease fencing or restart behavior against PostgreSQL.

## Decision

Keep crash recovery at the existing worker boundary:

- do not catch `BaseException` as a normal matcher failure; an interrupted
  process leaves the run `Running` with its lease and preserves committed
  checkpoints;
- reject a replacement worker while the original lease is still valid;
- allow reclaim only after the database lease expires;
- reload checkpoint keys before matching and require the adapter to emit only
  uncommitted partitions;
- keep checkpoint, result, audit, and outbox writes in the existing atomic
  transaction, with no duplicate result identity after recovery.

Add a live server-boundaries contract with two synthetic entity partitions,
one-to-many grouped matching, a deliberate unhandled process-crash exception,
lease-expiry takeover, non-superuser RLS, and exact result/checkpoint
cardinality assertions.

## Boundary

This proves one small PostgreSQL crash/resume path for grouped matching. It does
not prove automatic process supervision, multi-host failover, queue HA, soak,
capacity, production RPO/RTO, live ERP/bank data, posting, or write-back.

## Rollback

Remove the live contract, ADR, and execution evidence. No migration, schema,
production data, provider call, or deployment change is required.
