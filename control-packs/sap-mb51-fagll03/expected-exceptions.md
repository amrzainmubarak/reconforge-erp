# Expected Exceptions

This pack is designed for real SAP exports mapped into the ReconForge canonical schema. The default `examples/sample_data` folder is generic, so it may not trigger every SAP-specific control.

Common expected exceptions in real SAP mappings:

- FAGLL03/FBL3N lines missing both reference and source document.
- MB51 movements missing material number after layout export or mapping.
- MB51 movements missing movement type.
- MB51 materials absent from the mapped material master export.
- High-value material movements needing GL line evidence.
- High-value GL lines missing cost center, order, WBS, or other cost object.

Recommended reviewer classification:

- True posting or traceability issue.
- SAP layout/export issue.
- Mapping issue.
- Timing difference.
- Accepted risk.
- Resolved after corrected export or source review.
