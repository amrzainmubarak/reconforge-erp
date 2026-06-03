# Multi-Period Comparison

ReconForge can compare generated exception outputs from two or more local periods. This helps finance, audit, and operations teams see whether control issues are new, recurring, resolved, escalated, or accepted as risk.

## Command

```bash
reconforge compare periods --inputs output/jan output/feb --output output/period_comparison
```

Repeated `--inputs` also works:

```bash
reconforge compare periods --inputs output/jan --inputs output/feb --output output/period_comparison
```

## Inputs

Each input should be a generated ReconForge output folder containing exception CSVs such as:

- `stock_gl_all_exceptions.csv`
- `workorders_all_exceptions.csv`
- `management_pack_stock_gl_all_exceptions.csv`
- `management_pack_workorders_all_exceptions.csv`

If `review_state.json` exists in a period folder, the comparison includes review statuses such as `Escalated` and `Accepted Risk`.

## Outputs

- `period_comparison.xlsx`
- `period_comparison.html`
- `period_comparison.json`
- `period_comparison.md`

## Categories

- New exceptions: present in the final period and absent from earlier periods.
- Recurring exceptions: present in the final period and at least one earlier period.
- Resolved exceptions: present in an earlier period and absent from the final period.
- Escalated exceptions: final-period exceptions marked `Escalated`.
- Accepted risk items: final-period exceptions marked `Accepted Risk`.

## Matching Logic

ReconForge uses `exception_id` when available. If no exception ID exists, it creates a deterministic fallback key from available fields such as source file, exception type, reference, source document, work order, and amount.

## Limitations

- The report does not infer financial savings.
- Fallback matching can be imperfect if references or amounts change between periods.
- The command compares generated local outputs; it does not run reconciliation for each period automatically.
