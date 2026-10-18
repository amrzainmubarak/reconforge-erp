# ADR 0635: Expose Receivables through the PostgreSQL server boundary

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.receivables`, `reconforge.api.server_receivables`

## Context

The Accounts Receivable PostgreSQL repository already enforced exact minor-unit
money, arbitrary-scale quantity text, immutable approved invoices, credit
controls, maker-checker separation, idempotency, audit events, outbox events,
and tenant RLS. The HTTP router still used the generic local-database
dependency in server mode, so an authenticated server request could resolve
to a tenant SQLite database instead of the configured PostgreSQL aggregate.
That ambiguity was unsafe for a financial boundary even though the local
SQLite compatibility path remained valid.

## Decision

Expose all Receivables customer, invoice, receipt, credit-exposure, and aging
operations through an explicit PostgreSQL server adapter. Each request:

- derives tenant and workspace scope from the authenticated request execution
  scope and re-evaluates central scoped policy before repository access;
- opens a `PostgresTenantBoundary` transaction with the same scope so database
  tenant RLS and application hierarchy checks agree;
- validates invoice/receipt object scope and customer scope before mutation;
- canonicalizes organization and legal-entity codes from authenticated scope;
- binds created, submitted, posted, and approved actor labels to the
  authenticated principal, while preserving existing maker-checker and
  credit-control/step-up guards;
- preserves exact integer minor-unit amounts and arbitrary-scale quantity
  serialization, including quantities beyond twelve decimal places; and
- maps unavailable/configuration failures to safe errors without opening local
  SQLite.

The local SQLite path remains the compatibility path when the PostgreSQL
server profile is not active. If the PostgreSQL capability is unavailable, the
server path remains explicitly unavailable rather than falling back to a
tenant-local database.

## Evidence and limits

`tests/test_api_server_receivables.py` passes through the real FastAPI and
PostgreSQL boundaries using a disposable PostgreSQL 16 Alpine image at the
checked-in digest and a separate application role without superuser or
`BYPASSRLS`. The contract covers the customer/invoice/receipt lifecycle,
maker denial, checker approval actor binding, credit exposure, aging, exact
`1.0000000000001` quantity output, spoofed payload hierarchy binding, and
denied workspace scope. The existing direct PostgreSQL Receivables lifecycle
test runs in the same provisioned environment. The test fixture installs the
outbox schema because Receivables writes append-only outbox events.

This is bounded one-host synthetic evidence only. It does not establish
external IAM authenticity, multi-host or HA/DR behavior, provider behavior,
capacity, backup/restore, accessibility, compliance, certification, or
production readiness.

## Rollback

Revert the server route boundary, adapter workspace-ID compatibility and
aging projection changes, live contract, CI selection, and documentation
together. If the adapter is withdrawn, restore an explicit fail-closed server
error boundary; never restore implicit SQLite access for PostgreSQL server
requests.
