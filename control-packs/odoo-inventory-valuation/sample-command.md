# Sample Commands

Validate the mapped canonical input folder:

```bash
reconforge validate examples/sample_data
```

Run stock-to-GL reconciliation locally:

```bash
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output/odoo-stock-gl
```

Validate and run the Odoo inventory valuation control pack:

```bash
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge rules validate --pack control-packs/odoo-inventory-valuation
reconforge rules list --pack control-packs/odoo-inventory-valuation
reconforge rules run --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/rules-odoo
reconforge rules explain --pack control-packs/odoo-inventory-valuation --rule ODOO-IV-003
```

Generate local evidence from reconciliation outputs:

```bash
reconforge report evidence-binder --input output/odoo-stock-gl --output output/odoo-evidence
```

This workflow is export-based. It does not upload ERP data and does not use a direct Odoo API connector.
