# CFO Executive Risk Review Playbook

## Target User

CFOs, finance directors, and senior controllers.

## Business Problem

Senior finance leaders need a concise view of financial control exposure across inventory, WIP, work orders, and GL.

## Required Data

Generated management pack, risk matrix, and evidence register.

## Command Sequence

```bash
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge report evidence-binder --input output --output output/evidence
```

## Expected Output

- `output/management_pack.xlsx`
- `output/executive_report.html`
- `output/evidence/evidence_register.xlsx`

## How To Read Exceptions

Start with Critical and High counts, unmatched value exposure, WIP older than 90 days, direct purchase-and-fit cases, and unsupported manual GL entries.

## Recommended Actions

Assign owners, set closure dates, confirm accounting impact, and track repeat issues across periods.

## Common Mistakes

- Looking only at totals.
- Accepting old WIP without closure plan.
- Treating operational controls as separate from financial reporting.

## Escalation Path

Unresolved Critical exceptions should be reviewed with internal audit and operations leadership.
