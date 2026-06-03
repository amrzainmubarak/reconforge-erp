# Sample Commands

```bash
reconforge validate examples/sample_data
reconforge mappings validate --pack control-packs/dynamics-inventory-gl
reconforge rules validate --pack control-packs/dynamics-inventory-gl
reconforge rules run --input examples/sample_data --pack control-packs/dynamics-inventory-gl --output output/rules-dynamics
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output/dynamics-stock-gl
```

This workflow is export-based and local-first. It does not upload ERP data and does not use a direct Microsoft Dynamics connector.
