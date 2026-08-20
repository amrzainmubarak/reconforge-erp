# ADR-0521: Persist currency-registry snapshots for workspace replay

## Status

Accepted — additive historical snapshot storage and automatic operation-context
selection; configured live PostgreSQL execution and production assurance remain
open.

## Context

E-710 made a `CurrencyRegistryContext` immutable for one operation, but the
context existed only in process memory. A workspace binding therefore could
identify a digest without being able to replay that exact policy after the
installed process registry changed or after a restore.

## Decision

Persist one validated, canonical registry JSON snapshot per digest. SQLite
migration 41 stores the snapshot independently of the workspace binding;
PostgreSQL Alembic migration `0088_pg_currency_snapshot` stores the
same tenant-scoped object with forced RLS. Binding writes the snapshot and the
workspace binding atomically, and reconciliation loads the bound snapshot as
its operation context while comparing the binding with the currently
installed registry. A historical bound context therefore remains deterministic
but reports `drifted` until the installed registry matches it.

Snapshots are included in local backup/restore and public JSON export. Reads
validate the embedded digest, version, schema and every currency policy; a
missing, malformed, or mismatched snapshot fails closed and never falls back to
the current process registry. Existing pre-migration bindings without a stored
snapshot remain diagnosable only through an explicit failure until rebound.

## Verification

`tests/test_currency_registry_governance.py` covers automatic historical
context selection, installed-registry drift, tamper refusal, and no raw
snapshot echo. Backup/export tests cover retention and bounded JSON parsing.
PostgreSQL schema, adapter, migration-chain, Ruff, Mypy, package, and full
local regression gates are required for E-711. No configured live PostgreSQL
rerun is implied by local evidence.

## Boundary and rollback

This slice does not provide live FX rates, statutory posting, connector
write-back, distributed storage durability, HA/DR, or production readiness.
Revert migration 41/`0088`, adapters, persistence/export contracts, tests,
documentation, and E-711 records together. PostgreSQL downgrade removes only
the snapshot table through the normal migration guard.
