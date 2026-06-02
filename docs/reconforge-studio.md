# ReconForge Studio

ReconForge Studio is the local web interface for reviewing validation, reconciliation, rule, WIP, evidence, and report outputs. It is intentionally lightweight and server-rendered so it does not require a frontend build system.

## Start Studio

```bash
reconforge studio --input examples/sample_data --output output
```

Then open the local URL printed by the CLI. The Studio runs with FastAPI and reads local files only.

## Pages

| Page | Purpose |
| --- | --- |
| Home | Status, KPIs, and navigation |
| Dataset Health | Input file counts and structural health |
| Validation | Validation report summary where available |
| Reconciliation | Stock/GL and work-order result links |
| Exceptions | Filterable exception view with local review status |
| WIP Aging | Aging buckets and stale work orders |
| Control Packs | Rule engine result summaries |
| Evidence | Links to generated evidence binder case folders |
| Downloads | Links to generated Excel, Markdown, CSV, JSON, and HTML reports |
| Docs | Local documentation entry points |

## Recommended Workflow

1. Run validation and reconciliations from the CLI.
2. Run rule packs for the relevant business process.
3. Generate the management pack and evidence binder.
4. Start Studio against the output folder.
5. Review exceptions by risk, status, type, source file, amount, work order, product, and search text.

Studio is a review companion, not a separate data store. The authoritative outputs remain the generated files in the output directory.

## Exception Filters

The Exceptions page can filter by severity/risk level, exception type, review status, source file, search text, and minimum amount impact. It can sort by risk score, amount impact, or review update date when those fields are available.

Review status is read from `output/review_state.json`. Use the CLI to update local state:

```bash
reconforge review set-status --input output --exception-id EXC-0001 --status "Under Review" --reviewer "Amr" --note "Checking source records"
```
