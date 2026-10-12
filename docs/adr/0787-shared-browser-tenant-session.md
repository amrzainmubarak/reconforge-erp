# ADR 0787: Share tenant session state across Studio routes

- Status: Accepted
- Date: 2026-10-03
- Owners: Studio / Identity

## Context

Administration retained tenant/session state inside its own component while live
metrics omitted the tenant header. Navigation lost session context. Expired
step-up state could leave the user without a usable reauthentication form.

## Decision

Keep one in-memory browser session provider above routed components. Bind API
requests to its selected tenant and retain HttpOnly server session credentials.
Do not store credentials or session state in browser persistent storage.
Use generation and cancellation checks so an old response cannot repopulate
another tenant's screen. Explicit logout, session rejection and tenant switching
clear displayed state; step-up expiry returns to the verification form.

Keep explicit local mode available without inventing a tenant header.

## Verification and rollback

Component and browser regressions cover navigation, tenant headers, stale
responses, expiry recovery, real logout/revocation and sibling-tenant denial.
Real browser tests use two synthetic tenants on a database created only by the
production Alembic chain. Final run results are in execution evidence.

Rollback restores the prior components/provider integration without a data
migration. This session foundation does not implement AP/AR/GL editing screens
or demonstrate a complete production financial application.
