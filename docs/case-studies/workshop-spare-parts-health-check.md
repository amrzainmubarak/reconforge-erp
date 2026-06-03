# Synthetic Case Study: Workshop Spare-Parts Health Check

This is a synthetic case study and illustrative scenario based on ReconForge sample data. It is not a real customer story, does not describe a production deployment, and does not claim savings or audit results.

## Company Profile

Northline Fleet Services is a fictional mid-market workshop and fleet support company. The company maintains commercial vehicles and manages spare-parts inventory across a central store and service workshop.

The finance controller wants to understand whether stock issues, GL postings, work orders, purchase orders, old-part returns, and WIP balances are being reviewed consistently at month end.

## Data Inputs

The illustrative scenario uses local CSV/XLSX exports shaped like Odoo/SAP-style data:

- `stock_moves.csv`
- `gl_entries.csv`
- `work_orders.csv`
- `purchase_orders.csv`
- `old_parts_returns.csv`
- `invoices.csv`
- optional product and customer files for supporting analysis

The exports are local files. No cloud upload or live ERP connector is used.

## Process

The finance/controller team runs a local demo workflow:

```bash
reconforge demo run --output output/demo
```

For a mapping readiness check, the consultant runs:

```bash
reconforge mappings wizard --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/mapping_wizard
```

After reviewing exceptions in Studio:

```bash
reconforge studio --input examples/sample_data --output output/demo
```

The team creates a client handoff pack:

```bash
reconforge report client-pack --input output/demo --output output/client_pack
```

For an externally shareable rehearsal pack, use conservative sharing controls:

```bash
reconforge report client-pack --input output/demo --output output/client_pack_redacted --redact-names --redact-amounts --exclude-raw-records --include-manifest-checksums
```

## Outputs Generated

- `management_pack.xlsx`
- `executive_report.html`
- `dashboard.html`
- `summary.md`
- `review_state.json`
- `review_register.xlsx`
- `evidence/`
- `client_pack/`
- optional `files_manifest.json` with SHA-256 checksums when requested

## How To Reproduce With Sample Data

1. Clone the repository.
2. Install ReconForge locally.
3. Run `reconforge demo run --output output/demo`.
4. Open `output/demo/executive_report.html`.
5. Open `output/demo/evidence/index.html`.
6. Start Studio with `reconforge studio --input examples/sample_data --output output/demo`.
7. Generate a client pack with redaction controls if the pack will be shared outside the immediate review team.

## What The Case Study Proves

- The local sample workflow can generate reconciliation reports, review state, evidence, and a handoff pack.
- Studio review statuses can be updated locally.
- The evidence pack can be organized with integrity manifests.

## What The Case Study Does Not Prove

- It does not prove live ERP integration.
- It does not prove production readiness for regulated environments.
- It does not prove savings or audit outcomes.

## Sample Findings

The following examples are illustrative and based on sample data:

- Stock movement without matching GL posting.
- GL posting without matching stock movement.
- WIP items that remain open for review.
- Direct purchase fitting cases requiring evidence.
- Old-part return gaps for controlled spare-part categories.
- Exceptions moved from `New` to `Under Review`, `Accepted Risk`, or `Escalated`.

## Example Exceptions

| Exception | Business Meaning | Example Reviewer Action |
| --- | --- | --- |
| Stock without GL | A stock movement has no matching accounting line. | Check posting date, source document, and account mapping. |
| GL without stock | A GL line has no matching stock evidence. | Trace journal reference and approval evidence. |
| Old part not returned | Controlled part issue lacks return evidence. | Confirm return, scrap, customer retention, or exception rationale. |
| Aged WIP | Work order remains open or costed for too long. | Assign owner for closure, billing, provisioning, or explanation. |

## Review Workflow

Reviewers update local exception status in Studio:

- New
- Under Review
- Resolved
- Accepted Risk
- Escalated

The review state is stored in `output/demo/review_state.json`. The review register can be exported to `review_register.xlsx`.

## Management Recommendations

- Review high and critical exceptions first.
- Confirm ERP export completeness and period scope before concluding on results.
- Assign unresolved exceptions to finance, stores, workshop, or ERP owners.
- Document accepted risks with a reason and owner.
- Rerun ReconForge after source corrections or updated exports.
- Treat evidence folders as sensitive until approved for sharing.

## Privacy Note

This scenario uses sample data. In a real pilot, client exports should stay local unless the client explicitly approves sharing. Evidence folders may contain source-record extracts and should be reviewed before external handoff.

## What Was Not Claimed

- No real customer result is claimed.
- No financial savings are claimed.
- No audit opinion is claimed.
- No live Odoo or SAP connector is claimed.
- No hosted or authenticated workflow is claimed.
- No production adoption is claimed.
