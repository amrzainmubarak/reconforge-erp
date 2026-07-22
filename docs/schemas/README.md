# ReconForge Local File Schemas

These JSON Schema files document local workflow and report contracts. They are intended to help maintainers keep outputs stable before v1.0.

- `close_checklist.schema.json`
- `certification_metadata.schema.json`
- `variance_report.schema.json`
- `control_matrix.schema.json`
- `profile_template.schema.json`
- `enterprise_domain.schema.json`
- `audit_events.schema.json`
- `studio_overview.schema.json` (experimental synthetic-only executive overview, decision brief, governed domain scores, and entity readiness)
- `studio_exception_queue.schema.json` (experimental synthetic-only exception queue)
- `studio_evidence_binder.schema.json` (experimental synthetic-only evidence registry)
- `studio_inventory_control.schema.json` (experimental synthetic-only inventory control center)
- `module_registry.schema.json` (deterministic runtime capability metadata; planned-only work excluded)
- `organization_master_data.schema.json` (versioned, path-free local organization/fiscal reference snapshot)
- `ledger_entry_lines.schema.json` (strict local finance-core line input; service enforces balance and relationships)
- `finance_core_snapshot.schema.json` (bounded, path-free finance master and ledger-header snapshot)
- `ledger_control_trial_balance.schema.json` (validated local control-ledger aggregation)
- `inventory_movement_lines.schema.json` (strict local inventory movement-line input)
- `inventory_on_hand.schema.json` (exact quantities derived from Posted local movements)
- `inventory_control_exceptions.schema.json` (deterministic local inventory-control findings)
- `inventory_count_session.schema.json` (governed physical-count detail with exact immutable snapshot/result lines)
- `inventory_planning_snapshot.schema.json` (bounded local count-header and reorder-rule snapshot)
- `inventory_reorder_signals.schema.json` (deterministic exact reorder advice; no purchasing action)
- `inventory_core_snapshot.schema.json` (bounded, path-free inventory master and movement-header snapshot)
- `inventory_valuation_document.schema.json` (one FIFO valuation with exact inbound costs, lines, and immutable layer consumptions)
- `inventory_valuation_snapshot.schema.json` (bounded, path-free FIFO policies, document headers, and open layer balances)
- `inventory_valuation_reversal.schema.json` (one exact FIFO valuation reversal with immutable Restore/Remove layer effects)
- `inventory_valuation_reversal_snapshot.schema.json` (bounded, path-free reversal lifecycle and header snapshot)

The schemas describe local workflow files only. They do not define legal signatures, audit opinions, compliance certifications, direct ERP connectors, or SaaS workflows.

Generate the Studio bundle after the synthetic enterprise demo with `reconforge demo studio-data`, or generate the complete package and bundle with `reconforge demo showcase`. The bridge writes the overview, exception queue, evidence registry, and inventory control contracts beside one another. It accepts only marked synthetic demo artifacts, applies bounded input limits, and projects allowlisted scalar fields, including deterministic executive signals, exact FIFO valuations, reversal summaries, layer effects, and Finance Draft references. Runtime consistency checks tie the executive brief and control-domain scores back to governed metrics and distributions. Older valid demo packages without the optional inventory sample still produce an empty inventory contract. The marker is a local contract guard, not proof that independently edited files contain no sensitive data; users remain responsible for keeping demo inputs synthetic.
