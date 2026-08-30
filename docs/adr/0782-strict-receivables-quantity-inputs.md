# ADR 0782: Enforce strict quantity inputs in SQLite Receivables

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Receivables

## Context

The PostgreSQL Receivables adapter already routed invoice quantities through
the strict exact parser, while the SQLite adapter converted a caller value
with `Decimal(str(...))`. That allowed binary floating-point and
scientific-notation inputs to cross the local invoice boundary with a weaker
policy than the tenant-scoped adapter.

## Decision

Route SQLite Receivables invoice quantity validation through
`parse_exact_amount()`, retaining the existing positive quantity and
arbitrary-scale canonical text behavior. Preserve the existing
backend-neutral `PlatformError` boundary and do not change schema or
migration behavior.

## Consequences and rollback

SQLite and PostgreSQL now reject the same binary floating-point, non-finite,
malformed, missing, and scientific-notation quantity inputs before invoice
line persistence and line-total arithmetic. Rollback is a source/test/ADR/
execution-record revert with no external-state mutation.

This is a bounded Receivables input-integrity control. It does not claim
complete quantity-unit governance, tax correctness, statutory posting,
settlement, provider authenticity, or production assurance.
