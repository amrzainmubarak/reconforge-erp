# Synthetic Case Study: SAP Export Reconciliation Pilot

This is a synthetic case study and illustrative scenario based on sample data. It does not describe a real customer, real savings, SAP certification, or a completed audit.

## Scenario

A workshop/fleet business exports SAP-style MB51 material movement rows and FAGLL03/FBL3N G/L line item rows. The internal audit director wants to test whether recurring unmatched movements, missing references, and high-value exceptions can be triaged locally before audit fieldwork.

## Data Inputs

- MB51-style material movement export mapped to `stock_moves.csv`.
- FAGLL03/FBL3N-style GL export mapped to `gl_entries.csv`.
- Material master export mapped to `products.csv`.
- Optional work-order and invoice exports.

## Commands Used

```bash
reconforge validate examples/sample_data
reconforge mappings validate --pack control-packs/sap-mb51-fagll03
reconforge mappings wizard --input examples/sample_data --pack control-packs/sap-mb51-fagll03 --output output/sap_mapping
reconforge demo run --output output/demo
reconforge compare periods --inputs output/demo output/demo --output output/period_comparison
```

## Sample Exceptions

- GL line missing both reference and source-document fields.
- Material movement missing product/material mapping.
- High-value material movement requiring evidence review.
- Recurring exception themes across period comparisons.

## Review Workflow

Reviewers classify each exception as:

- True posting issue.
- SAP layout/export issue.
- Mapping issue.
- Timing difference.
- Accepted risk.
- Resolved after corrected export.

## Management Recommendations

- Align company code, plant, storage location, account, and period scope across exports.
- Review high and critical exceptions first.
- Use evidence manifests to detect post-generation file changes.
- Document accepted risks with an owner and reason.

## What This Proves

The workflow can support an export-based SAP pilot using local files and deterministic reports.

## What This Does Not Prove

- It does not prove direct SAP integration.
- It is not SAP-certified.
- It does not certify financial statements.
- It does not replace audit judgment.
