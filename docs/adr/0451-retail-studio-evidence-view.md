# ADR 0451: Add a read-only retail settlement evidence view

- Status: Accepted for the experimental local Studio
- Date: 2026-08-07
- Decision owners: ReconForge maintainers

## Context

The retail settlement control now has deterministic CLI, SQLite, authenticated
API, and bounded PostgreSQL persistence paths. The Studio still had no way to
review that evidence, leaving the retail vertical slice without a coherent
accessible interface.

## Decision

Add `/retail-settlement` to the React Studio. It consumes one versioned,
synthetic-only projection derived from the checked-in deterministic report.
The browser validates the envelope, digest shapes, exact decimal strings,
status set, unique batch IDs, and summary counts before rendering. The view
shows status filtering, exact expected/settled/variance text, decision reasons,
algorithm and replay digests, and an explicit non-posting/provider boundary.
English and Arabic labels share the same semantic structure, and the route is
included in the automated WCAG regression set.

The projection is deliberately not a second matching engine and does not call
the retail API, a processor, an ERP, or a payment network. A future authorized
live view must use the authenticated API contract, preserve no-fallback
behavior, and add its own runtime and tenant-isolation evidence.

## Evidence

- `apps/web/src/components/RetailSettlementStudio.tsx`
- `apps/web/src/data.ts` strict projection validator and loader
- `apps/web/public/demo/studio-retail-settlement.json`
- `apps/web/src/components/RetailSettlementStudio.test.tsx`
- `apps/web/e2e/accessibility.spec.ts`
- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run test:run` (58 tests)
- `npm --prefix apps/web run build`
- `npm --prefix apps/web run e2e -- e2e/accessibility.spec.ts` (6 passed)

## Boundary and rollback

This closes only the local Studio review surface. It does not establish live
processor authenticity, settlement finality, fraud prevention, accounting
posting, ERP write-back, hosted deployment, HA/DR, or production retail
operations. Rollback removes the route, component, projection contract,
fixture, i18n/CSS additions, and focused tests in one reviewed commit; the
Python retail domain and API paths remain unchanged.
