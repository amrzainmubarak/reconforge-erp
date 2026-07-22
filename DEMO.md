# ReconForge Expert Showcase

This is the shortest credible path through ReconForge ERP. It uses generated synthetic records, real deterministic services, strict browser contracts, and the actual React Studio—no stock mockup, customer data, external call, or hidden SaaS dependency.

## Build the complete showcase

```bash
make showcase-serve
```

Open `http://127.0.0.1:4173`. The target generates the enterprise package, projects four allowlisted Studio contracts, validates the TypeScript application, creates the production web build, and serves it on loopback. Use `make showcase` when a build-only command is preferred.

Without Make:

```bash
python -m reconforge.cli demo showcase \
  --output output/showcase/enterprise_demo \
  --studio-output apps/web/public/demo/studio-overview.json
npm --prefix apps/web run build
npm --prefix apps/web run preview -- --host 127.0.0.1 --port 4173
```

Use `--persist-db` on `demo showcase` when a seeded local SQLite walkthrough database is useful. It remains inside the generated enterprise-demo directory.

## Five-minute decision story

1. **Executive pulse** — start with close readiness, the deterministic decision brief, control-domain health, and multi-entity risk concentration.
2. **Exception triage** — use the guided step to open the complete synthetic queue, then filter by risk, source, status, owner, or deterministic exception ID.
3. **Evidence verification** — move to the evidence binder and show allowlisted provenance plus SHA-256 integrity aids. Source paths are intentionally excluded.
4. **Inventory trace** — review exact quantities, posted local movements, count sessions, reorder advice, FIFO layers, valuation documents, and an exact valuation reversal.
5. **Boundary close** — show the persistent read-only and synthetic labels: Finance references are Drafts, no entry is validated automatically, and nothing is written to a source ERP.

## What proves the demo is real

| Claim | Evidence |
| --- | --- |
| Generated, not hand-edited | `reconforge demo showcase` rebuilds the source package and Studio contracts |
| Local-first | Contract source records `local_first: true` and `external_calls: false` |
| Traceable metrics | Every metric and control-domain score carries deterministic lineage |
| Strict browser boundary | Python allowlists fields; JSON Schema and runtime TypeScript validators reject malformed nested data |
| Real UI | Vitest exercises interactions and Playwright regenerates repository screenshots from the running app |
| Honest scope | Synthetic/read-only labels and product boundaries remain visible throughout the experience |

## Generated artifacts

- `output/showcase/enterprise_demo/` — source records, walkthrough, presenter script, reports, evidence samples, and checksum manifest.
- `apps/web/public/demo/studio-overview.json` — executive showcase contract.
- `apps/web/public/demo/studio-exceptions.json` — complete exception queue contract.
- `apps/web/public/demo/studio-evidence.json` — path-free evidence metadata contract.
- `apps/web/public/demo/studio-inventory.json` — exact inventory/FIFO control contract.
- `apps/web/dist/` — local production web build.

This showcase demonstrates early-stage, foundation-level behavior for local evaluation. It is not evidence of production deployment, a real customer, an audit opinion, a certification, or a complete ERP transaction suite.
