# ADR 0152: Scope PostgreSQL Master Data without duplicating masters

- Status: Accepted
- Date: 2026-07-28

## Context

The current Master Data Application contract scopes organizations, entities,
branches, and fiscal periods by workspace. Existing PostgreSQL tables are
tenant-scoped and are already referenced by Finance Core. Creating parallel
Application tables would introduce two financial sources of truth.

## Decision

Retain the existing currency, organization, legal-entity, branch, and
fiscal-period tables. Migration 0020 adds optional Application workspace fields
to organizations and periods plus forced-RLS ownership links. The new adapter
resolves every organization, entity, branch, and period through those links,
uses deterministic identifiers, serializes period overlap checks per
tenant/workspace, and writes audit/outbox evidence in the mutation transaction.

Organization codes remain tenant-global because established PostgreSQL APIs
and Finance Core resolve them at tenant scope. Fiscal-period names and overlap
rules are workspace-scoped for Application-managed rows; legacy rows retain a
separate null-workspace uniqueness path.

## Consequences

Master Data and Finance Core observe the same records. Workspace reads fail
closed, cross-workspace periods may share names and dates, and snapshots are
bounded. The optional non-superuser test must pass in a configured PostgreSQL
environment before current-live parity can be claimed.

## Rollback

Downgrade removes ownership links, workspace indexes, foreign keys, and optional
workspace columns, then restores the legacy tenant/name constraint. Downgrade
can refuse if multiple workspaces contain duplicate period names; operators
must consolidate or export those records before rollback.
