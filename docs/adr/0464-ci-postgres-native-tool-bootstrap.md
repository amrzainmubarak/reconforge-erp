# ADR 0464: CI PostgreSQL native-tool bootstrap contract

> The package-selection portion of this ADR is superseded by ADR 0494, which
> pins the client major version to the PostgreSQL 16 service. The `pg_config`
> bindir and five-tool checks remain in force.

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The live server-boundaries job exercises encrypted PostgreSQL backup and
isolated restore through versioned native binaries. The job already checked
`pg_config --bindir`, but installing only the client package does not make the
`pg_config` development utility an explicit dependency on every Ubuntu image.
The historical backup failure also showed that the live matrix must continue
to include backup, metrics, and migration contracts together.

## Decision

Install both `libpq-dev` and the PostgreSQL client package before the live
matrix. The first provides the `pg_config` contract; the second provides the versioned
`pg_dump`, `pg_restore`, `createdb`, `dropdb`, and `psql` binaries. Keep the
bindir executable assertions and the service-file based live test profile.
Add a repository contract that binds the native-tool bootstrap to the
PostgreSQL parity inventory entries for backup and metrics, plus the explicit
Alembic migration test.

ADR 0494 narrows the client package to `postgresql-client-16` and adds a
major-version assertion because the service image is PostgreSQL 16.

## Rationale and boundaries

The change makes the hosted runner dependency explicit and prevents a
distribution-package drift from silently selecting an unversioned wrapper.
It does not claim that a hosted run has passed, nor does it replace live
backup/restore, independent HA/DR, provider, or production evidence.

## Reversibility

Reverting the package addition and contract test restores the former workflow
without changing application schemas or data. No external system is mutated
by this ADR.

## Verification

`tests/test_phase4_execution_contract.py` passes locally, including the
native-tool ordering, executable-path, service-file, and repaired failure-surface
assertions. A fresh GitHub server-boundaries run remains required before
E-461 can move from `in_progress` to `completed`.
