# ADR 0486: Modern Studio accessibility evidence

- **Status:** Accepted
- **Date:** 2026-08-10
- **Scope:** `apps/web` local synthetic/read-only Studio projections

## Context

ReconForge's breadth slices include English/Arabic read-only projections for
bank, retail, manufacturing, and professional evidence. The previous browser
contracts existed, but the current head needed a fresh typecheck, component
suite, production build, and accessibility run before this evidence could be
carried forward.

## Decision

Record the current local web gate as evidence without changing the runtime
claim boundary. TypeScript typecheck, Vitest, Vite production build, and the
Playwright accessibility suite are required for this slice. The suite must
cover English and Arabic critical routes, keyboard focus/dialog behavior,
contrast, reduced motion, color-safe states, redaction, bounded industry
projections, and mobile landmarks. The projections remain synthetic,
read-only, and provider-neutral.

## Evidence

- Typecheck passed.
- Vitest passed 12 files / 67 tests.
- Vite production build passed.
- Playwright accessibility passed 9/9.

## Consequences

This improves confidence in the local accessibility and RTL browser surface,
but does not prove authenticated live API browser behavior, provider
authenticity, accounting posting, write-back, hosted deployment, HA/DR, or
production availability. Rollback is documentation-only.
