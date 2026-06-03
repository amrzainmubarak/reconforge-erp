# ERPNext Stock Ledger vs GL Control Pack

This pack supports local, export-based review of ERPNext stock ledger and general ledger rows mapped into ReconForge canonical CSV files. It is not a direct ERPNext API connector and does not require cloud upload.

## Required Exports

- Stock Ledger or Stock Ledger Entry export for inventory movements.
- General Ledger or GL Entry export for accounting rows.
- Item master export for item-code validation and account configuration review.

## Local Workflow

1. Export ERPNext reports or list views to CSV/XLSX.
2. Map the columns into `stock_moves.csv`, `gl_entries.csv`, and `products.csv`.
3. Validate the mapping profile and source folder.
4. Run stock-to-GL reconciliation and this control pack locally.
5. Review exceptions, evidence, and client handoff outputs.

## Limitations

- Export-based only; no direct ERPNext connector is implemented.
- Users must confirm company, fiscal period, warehouse, and account scope.
- ReconForge does not issue an audit opinion or certify ERPNext configuration.
