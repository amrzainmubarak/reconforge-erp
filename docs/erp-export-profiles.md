# ERP Export Profiles

ReconForge supports export-based mapping profiles. These profiles help users map local CSV/XLSX exports into ReconForge canonical files. They are not direct ERP connectors.

## Available Profiles

| Profile | Folder | Intended Export Workflow |
| --- | --- | --- |
| Odoo Inventory Valuation | `control-packs/odoo-inventory-valuation` | Odoo stock, valuation, product, invoice, work-order, and account move line exports. |
| SAP MB51/FAGLL03 | `control-packs/sap-mb51-fagll03` | SAP MB51 material document and FAGLL03/FBL3N G/L line item exports. |
| ERPNext Stock Ledger vs GL | `control-packs/erpnext-stock-gl` | ERPNext stock ledger, GL entry, and item exports. |
| Microsoft Dynamics Inventory vs GL | `control-packs/dynamics-inventory-gl` | Dynamics inventory transaction, voucher/GL, and released product exports. |
| NetSuite Inventory vs GL | `control-packs/netsuite-inventory-gl` | NetSuite inventory activity, accounting line/GL impact, and item saved-search exports. |
| Oracle Inventory vs GL | `control-packs/oracle-inventory-gl` | Oracle-style inventory transaction, subledger accounting, general ledger, and item master exports. |

## Validate A Profile

```bash
reconforge mappings validate --pack control-packs/erpnext-stock-gl
reconforge mappings validate --pack control-packs/dynamics-inventory-gl
reconforge mappings validate --pack control-packs/netsuite-inventory-gl
reconforge mappings validate --pack control-packs/oracle-inventory-gl
```

## Inspect Local Headers

```bash
reconforge mappings wizard --input examples/sample_data --pack control-packs/erpnext-stock-gl --output output/mapping_wizard
```

## Generate A Generic Template

```bash
reconforge mappings profile-template --output output/profile_template
```

This writes `mapping_template.yml` and `profile_authoring_guide.md` for local export-based profile authoring. It does not create a direct connector.

## Boundaries

- ReconForge works with local exports supplied by the user.
- No direct Odoo, SAP, ERPNext, Microsoft Dynamics, NetSuite, or Oracle connector is implemented.
- Users are responsible for validating export scope, company/legal entity, period, currency, and field mappings.
- ReconForge outputs are decision-support artifacts and do not certify financial statements.
