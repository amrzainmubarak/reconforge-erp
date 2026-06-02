# External Auditor Evidence Review Playbook

## Target User

External auditors and audit support teams.

## Business Problem

Auditors need traceable evidence for inventory consumption, GL postings, WIP, and work-order exceptions.

## Required Data

Generated ReconForge outputs and evidence binder folders.

## Command Sequence

```bash
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge report evidence-binder --input output --output output/evidence
```

## Expected Output

- `output/evidence/index.html`
- `output/evidence/evidence_register.xlsx`
- `output/evidence/EXC-0001/summary.md`

## How To Read Exceptions

Review severity, risk score, affected work order, source records, match candidates, and triggered controls.

## Recommended Actions

Request management response, root cause, financial impact assessment, and closure evidence for High and Critical cases.

## Common Mistakes

- Treating an exception as a confirmed error before source review.
- Ignoring timing differences.
- Sharing live ERP data without anonymization.

## Escalation Path

Unresolved Critical exceptions should be escalated to finance leadership and internal audit.
