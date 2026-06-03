# Sample Commands

Validate the mapped canonical input folder:

```bash
reconforge validate examples/sample_data
```

Run stock-to-GL reconciliation locally:

```bash
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output/sap-stock-gl
```

Validate and run the SAP MB51/FAGLL03 control pack:

```bash
reconforge mappings validate --pack control-packs/sap-mb51-fagll03
reconforge rules validate --pack control-packs/sap-mb51-fagll03
reconforge rules list --pack control-packs/sap-mb51-fagll03
reconforge rules run --input examples/sample_data --pack control-packs/sap-mb51-fagll03 --output output/rules-sap
reconforge rules explain --pack control-packs/sap-mb51-fagll03 --rule SAP-001
```

Generate local evidence from reconciliation outputs:

```bash
reconforge report evidence-binder --input output/sap-stock-gl --output output/sap-evidence
```

This workflow is export-based. It does not upload ERP data and does not use a direct SAP connector.
