# Report Samples

Run the sample management pack:

```bash
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
```

## Excel Sheets

| Sheet | Purpose |
| --- | --- |
| Executive Summary | KPI-level values for management review |
| Reconciliation Summary | Counts by stock/GL matching and exception category |
| Stock vs GL Mismatch | Unmatched and mismatched stock/GL records |
| Work Order Exceptions | Workshop and stores control exceptions |
| WIP Aging | Open WIP work orders with owner and bucket |
| WIP Aging Summary | Aging bucket count and value |
| Risk Scoring | Exception count by risk level |
| Recommended Actions | Owner-focused follow-up actions |
| Audit Log | Report parameters and local processing evidence |

## Companion Outputs

- CSV files for each exception category
- JSON records for integrations and downstream analysis
- Markdown summary for audit workpapers
- HTML dashboard for quick local review

## Currency and amount policy

The management pack is a single-currency report. `output_currency` must resolve
through the versioned offline Currency Registry, and explicit currencies in the
reconciliation/report rows must match it. ReconForge stops before writing the
pack if a different currency is present because this path has no implicit FX
conversion.

Monetary KPI rows include currency, minor units, rounding policy, and currency
policy digest. Schema-v3 `management_pack.json` (documented by
`docs/schemas/management_pack.schema.json`) records the applied strict or legacy
financial-input policy, the `canonical-multiset-occurrence-v1` record-identity
policy, and the registry version/digest,
the `single-currency-only-no-implicit-fx` aggregation rule, and the current
compatibility rule that rows without an explicit currency inherit
`output_currency`. Sums use exact Decimal arithmetic; registry rounding is an
output-display step, not a reconciliation decision.

The same schema remains a compatibility reader for historical schema-v1 and v2
files. V1 is valid only without financial-input or record-identity policy; v2
requires the financial-input policy and rejects a record-identity field it did
not historically contain. Older artifacts are never silently relabeled.

`unquantified_exception_count`, `unquantified_wip_count`, and the grouped
`unquantified_amount_count` fields expose rows whose amount/cost cannot be
measured. Those rows are excluded from value totals and are not converted to
valid zero amounts.

## Reading the Risk Columns

`risk_score` is numeric from 0 to 100. `risk_level` is Low, Medium, High, or Critical. Scores are not a substitute for professional judgment; they prioritize review work.
