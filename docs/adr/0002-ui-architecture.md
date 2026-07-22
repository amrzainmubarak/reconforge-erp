# ADR 0002: Modern Studio Read-Only Contract Architecture

- Status: Accepted for the read-only synthetic contract slice
- Date: 2026-07-21
- Decision owners: ReconForge maintainers

## Context

The first modern Studio dashboard proved the visual shell with one generated synthetic artifact. Adding exception, evidence, and inventory-control views could either couple the browser to authenticated APIs prematurely, duplicate static mock data, or extend the existing bounded artifact bridge. Browser authentication, CSRF, permissions, and same-origin deployment are not yet designed for this client.

Evidence metadata is especially sensitive because server-side registries can contain local paths. Inventory records also need strict exact-quantity and scope-shaped fields without database identity or costing data. A browser contract must not become an indirect arbitrary-file discovery or serving mechanism.

## Decision

1. Keep this Studio slice read-only and synthetic-only.
2. Generate four independent versioned contracts in one atomic-per-file bridge operation: overview, exception queue, evidence binder, and inventory control center.
3. Accept only the known synthetic enterprise-demo report set, enforce byte/record/text limits, and project explicit scalar allowlists.
4. Generate deterministic exception IDs from stable allowlisted fields so the UI has keys without exposing database or filesystem identity.
5. Validate every contract again at the browser boundary before rendering nested values.
6. Exclude evidence source paths and arbitrary links from the browser contract. Display evidence code, provenance class, redaction status, availability status, and validated SHA-256 only.
7. Use lightweight History API routes for the four native views plus the dashboard shell. Keep existing Studio handoff links for workflows that still require server-rendered behavior.
8. Require loading, error, empty, search/filter, responsive, RTL, component-test, and screenshot-test coverage for each native page.

## Consequences

### Positive

- The pages are driven by genuine ReconForge-generated synthetic outputs rather than disconnected UI fixtures.
- The frontend and generator share published JSON Schema contracts with explicit versioning.
- Exception filtering, evidence inspection, and inventory-control exploration work with no external calls after the local build.
- Evidence paths remain confined to server-side/local workflow boundaries.
- Future API integration can replace individual loaders without redesigning the page shell.

### Costs

- Static artifacts can become stale until the bridge command is rerun.
- Four runtime validators must remain compatible with four published schemas.
- Routes are read-only; ownership/status mutations still belong to the authenticated current Studio.

### Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Independently edited input contains real data despite its marker | Documentation states that the marker is a guard, not proof; only known allowlisted fields are projected. |
| Contract drift | JSON Schema validation, Python bridge tests, TypeScript runtime validators, and UI tests fail independently. |
| Static-host route refresh returns 404 | Development uses Vite fallback; production hosting must configure an SPA fallback before this preview is presented as deployable. |
| UI suggests mutation support | Pages carry read-only, synthetic, and foundation labels; mutation workflows remain linked to current Studio. |

## Deferred decisions

- Browser authentication, CSRF, cookies/tokens, same-origin deployment, and permission-aware routing.
- API-generated client types and compatibility negotiation.
- Production hosting and cache invalidation.
- Mutating exception ownership/status, evidence registration, and inventory movement workflows.
