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

Threshold option text is parsed as a finite, non-negative Decimal. Scientific
notation is rejected at the CLI boundary. Decisions use the unrounded exact
amount variance and an exact cross-multiplied percentage comparison; the
two-decimal values shown in reports use explicit `ROUND_HALF_EVEN` display
rounding only. An amount threshold of `0` retains the legacy behavior of
disabling amount-based flags, while percentage comparison remains inclusive.

Outputs:

- `output/variance/variance_analysis.xlsx`
- `output/variance/variance_analysis.csv`
- `output/variance/variance_analysis.json`
- `output/variance/variance_analysis.html`
- `output/variance/variance_summary.md`

### JSON contract migration

New output uses variance report schema version 2. The existing numeric fields
remain available at:

- `thresholds.amount_threshold`
- `thresholds.percent_threshold`

They are written as exact JSON number lexemes without converting through a
binary float. Version-aware consumers should prefer `threshold_policy`, whose
canonical decimal strings, comparison/display semantics, and SHA-256 policy
digest are independently verifiable. Python consumers can use
`reconforge.variance.read_variance_thresholds()`; it also reads unversioned and
explicit-v1 artifacts whose legacy threshold values are numbers or strings.

The contract schema is documented in
`docs/schemas/variance_report.schema.json`. It accepts legacy v1 reports and
requires the canonical threshold policy for v2 reports. No database migration
is involved.

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
- Negative, malformed, non-finite, and scientific-notation threshold text is
  rejected before an output directory is created.
- Malformed or missing summary inputs return controlled CLI errors.
- The command does not upload data or require an API key.
