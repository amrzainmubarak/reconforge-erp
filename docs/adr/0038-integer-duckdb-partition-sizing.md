# ADR 0038: Integer DuckDB Partition Sizing

- Status: Accepted
- Date: 2026-07-25
- Scope: DuckDB work-order bucket sizing

## Context

The relation-partition path estimated bucket size using two integer counts
converted to binary float, followed by nested ceiling arithmetic. For ordinary
tested dataset sizes this was stable, but counts beyond binary float's exact
integer range could change the ceiling. A reproduced case returned seven
buckets while exact integer arithmetic required eight.

Partition size is an execution/batching choice, not a financial value. It still
belongs to deterministic replay because changing batch composition can alter
memory behavior and which safeguard is reached, even though work-order
partitions are expected to preserve matching decisions.

## Decision

Calculate the same ceiling directly with integers:

```text
ceil(target_rows * work_order_count / total_records)
= (numerator + total_records - 1) // total_records
```

Retain the existing bounds of at least one bucket and no more than the number
of work orders. Preserve the former fallback when record count is no greater
than work-order count by using the configured target before applying bounds.

## Consequences

- Bucket sizing is deterministic for arbitrary Python integer counts and no
  longer depends on IEEE-754 exact-integer range.
- A boundary of 3,000 records/six work orders remains one; 2,999 becomes two.
- The reproduced large case now returns eight instead of seven. This is a
  batching correction, not a scale claim or benchmark result.
- Reconciliation rules, source records, partition keys, decision sorting, and
  output signature formats are unchanged.

## Rollback

Restoring float ceiling arithmetic is unsafe. A future partition heuristic must
be versioned/tested and must preserve decision parity or document a result
migration.
