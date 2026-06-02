# Plugin Development

ReconForge ERP includes a connector foundation for future ERP adapters. Current adapters are local export-oriented and do not connect to live ERP systems.

## Connector Interface

Connectors implement:

- `load_data`
- `validate_schema`
- `normalize_columns`
- `map_accounts`
- `export_results`

## Current Foundations

- `generic_csv`
- `odoo_export`
- `sap_export`

## Future Connector Roadmap

- Odoo read-only connector.
- SAP export template adapter.
- ERPNext connector.
- NetSuite CSV adapter.
- Dynamics CSV adapter.

## Design Rule

Connectors should map data into the canonical ReconForge schema before reconciliation. Reconciliation logic should remain ERP-neutral.
