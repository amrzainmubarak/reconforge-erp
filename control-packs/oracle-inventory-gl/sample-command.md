# Sample Commands

Validate the export-based mapping profile:

```bash
reconforge mappings validate --pack control-packs/oracle-inventory-gl
```

Validate and run the rule pack against local exports:

```bash
reconforge rules validate --pack control-packs/oracle-inventory-gl
reconforge rules run --input examples/sample_data --pack control-packs/oracle-inventory-gl --output output/rules/oracle_inventory_gl
```

This profile uses local CSV/XLSX exports only. It does not create a direct Oracle connector.
