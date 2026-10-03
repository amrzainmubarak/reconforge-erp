# ADR 0634: Expose Inventory Core through the PostgreSQL server boundary

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.inventory_core`, `reconforge.api.server_inventory_core`
- Supersedes: ADR 0632 for configured PostgreSQL server requests

## Context

ADR 0632 correctly stopped the Inventory Core router from falling back to a
tenant-local SQLite database when the PostgreSQL server identity profile was
enabled. The repository and schema already supported exact scaled quantities,
movement lifecycle guards, tenant/workspace hierarchy, audit events, and
outbox records, but the HTTP boundary was not wired. Leaving that boundary at
501 was safe but incomplete for the supported server profile.

## Decision

Expose all 19 Inventory Core operations through an explicit PostgreSQL server
adapter. Each request:

- derives tenant, workspace, organization, and legal-entity scope from the
  authenticated request execution scope;
- re-evaluates the central scoped policy before repository access;
- opens a `PostgresTenantBoundary` transaction with the same hierarchy so RLS
  and application checks agree;
- validates movement object scope before read, post, or void operations;
- binds actor labels to the authenticated principal and ignores spoofed
  workspace, organization, entity, and actor payload values;
- keeps `inventory.post` behind the existing privilege and step-up policy;
- preserves exact scaled quantity serialization and PostgreSQL source
  metadata; and
- maps unavailable/configuration failures to safe errors without opening local
  SQLite.

The local SQLite path remains the compatibility path when the server identity
profile is not active. If the PostgreSQL capability is not configured, the
server path remains explicitly unavailable rather than using an ambiguous
fallback.

## Evidence and limits

`tests/test_api_server_inventory_core.py` passes through the real FastAPI and
PostgreSQL boundaries using a disposable PostgreSQL 16 Alpine image at the
checked-in digest and a separate non-superuser/no-BYPASSRLS application role.
The live contract covers unit/item/warehouse/location creation, a receipt
movement, step-up-protected posting, exact on-hand output, snapshot output,
authenticated hierarchy binding, and denied workspace scope. Focused adapter,
authorization, route, Ruff, Mypy, and diff checks are required with the
slice.

This is bounded one-host synthetic evidence only. It does not establish
external IAM authenticity, multi-host or HA/DR behavior, provider behavior,
capacity, backup/restore, accessibility, compliance, certification, or
production readiness.

## Rollback

Revert the server route boundary, adapter metadata adjustment, live test, CI
selection, and documentation together. If the adapter is withdrawn, restore
the explicit 501 fail-closed boundary from ADR 0632; never restore implicit
SQLite access in PostgreSQL server mode.
