# ADR 0267: PostgreSQL consolidation certification parity

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Extend the PostgreSQL consolidation-close repository with posted-run
certification operations. Each operation is tenant-scoped; prepare and review
lock the run, replay-verify the JSONB worksheet, require `Posted` or `Reversed`,
and reuse the existing RLS certification repository and maker-checker triggers.

## Boundary

This proves backend parity for internal workflow metadata only. It does not
create a legal signature, statutory consolidation, source-ERP posting, or
production certification claim.

## Reversibility

The change is additive to the application protocol, adapter, and live test.
Existing migrations and run transitions remain compatible.
