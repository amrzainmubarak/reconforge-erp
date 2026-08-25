# ADR 0639: Expose Inventory Valuation through the PostgreSQL server boundary

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.inventory_valuation`, `reconforge.api.routes.inventory_valuation_reversal`, `reconforge.api.server_inventory_valuation`

## Context

The PostgreSQL Inventory Valuation and Valuation Reversal repositories already
enforced exact minor/scaled values, FIFO allocation, Finance Core draft
generation, immutable effects, and maker-checker controls. The authenticated
API routers still used the generic local SQLite dependency in Server Profile.
That left a high-risk path where a valuation or reversal request could be
accepted by server identity while persisting financial state outside the
configured PostgreSQL aggregate.

## Decision

Expose policy, valuation-document, cost-layer, summary, snapshot, and reversal
operations through an explicit PostgreSQL server adapter. Each request:

- derives tenant/workspace/organization/legal-entity scope from the
  authenticated execution scope and re-evaluates central policy;
- opens a `PostgresTenantBoundary` transaction with the same hierarchy;
- validates movement, valuation-document, and reversal object scope before
  reads or lifecycle mutation;
- canonicalizes policy hierarchy codes from the authenticated scope;
- binds maker/checker actors to the authenticated principal; and
- preserves the existing exact FIFO, Finance Draft, reversal-line, audit, and
  outbox invariants without opening local SQLite in Server Profile.

The local SQLite dependency remains the compatibility path only when the
PostgreSQL server profile is not active. If the PostgreSQL capability is not
available, the server path returns a safe unavailable error rather than using
an ambiguous local fallback.

## Evidence and limits

`tests/test_api_server_inventory_valuation.py` passes through the real FastAPI
and PostgreSQL boundaries using a disposable PostgreSQL 16 Alpine image at the
checked-in digest and a separate application role without superuser or
`BYPASSRLS`. The contract covers policy creation, receipt valuation, exact
`12.34`, maker/checker approval, FIFO delivery valuation exact `4.94`, reversal
creation and approval, snapshot, and denied workspace scope. Existing direct
PostgreSQL valuation and reversal contracts remain covered.

This is bounded one-host synthetic evidence only. It does not establish
external IAM authenticity, multi-host or HA/DR behavior, provider behavior,
capacity, backup/restore, accessibility, compliance, certification, or
production readiness.

## Rollback

Revert the server route boundary, workspace-ID compatibility, live contract,
CI selection, and documentation together. If the adapter is withdrawn, retain
an explicit fail-closed server error boundary; never restore implicit SQLite
access for PostgreSQL server requests.
