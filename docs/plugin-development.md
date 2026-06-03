# Plugin Development

ReconForge ERP includes a plugin foundation for local export adapters. Current adapters are export-oriented and do not connect to live ERP systems.

## Export Adapter Interface

Export adapters implement:

- `load_data`
- `validate_schema`
- `normalize_columns`
- `map_accounts`
- `export_results`

## Current Foundations

- `generic_csv`
- `odoo_export`
- `sap_export`

## Future Export Profile Roadmap

- Additional Odoo export helpers.
- SAP export template adapter.
- ERPNext CSV/XLSX adapter.
- NetSuite CSV adapter.
- Dynamics CSV adapter.

## Design Rule

Adapters should map exported data into the canonical ReconForge schema before reconciliation. Reconciliation logic should remain ERP-neutral. Do not describe these adapters as direct ERP connectors unless a live credentialed integration is explicitly implemented and documented.
