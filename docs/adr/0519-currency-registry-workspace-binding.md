# ADR-0519: Persist workspace currency-registry bindings

## Status

Accepted — additive governed binding and drift evidence; per-operation
registry context and independently persisted registry versions remain open.

## Context

ADR-0518 made master-data currency drift visible against the installed
`CurrencyRegistry`, but the result could not say which registry snapshot an
operator had selected for a workspace. A process-wide registry comparison is
not sufficient evidence of a durable workspace policy, and silently switching
that process-wide registry would make replay and rollback unsafe.

## Decision

Persist one binding per workspace containing the canonical registry version,
digest, UTC bind time, and actor. SQLite migration 40 and PostgreSQL Alembic
migration `0087_pg_currency_binding` enforce workspace foreign keys, digest
shape, append-only audit evidence, and PostgreSQL forced tenant RLS. The
binding is included in master-data snapshots, structured exports, encrypted
backup/restore, and the PostgreSQL outbox path.

Reconciliation reports `unbound`, `current`, `drifted`, or `invalid`. A
drifted or invalid binding is inconsistent and fails closed for governance
evidence; it never installs or switches the process-wide registry. The
authenticated API and local CLI provide an explicit bind action, while reads
remain available for diagnosis. Malformed binding details are sanitized and
must not echo arbitrary input.

## Verification

The currency-governance, master-data service/API/CLI, application-port,
PostgreSQL schema/adapter, migration, backup/restore, export, authorization
inventory, Ruff, Mypy, and package tests cover the contract. E-709 records the
focused and full local verification; a configured live PostgreSQL rerun and
hosted CI remain separate evidence gates.

## Boundary and rollback

This slice does not provide per-operation registry context, independent
persisted registry-version storage, FX conversion, live rates, statutory
accounting, or production assurance. Revert the SQLite migration, Alembic
migration, adapters, API/CLI, schemas, tests, manifest, ADR, and E-709 records
together. A PostgreSQL downgrade drops only the binding table and is guarded
by the normal migration rollback procedure; no customer or production
database action is authorized by this ADR.
