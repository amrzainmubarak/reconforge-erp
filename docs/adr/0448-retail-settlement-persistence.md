# ADR 0448: Persist local retail settlement evidence

## Context

The experimental `retail.settlement` control produced a deterministic,
digest-bound report but had no durable local storage boundary. Without a
workspace-scoped record and backup mapping, a local operator could not retain
or restore the report as evidence while preserving replay integrity.

## Decision

Add SQLite migration 35 and `SQLiteRetailSettlementRepository`. It stores one
immutable report per workspace and decision digest, requires the existing
`finance_core.manage` permission, binds the row to the outer artifact digest
and nested decision digest, and refuses tampered or status/algorithm-mismatched
rows on read. Update and delete triggers preserve append-only semantics.
The local backup/restore table maps include the new table and restore its
payload without changing the report contract.

## Evidence and boundary

`tests/test_sqlite_retail_settlement.py` covers idempotency, workspace
isolation, tamper refusal, migration gating, and backup/restore replay. This
is local SQLite persistence evidence only. It does not provide a retail API or
Studio surface, live processor authenticity/conformance, settlement finality
or fraud semantics, accounting posting, write-back, PostgreSQL parity, HA/DR,
or production retail operations evidence.
