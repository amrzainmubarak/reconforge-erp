# ADR 0285: Verify the PPA API on the PostgreSQL server boundary

- **Status:** Accepted (bounded E-334 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

E-333 verified the PPA API contract with a local authenticated principal and
verified the persistence adapter in its own PostgreSQL gate. Those two facts do
not prove that server identity, tenant scope, strict request reconstruction,
maker-checker foreign keys, and the HTTP transaction work together.

## Decision

Extend the existing live PostgreSQL server-identity boundary test with the PPA
schema, an independent reviewer identity, and authenticated POST/GET calls.
The test runs with the configured non-superuser application role, applies the
workspace/organization headers, performs the required password step-up, and
asserts a replayable artifact with `posted: false`. It removes synthetic rows
and restores the append-only trigger during cleanup.

## Boundary

This proves one synthetic PostgreSQL service and one API process path. It does
not prove hosted availability, multi-process scale, HA/DR, statutory posting,
tax/impairment, live valuation providers, source write-back, or production
readiness. The existing tenant-local SQLite domain router remains unchanged.
