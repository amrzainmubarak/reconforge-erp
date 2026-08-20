# ADR 0349: Bind PostgreSQL metrics reads to tenant policy

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The server-profile metrics dashboard and lineage projections are tenant-wide
reads. Their ordinary permission dependency must be followed by a central
policy check bound to the request tenant before the PostgreSQL metrics adapter
is called.

## Decision

Re-evaluate `metrics.read` for both server metrics routes using the validated
request tenant and `workspace_id=None`. Local SQLite requests retain their
existing compatibility path.

## Consequences

Metrics access cannot rely only on a raw permission snapshot in server mode,
while no synthetic workspace is introduced. This remains operational metric
evidence, not a security assurance, SLO, compliance or production-readiness
claim; federation, distributed invalidation, and complete worker/export/UI
policy adoption remain open.

## Verification and rollback

`tests/test_api_metrics.py` covers both route calls and null-workspace tenant
binding. Rollback removes the helper calls, test, ADR, and manifest entry; no
schema or data migration is required.
