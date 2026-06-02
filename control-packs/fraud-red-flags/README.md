# Fraud Red Flags Control Pack

## Target User

Internal auditors, fraud risk reviewers, and finance controllers.

## Business Problem

Duplicate references and unsupported manual journals can indicate weak controls, duplicate postings, or fraud red flags.

## Required Input Files

- `gl_entries.csv`
- `stock_moves.csv`

## Checks Performed

- Duplicate GL references.
- Manual journals missing references.

## Common Exceptions

- Reused reference across GL entries.
- Manual entry without source document.

## Risk Model

Unsupported manual journals are Critical. Duplicate GL references are High until explained.

## Recommended Workflow

Run after GL extraction and before audit evidence binder generation.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/fraud-red-flags --output output/rules-fraud
```

## Interpretation Guide

Red flags are not proof of fraud. They identify transactions requiring evidence, explanation, and independent review.
