# ReconForge Studio Web

`apps/web` is the experimental React/Vite/TypeScript client for ReconForge Studio. It is an additive preview, not a replacement for the current server-rendered `reconforge studio` workspace.

The current slice is read-only and accepts four versioned, synthetic-only contracts: `studio-overview.json`, `studio-exceptions.json`, `studio-evidence.json`, and `studio-inventory.json`. It does not call an external service, upload ERP data, bypass local API authentication, or claim that foundation-stage modules are complete ERP functionality.

## Generate local demo data

From the repository root:

```bash
reconforge demo showcase --output output/showcase/enterprise_demo --studio-output apps/web/public/demo/studio-overview.json
```

One bridge command writes the overview, exception queue, evidence registry, and inventory control contract beside one another. It validates the ReconForge synthetic marker, bounds JSON file and record sizes, rejects invalid scalar/metric/checksum/exact-quantity/exact-value records and inconsistent FIFO/reversal/Finance Draft references, and projects allowlisted fields from known demo reports. Valid older packages without the optional inventory sample receive an empty inventory contract. The browser validates nested contract values again before rendering. Published schemas live under `docs/schemas/studio_*.schema.json`.

## Develop and verify

```bash
npm --prefix apps/web install
npm --prefix apps/web run dev
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:run
npm --prefix apps/web run build
npm --prefix apps/web run e2e
```

Playwright screenshot tests write real UI captures to `docs/assets/screenshots/`.

## Current boundary

- Implemented here: responsive shell, executive decision brief, close-readiness signal, guided control story, control-domain and entity health, native exception queue, native evidence binder, native inventory controls with on-hand/movement/count/reorder/FIFO-valuation/reversal/layer views, history-based routes, search/filter controls, command palette, current-Studio handoff links, notification/quick/profile panels, theme and density preferences, accessibility controls, English/Arabic direction support, loading/empty/error states, component tests, and screenshot tests.
- Existing product behavior remains in the Python CLI, local API, generated reports, and current Studio.
- Close, reconciliation, import, reports, control-pack, developer, and WIP navigation opens the current local Studio on its default `127.0.0.1:8601` address. Set `VITE_CURRENT_STUDIO_URL` when a different local origin is required.
- Live API mutations, browser authentication, and production deployment are future work. The exception, evidence, and inventory pages expose only bounded synthetic metadata; evidence excludes source paths, and FIFO/reversal rows are read-only previews that cannot approve workflows, validate Finance Core entries, or write to an ERP.
