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

## Reading the Risk Columns

`risk_score` is numeric from 0 to 100. `risk_level` is Low, Medium, High, or Critical. Scores are not a substitute for professional judgment; they prioritize review work.
