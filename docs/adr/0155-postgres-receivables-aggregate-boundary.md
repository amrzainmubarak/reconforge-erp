# ADR 0155: PostgreSQL Receivables aggregate boundary

- Status: Accepted
- Date: 2026-07-28

## Context

The thirteen-use-case Receivables Application port had a complete SQLite
implementation but no contract-compatible PostgreSQL adapter. Customer credit,
invoice approval, receipt allocation, and aging are one financial aggregate:
splitting their transaction boundary would permit limit and allocation races.

## Decision

Add migration 0022 and a tenant-bound PostgreSQL adapter implementing all
thirteen signatures. Store money as BIGINT minor units and quantities as
unconstrained NUMERIC plus canonical text. Use composite tenant foreign keys,
forced RLS, optimistic row versions, maker-checker approval, customer and
invoice/receipt row locks for credit/allocation serialization, deterministic
identifiers, bounded inputs, transactional audit/outbox, and safe idempotency
documents. Preserve final invoice headers and lines through database triggers.

## Consequences

SQLite/API/CLI behavior remains compatible and PostgreSQL now has an executable
non-superuser lifecycle/RLS test. The test is skipped without configured service
credentials, so maturity is `live_test_available`, not `live_verified_current`.
This is not a statutory subledger, tax engine, compliance, or production claim.
Rollback drops child tables before parents and then the protection functions.
