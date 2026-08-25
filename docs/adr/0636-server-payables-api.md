# ADR 0636: Expose Payables through the PostgreSQL server boundary

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.payables`, `reconforge.api.server_payables`

## Context

The Accounts Payable PostgreSQL repository already supported exact decimal
quantities, immutable lifecycle transitions, purchase-order receipts,
supplier invoices, three-way matching, maker-checker separation, idempotency,
audit events, outbox events, and tenant RLS. The HTTP router still used the
generic local-database dependency in server mode, so an authenticated server
request could resolve to a tenant SQLite database instead of the configured
PostgreSQL aggregate. That ambiguity was unsafe for a financial control path.

## Decision

Expose all Payables supplier, purchase-order, goods-receipt, supplier-invoice,
three-way-match, and approval operations through an explicit PostgreSQL server
adapter. Each request:

- derives tenant and workspace scope from the authenticated request execution
  scope and re-evaluates central scoped policy before repository access;
- opens a `PostgresTenantBoundary` transaction with the same scope so database
  tenant RLS and application hierarchy checks agree;
- validates purchase-order, receipt, and supplier-invoice object scope and
  supplier scope before mutation;
- canonicalizes organization and legal-entity codes from authenticated scope;
- binds maker, matcher, and checker actor labels to authenticated principals,
  preserving existing separation-of-duties and human approval controls; and
- preserves exact quantity text and safe error handling without opening local
  SQLite in the server profile.

The local SQLite path remains the compatibility path when the PostgreSQL
server profile is not active. If the PostgreSQL capability is unavailable, the
server path remains explicitly unavailable rather than falling back to a
tenant-local database.

## Evidence and limits

`tests/test_api_server_payables.py` passes through the real FastAPI and
PostgreSQL boundaries using a disposable PostgreSQL 16 Alpine image at the
checked-in digest and a separate application role without superuser or
`BYPASSRLS`. The contract covers supplier and PO creation, exact
`1.0000000000001` quantity, submit/approve, goods receipt, supplier invoice,
three-way match, maker denial, checker/matcher actor binding, list projection,
spoofed hierarchy binding, and denied workspace scope. The existing direct
PostgreSQL Payables lifecycle test runs in the same provisioned environment.
The fixture installs the ledger outbox schema because Payables writes
append-only outbox events.

This is bounded one-host synthetic evidence only. It does not establish
external IAM authenticity, multi-host or HA/DR behavior, provider behavior,
capacity, backup/restore, accessibility, compliance, certification, or
production readiness.

## Rollback

Revert the server route boundary, adapter workspace-ID compatibility, live
contract, CI selection, and documentation together. If the adapter is
withdrawn, restore an explicit fail-closed server error boundary; never
restore implicit SQLite access for PostgreSQL server requests.
