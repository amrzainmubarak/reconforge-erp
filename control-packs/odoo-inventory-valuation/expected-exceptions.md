# Expected Exceptions

This pack is designed for real Odoo exports mapped into the ReconForge canonical schema. The default `examples/sample_data` folder is generic, so it may not trigger every Odoo-specific control.

Common expected exceptions in real Odoo mappings:

- Products missing stock valuation accounts.
- Products missing expense accounts.
- Stock valuation layers without a usable origin, reference, picking, or valuation description.
- Account move lines without a reference or source-document field.
- Product codes present in stock movement exports but absent from the product master export.
- Negative quantity and positive valuation sign mismatches caused by return or export mapping conventions.
- High-value stock valuation movements requiring manual evidence review.

Recommended reviewer classification:

- True configuration issue.
- Mapping issue.
- Timing difference.
- Accepted risk.
- Resolved after source export correction.
