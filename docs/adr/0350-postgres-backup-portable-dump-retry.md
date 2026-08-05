# ADR 0350: Retry a missing PostgreSQL dump with a portable file argument

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The native PostgreSQL backup adapter invokes `pg_dump` with a closed argument
vector. Some client wrappers can return success without materializing the
requested file when the separate `--file <path>` form is not handled as
expected. Treating that condition as a final error makes the runtime gate
opaque and does not attempt the equivalent portable spelling.

## Decision

After a successful `pg_dump` exit, require a non-empty dump. If it is missing,
delete only the disposable temporary path and retry once with
`--file=<path>`. A second missing or empty artifact fails closed with an
explicit error. No retry is attempted after a non-zero tool exit.

## Consequences

The backup path is more tolerant of wrapper argument parsing while remaining
bounded, read-only, secret-free, and limited to a temporary directory. This is
not evidence that a hosted CI environment or a production backup toolchain is
healthy, and it does not establish HA/DR, restore RPO/RTO, or provider
interoperability.

## Verification and rollback

`tests/test_postgres_backup.py` covers normal encryption, one successful
portable retry, and fail-closed double absence. Rollback removes the retry,
tests, ADR, manifest entry, and execution records; no schema or data rewrite is
required.
