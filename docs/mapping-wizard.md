# Mapping Wizard

The mapping wizard is a local import helper for CSV/XLSX ERP exports. It compares the headers in an input folder against a ReconForge mapping profile and writes a draft report.

It does not connect to Odoo, SAP, or any live ERP system. It does not modify user files. It is a file-based helper for export adaptation.

## Command

```bash
reconforge mappings wizard --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/mapping_wizard
```

The non-interactive inspection command writes the same reports:

```bash
reconforge mappings inspect --input examples/sample_data --pack control-packs/sap-mb51-fagll03 --output output/mapping_wizard
```

## Outputs

- `mapping_report.md`
- `mapping_report.json`

## What It Checks

For each mapped dataset in `mapping.yml`, ReconForge reports:

- available input file and headers
- matched canonical fields
- missing required fields
- missing optional mapped fields
- unknown fields in the export
- simple candidate mapping suggestions based on normalized column names

## How To Use The Report

1. Export CSV/XLSX files from the ERP for the same company and period.
2. Place them in a local folder.
3. Run `reconforge mappings wizard`.
4. Review missing required fields first.
5. Use suggestions as a starting point, not as automatic truth.
6. Update client export templates or mapping documentation as needed.
7. Run `reconforge mappings validate --pack ...` after profile edits.

## Limitations

- Suggestions are based on names, not semantic ERP metadata.
- The helper does not transform files or write a mapped dataset.
- A human reviewer must validate field meaning, sign conventions, dates, periods, and company scope.
- The workflow is export-based and local-first; direct connectors are not implemented.
