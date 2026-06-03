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

1. Run the one-command demo or generate reports from the CLI.
2. Start Studio against the same output folder.
3. Open **Exceptions**.
4. Update review status, reviewer, notes, decision reason, accepted-risk reason, or escalation owner.
5. Filter exceptions by risk, status, type, source file, amount, work order, product, and search text.
6. Export the review register from the CLI when the review state is ready.

Studio is a review companion, not a separate data store. The authoritative outputs remain the generated files in the output directory.

## Exception Filters

The Exceptions page can filter by severity/risk level, exception type, review status, source file, search text, and minimum amount impact. It can sort by risk score, amount impact, or review update date when those fields are available.

Review status is read from and written to `output/review_state.json`. Use the Studio form or CLI to update local state:

```bash
reconforge review set-status --input output --exception-id EXC-0001 --status "Under Review" --reviewer "Amr" --note "Checking source records"
```

## 10-Minute Demo

```bash
reconforge demo run --output output/demo
reconforge studio --input examples/sample_data --output output/demo
```

Open **Exceptions**, change `EXC-0001` or another visible exception, then filter by the selected review status. Studio validates allowed statuses and uses a simple local form token; it is not an authenticated multi-user workflow.

## Review Fields

Studio can update:

- `exception_id`
- `status`
- `reviewer`
- `note`
- `decision_reason`
- `accepted_risk_reason`
- `escalation_owner`

Rendered values are escaped before display. Invalid statuses are rejected. Existing review entries are preserved when another exception is updated.

## Local Security Boundary

Studio is local-only by default and binds to `127.0.0.1` unless another host is provided. It does not include authentication, roles, or approval locking yet. Use it on trusted machines and trusted networks.
