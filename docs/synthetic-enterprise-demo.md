# Synthetic Enterprise Demo

The synthetic enterprise demo creates a repeatable local folder that shows ReconForge ERP platform foundations using generated data only.

Run:

```bash
reconforge demo enterprise --output output/enterprise_demo
```

For the complete enterprise package plus all four modern Studio contracts in one command:

```bash
reconforge demo showcase \
  --output output/showcase/enterprise_demo \
  --studio-output apps/web/public/demo/studio-overview.json
```

The showcase overview adds only deterministic projections: close readiness, high-risk/open counts, blocked/completed close-task counts, control-domain scores with lineage, and entity-level exception concentration. It does not generate AI claims or infer business outcomes.

Optionally persist a local SQLite demo database inside the same folder:

```bash
reconforge demo enterprise --output output/enterprise_demo --db output/enterprise_demo/reconforge.db
```

## Boundaries

- Synthetic data only.
- No real customers.
- No fake ROI, fake logos, fake testimonials, fake adoption, or fake revenue.
- No audit opinion, assurance conclusion, legal signature, or compliance certification.
- No SOX, SOC 2, ISO, GDPR, IFRS, GAAP, audit, or tax compliance claim.
- No direct ERP connector, sync, hosted storage, cloud upload, telemetry, or SaaS behavior.
- Local-first demo only.

## Generated Outputs

The command writes a local package under the requested output folder:

- `README.md`
- `demo_walkthrough.md`
- `demo_script.md`
- `demo_manifest.json`
- `screenshots_checklist.md`
- `sample_entities.json`
- `sample_periods.json`
- `sample_trial_balance.csv`
- `sample_journals.csv`
- `sample_intercompany.csv`
- `sample_controls.csv`
- `sample_account_reconciliations.json`
- `sample_close_tasks.json`
- `sample_inventory_control.json`
- `sample_evidence_references.json`
- `sample_matching_left.csv`
- `sample_matching_right.csv`
- `sample_unified_exceptions.json`
- `sample_metrics.json`
- `sample_evidence/`
- `reports/`
- `reconforge.db` when `--db` is used

Every generated source file includes the marker `SYNTHETIC_ENTERPRISE_DEMO_ONLY` or a manifest-level synthetic marker.

## What It Demonstrates

The package uses synthetic examples for:

- Multi-entity reference data.
- Multiple synthetic periods.
- Accounts and trial balance rows.
- Close tasks and readiness examples.
- Account reconciliation records.
- Evidence registry references and checksum/provenance aids.
- Journal control findings.
- Intercompany imbalance cases.
- Control testing plans and results.
- Deterministic matching results.
- Unified exception queue examples.
- Metric and dashboard data.
- Synthetic inventory on-hand, movement, warehouse, physical-count, reorder-advice, FIFO-valuation, exact valuation-reversal, cost-layer, Finance Draft-reference, and deterministic control-display records.

The inventory sample is a marked file fixture for the read-only modern Studio contract; this command does not import those sample rows into the inventory database ledger. Count/reorder/valuation/reversal/layer rows are synthetic display records, not evidence of purchasing, automatic adjustment posting, Finance Core validation, or ERP writeback. The bridge strictly allowlists fields and rejects inconsistent Approved valuation/reversal Finance references, inverse movement types, or FIFO layer balances. When `--db` is used, the command seeds the existing local SQLite platform foundations through current services. It does not add DB schema, migrations, SaaS features, or live ERP connectivity.

## Regeneration

The default file package is deterministic enough for test assertions and repeated local walkthroughs. If `--db` is used, the database path must be inside the demo output folder and is recreated as generated demo state. The SQLite file contains runtime audit timestamps from the existing DB services, so treat it as a local walkthrough artifact rather than a byte-stable fixture.
