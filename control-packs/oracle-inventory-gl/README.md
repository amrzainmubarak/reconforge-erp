# Oracle Inventory to GL Export Controls

This control pack provides export-based mapping guidance and baseline controls for Oracle-style inventory and general ledger CSV/XLSX exports.

It is not a direct Oracle connector, API integration, vendor certification, partnership, endorsement, or ERP writeback workflow.

## Expected Local Exports

- Inventory transaction or cost accounting distribution export.
- General ledger journal line or subledger accounting line export.
- Item master export where available.

Keep ledger, inventory organization, account, currency, and accounting period scope consistent across exports.

## Commands

```bash
reconforge mappings validate --pack control-packs/oracle-inventory-gl
reconforge rules validate --pack control-packs/oracle-inventory-gl
reconforge rules run --input examples/sample_data --pack control-packs/oracle-inventory-gl --output output/rules/oracle_inventory_gl
```

Use sanitized or synthetic examples only. Do not commit customer, supplier, employee, invoice, asset, GL, or financial data.
