# Internal Auditor Exception Review Playbook

## Target User

Internal auditors, control reviewers, external audit support teams, and compliance analysts.

## Problem

Audit teams need repeatable evidence, not only spreadsheet totals. They need source records, triggered controls, match candidates, and recommended follow-up.

## Required Data

Use the standard export folder plus generated ReconForge outputs.

## Commands to Run

```bash
reconforge validate examples/sample_data
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge rules run --input examples/sample_data --pack control-packs/audit-basic --output output/rules
reconforge report evidence-binder --input output --output output/evidence
```

## Expected Outputs

- `output/evidence/EXC-0001/summary.md`
- `source_records.csv`
- `match_candidates.csv`
- `triggered_rules.yml`
- `recommended_action.md`
- `audit_trail.json`

## How to Interpret Exceptions

Review severity, risk score, business impact, source files, and affected work order. Use match candidates to determine whether the exception is unresolved or a documentation/mapping issue.

## Recommended Next Actions

- Select a sample of High and Critical cases for management response.
- Check whether exceptions are isolated or systematic.
- Ask finance and operations to attach explanations to evidence folders.
- Track recurring control failures across periods.

## Common Mistakes

- Treating unmatched records as proven errors before source review.
- Reviewing only the Excel report and ignoring evidence folders.
- Mixing live customer data into shared audit examples without anonymization.
