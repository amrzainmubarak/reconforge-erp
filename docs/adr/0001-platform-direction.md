# ADR 0001: Additive Platform Direction

- Status: Accepted for the foundation slice
- Date: 2026-07-21
- Decision owners: ReconForge maintainers

## Context

ReconForge already has working local-first reconciliation, control packs, reports, evidence, review state, SQLite-backed finance-control services, a local API and a server-rendered Studio. The product direction calls for broader ERP foundations and a premium modern UI. Replacing the current package or presenting a large set of mocked ERP pages would endanger compatibility and create unsupported capability claims.

The repository also needs to preserve export-based workflows, avoid cloud requirements, and maintain strict path, HTML, YAML, authentication and evidence safeguards.

## Decision

ReconForge will evolve through additive bounded slices:

1. Preserve the `reconforge` Python package, current CLI, `/api/v1`, generated artifact contracts and server-rendered Studio.
2. Add `apps/web` as an experimental React/Vite/TypeScript client rather than rewriting the current Studio.
3. Feed the first modern dashboard from a versioned synthetic JSON artifact generated from existing enterprise-demo reports.
4. Keep the client read-only until browser authentication, same-origin/CSRF behavior, permission mapping and mutation contracts are designed and tested.
5. Add domain modules only after shared company, period, currency, permission, audit and migration primitives are explicit.
6. Keep SQLite as the implemented local default and design repository boundaries that can be contract-tested for PostgreSQL later.
7. Label modern UI and module foundations as experimental or planned until their behavior exists end to end.

## Frontend technology choice

- React provides a mature component and accessibility ecosystem.
- Vite keeps local development and static production builds simple.
- TypeScript makes artifact/API contracts explicit.
- CSS custom properties provide original design tokens without copying a competitor design system.
- Recharts supplies accessible chart primitives for the first dashboard.
- Vitest and Testing Library cover behavior and semantics.
- Playwright covers responsive, RTL and screenshot flows.
- Lucide supplies generic open-source icons; product-specific marks remain original.

All dependencies are isolated under `apps/web`. The Python CLI remains usable without Node.js.

## Data-bridge choice

The first client will load `studio-overview.v1.json`. A Python bridge reads only known JSON files produced by the synthetic enterprise demo, projects allowlisted fields, validates the synthetic marker, computes aggregate values, and writes deterministic output. It will not serve arbitrary paths, expose live ERP data, or open a network listener.

This bridge proves a product-connected UI while avoiding changes to API authentication and existing report formats.

## Consequences

### Positive

- Existing workflows and security controls stay intact.
- The UI is connected to real ReconForge-generated synthetic artifacts.
- Frontend work can progress with an explicit contract and independent quality gates.
- The repository gains a clean path toward a modern authenticated client without premature coupling.
- Planned ERP breadth remains visibly separate from implemented control capabilities.

### Costs

- Two Studio implementations coexist temporarily.
- Node.js tooling adds contributor and CI work for frontend changes.
- The initial dashboard is read-only and synthetic-only.
- A future API integration needs a separate security ADR.

### Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| UI implies completed ERP modules | Show “synthetic preview” and maturity labels; keep unimplemented modules out of active routes. |
| Frontend dependency drift | Commit a lockfile, use automated audits, and keep dependencies narrow. |
| Duplicate business logic | Compute authoritative aggregates in the Python bridge/API; keep React presentation-focused. |
| Existing Studio stagnates | Maintain it until the new client reaches functional/security parity, then propose a separate migration ADR. |
| Data exposure through static files | Bridge accepts only explicit synthetic reports and outputs allowlisted aggregate/detail fields. |

## Alternatives considered

### Rewrite `reconforge/studio/app.py` in place

Rejected for this slice because it mixes visual change with proven authentication, CSRF, escaping, download and DB behavior.

### Build 20 disconnected mock pages

Rejected because visual breadth without contracts, state and tests would contradict the repository’s evidence-first product rule.

### Make the React client call authenticated APIs immediately

Deferred. The browser session, CSRF, origin, token storage and permission model need a dedicated design and security tests.

### Adopt a competitor UI kit or template

Rejected. ReconForge will use original layout, tokens, components and copy. Generic open-source icons/charts are dependencies, not a copied product design.

## Follow-up decisions

- ADR: browser authentication and same-origin deployment.
- ADR: module registry and lifecycle.
- ADR: shared ERP platform data model.
- ADR: PostgreSQL adapter and migration compatibility.
