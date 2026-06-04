# Variance Analysis

ReconForge variance analysis compares numeric summary metrics from two local generated output folders. It is intended for controller review and exception triage, not for financial statement assurance.

The command does not infer savings, issue an audit opinion, provide legal/tax/compliance advice, or conclude that a balance is correct.

## Command

```bash
reconforge analyze variance --current output/feb --previous output/jan --output output/variance
```

Optional thresholds:

```bash
reconforge analyze variance \
  --current output/feb \
  --previous output/jan \
  --output output/variance \
  --amount-threshold 1000 \
  --percent-threshold 10
```

Outputs:

- `output/variance/variance_analysis.xlsx`
- `output/variance/variance_analysis.csv`
- `output/variance/variance_analysis.json`
- `output/variance/variance_analysis.html`
- `output/variance/variance_summary.md`

## Inputs

The command reads local ReconForge summary artifacts when present, including:

- `management_pack.json`
- `period_comparison.json`
- `close_report.json`
- `*summary.csv`
- `*control_value_summary.csv`

Each metric is compared by name. The output includes:

- Previous value
- Current value
- Amount variance
- Percentage variance
- Threshold flag
- Explanation placeholder

## Security Notes

- Inputs and outputs are local folders.
- The HTML report escapes rendered values.
- Malformed or missing summary inputs return controlled CLI errors.
- The command does not upload data or require an API key.
