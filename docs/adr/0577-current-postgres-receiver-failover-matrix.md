# ADR 0577: Current PostgreSQL write-back receiver failover matrix

## Status

Accepted — 2026-08-23

## Context

The receiver contract already had a historical two-version failover report.
Because receiver replay can have financial effect, its current evidence must
cover both supported PostgreSQL images, response loss, uncertain synchronous
commit, rejoin, and restart endpoint recovery.

## Decision

Run `.github/scripts/verify_postgres_writeback_receiver_failover_matrix.py`
against the digest-pinned PostgreSQL 16.14 and 17.10 images. Retain the closed
report with source/policy digests and require all checks, cleanup, and SQLite
canonical-history parity before counting the run as evidence.

## Limits

The run uses two nodes per version on one Docker host, a manual fencing/rejoin
controller, synthetic digest-only effects, and synthetic credentials. It does
not establish cross-host HA, automatic failover, provider semantics,
accounting settlement, or production exactly-once behavior.
