# ADR 0465: Hosted sequential-matching runtime gate

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The PostgreSQL sequential matching worker already had a live integration test
covering carry-forward and reversal pairing, including persisted lineage,
strategy digests, and sibling-tenant refusal. The test was not selected by the
server-boundaries workflow because the parity inventory intentionally covers
application repositories, while the sequential worker is a strategy adapter.

## Decision

Run the bounded live worker test explicitly in `server-boundaries` after the
grouped-matching scale profile. Keep the test synthetic, single-node, and
non-posting. The repository phase-4 contract must fail if the explicit selector
or its test name is removed.

## Rationale and boundaries

This adds hosted coverage for the actual PostgreSQL worker projection without
misclassifying a pure strategy as an application-service parity row. It proves
only the selected carry-forward/reversal persistence and tenant isolation
scenario; it does not establish distributed scale, soak, provider behavior,
posting, or production readiness.

## Reversibility

Removing the explicit workflow line and contract assertion restores the prior
matrix; no schema or runtime data changes are introduced.

## Verification

The live Docker PostgreSQL 16.14 run of
`test_live_postgres_grouped_matching_worker_persists_group_lineage_and_is_tenant_scoped`
passes locally. The phase-4 workflow contract remains green. A fresh hosted run
is required before treating the hosted gate as passed.
