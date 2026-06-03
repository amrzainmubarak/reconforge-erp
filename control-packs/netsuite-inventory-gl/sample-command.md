# Sample Commands

```bash
reconforge validate examples/sample_data
reconforge mappings validate --pack control-packs/netsuite-inventory-gl
reconforge rules validate --pack control-packs/netsuite-inventory-gl
reconforge rules run --input examples/sample_data --pack control-packs/netsuite-inventory-gl --output output/rules-netsuite
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output/netsuite-stock-gl
```

This workflow is export-based and local-first. It does not upload ERP data and does not use a direct NetSuite connector.
