# ADR 0392: Pass PostgreSQL service connections through `--dbname`

- **Date:** 2026-08-06
- **Status:** Accepted
- **Scope:** Native PostgreSQL backup command construction

## Context

The native backup adapter passed `service=<name>` as the positional database
argument to `pg_dump`. PostgreSQL clients treat that positional value as a
database name in this boundary instead of resolving the configured
`PGSERVICEFILE` service, which can fall back to a local Unix socket and produce
no dump in the CI service container.

## Decision

Pass the service connection explicitly as `--dbname service=<name>` for both
the primary and portable-file retry commands. Restore commands already use the
explicit `--dbname` form. Keep the service name validated and keep the closed
argv/no-shell boundary unchanged.

## Verification

The backup unit suite reports 11 passed with its declared disposable-service
skip. A PostgreSQL 16 Alpine client using the same service-file shape generated
a non-empty 5,168,214-byte custom dump when invoked with `--dbname
service=reconforge_ci_source`; the previous positional form attempted the
local socket and failed. The exact argv contract is covered by the regression
assertion in `tests/test_postgres_backup.py`.

## Boundary

This fixes command construction and does not by itself prove hosted encrypted
backup/restore, native tool availability on every runner, key custody,
cross-site recovery, or production RPO/RTO.

## Reversibility

Restore the two argv tuples and the expectation in the focused test. No
database migration or persisted data change is required.
