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

The workbook includes trend sheets for period counts, review progress, and top recurring themes where available.

Current CLI output uses `strict-financial-input-v2`. Exception CSV fields stay
as text until Decimal validation, so binary floating-point inference cannot
change a comparison decision. The workbook records the policy and decision
digest in `Report Parameters`; HTML and Markdown also display the policy.

The current JSON contract is schema v2. It records the comparison and rounding
policy, sorted SHA-256/byte fingerprints for recognized input CSVs and
`review_state.json`, a path-independent `decision_digest`, and a complete
`artifact_digest`. Historical unversioned JSON remains readable as v1 but is
reported as `legacy-unverified`; it has no policy or input provenance.

Python callers can use `read_period_comparison` to read v1/v2 and
`verify_period_comparison_payload` to verify v2. Passing the original period
paths to the verifier additionally rechecks their current bytes against the
recorded input fingerprints.

## Categories

- New exceptions: present in the final period and absent from earlier periods.
- Recurring exceptions: present in the final period and at least one earlier period.
- Resolved exceptions: present in an earlier period and absent from the final period.
- Escalated exceptions: final-period exceptions marked `Escalated`.
- Accepted risk items: final-period exceptions marked `Accepted Risk`.

## Trend Summary

The comparison also reports:

- new, recurring, and resolved counts by period
- high/critical exception counts
- review completion percentage where review state exists
- accepted risk count
- escalated count
- top recurring themes from exception type, rule name, or source file
- JSON chart data for lightweight downstream dashboards

## Matching Logic

ReconForge uses `exception_id` when it appears to be a stable business identifier. Synthetic row-position IDs such as `EXC-0001` are not treated as stable across periods by themselves.

When a stable ID is unavailable, ReconForge creates a deterministic fallback fingerprint from available business fields such as source file, exception type, rule/control ID, reference, source document, work order, product/item/customer, amount, and date.

The current strict fallback rounds valid amounts to two fractional digits with
`ROUND_HALF_UP` for compatibility with the historical comparison rule. Missing,
malformed, and valid-zero amounts have distinct fingerprint values. The direct
Python API defaults to the explicit legacy-v1 reader during its compatibility
window; current CLI and demo calls select strict v2 explicitly.

## Limitations

- The report does not infer financial savings.
- Fallback matching can be imperfect if references or amounts change between periods.
- The command compares generated local outputs; it does not run reconciliation for each period automatically.
- Review completion trends depend on local `review_state.json` files being present and aligned with generated exceptions.
- The input and artifact hashes provide local integrity checks only. They are
  not signatures, audit opinions, compliance certifications, or proof that a
  source system is authentic.
- Currency-specific comparison identity is not yet implemented; callers should
  not interpret the two-fractional-digit fingerprint rule as a universal
  currency precision policy.
