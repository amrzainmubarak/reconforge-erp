# ADR 0638: Expose Inventory Planning through the PostgreSQL server boundary

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.inventory_planning`, `reconforge.api.server_inventory_planning`

## Context

Inventory Planning already had a PostgreSQL repository and schema for count
sessions, exact scaled quantities, reorder rules, audit events, and outbox
events. The API router still used the generic local SQLite dependency in Server
Profile, so an authenticated server request could write count and reorder
state to a tenant-local database instead of the configured PostgreSQL
aggregate. That was unsafe for inventory control and count approval.

## Decision

Expose all Inventory Planning summary, snapshot, count-session, reorder-rule,
and reorder-signal operations through an explicit PostgreSQL server adapter.
Each request:

- derives tenant/workspace/organization/legal-entity scope from the
  authenticated request execution scope and re-evaluates central policy;
- opens a `PostgresTenantBoundary` transaction with the same hierarchy;
- validates count-session object scope before reads and lifecycle mutation;
- canonicalizes organization/entity codes from authenticated scope;
- binds count/reorder actor labels to the authenticated principal; and
- preserves exact scaled quantity serialization without opening local SQLite
  in Server Profile.

The local SQLite path remains the compatibility path when the PostgreSQL
server profile is not active. If the PostgreSQL capability is unavailable, the
server path returns a safe unavailable error rather than using an ambiguous
local fallback.

## Evidence and limits

`tests/test_api_server_inventory_planning.py` passes through the real FastAPI
and PostgreSQL boundaries using a disposable PostgreSQL 16 Alpine image at the
checked-in digest and a separate application role without superuser or
`BYPASSRLS`. The contract covers full hierarchy setup, seeded Inventory Core
movement, count create/start/record/submit/approve, maker-checker denial,
exact `2.500` output, reorder signals, actor/hierarchy binding, and denied
workspace scope. The direct PostgreSQL Planning lifecycle runs in the same
provisioned environment.

This is bounded one-host synthetic evidence only. It does not establish
external IAM authenticity, multi-host or HA/DR behavior, provider behavior,
capacity, backup/restore, accessibility, compliance, certification, or
production readiness.

## Rollback

Revert the server route boundary, workspace-ID adapter compatibility, live
contract, CI selection, and documentation together. If the adapter is
withdrawn, restore an explicit fail-closed server error boundary; never
restore implicit SQLite access for PostgreSQL server requests.
