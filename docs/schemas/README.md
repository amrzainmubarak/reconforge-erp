# ReconForge Local File Schemas

These JSON Schema files document local workflow and report contracts. They are intended to help maintainers keep outputs stable before v1.0.

- `close_checklist.schema.json`
- `certification_metadata.schema.json`
- `variance_report.schema.json` (legacy/unversioned v1, exact-threshold v2, and ingress-policy v3)
- `anonymization_manifest.schema.json` (v1 implicit-legacy compatibility plus current v2 financial-input policy/digest boundary)
- `management_pack.schema.json` (v1/v2/v3 compatibility plus current v4 financial-input, record-identity, ambiguity, and single-currency policy provenance)
- `synthetic_generator_manifest.schema.json` (v1 implicit-legacy and current v2 generator/rate/currency/input policy plus output byte hashes)
- `rule_results.schema.json` (historical unversioned v1 plus current v2 pack/input/decision provenance and local digest verification)
- `period_comparison.schema.json` (historical unversioned v1 plus current v2 exact ingress, input-byte provenance, decision/artifact digests, and explicit invalid-value policy)
- `client_pack_manifest.schema.json` (historical unversioned v1 plus current strict-v2 redaction policy, source/output fingerprints, and manifest verification)
- `evidence_index.schema.json` (historical schema-v2 score decisions plus current strict-v3 CSV ingress, source fingerprints, and decision/artifact digest verification)
- `file_ingestion_inventory.schema.json` (closed v1 file trust/format/entrypoint/parser/control/risk inventory plus exact direct-tabular and direct-PyYAML parser allowlists)
- `database_backup.schema.json` and `database_backup_manifest.schema.json` (closed current-writer local restore contracts; unkeyed integrity metadata, not authentication or DR assurance)
- `database_account_reconciliations_import.schema.json` and `database_control_tests_import.schema.json` (bounded legacy direct-list/single-envelope/keyed-map DB import compatibility shapes; individual record fields remain open)
- `security_architecture.schema.json` (closed v2 trust-boundary, edition, data-classification, control-ownership, evidence, and residual-risk registry)
- `threat_model_index.schema.json` (closed v1 active-module asset, actor, trust-boundary, threat-case, control, test, owner, assumption, and limitation index)
- `asvs_mapping.schema.json` (closed v1 official-source-pinned ASVS 5.0.0 all-chapter selected-requirement evidence mapping with explicit unassessed coverage)
- `ssdf_mapping.schema.json` (closed v1 final-NIST-source-pinned SSDF 1.1 all-task repository evidence/gap mapping with owners and review cadence)
- `slsa_provenance_plan.schema.json` (closed v1 Approved-SLSA-1.2-pinned artifact/builder/attestation/verification/rollback implementation plan with both tracks unevaluated)
- `release_manifest.schema.json` (closed v1 source/wheel/sdist/digest-addressed-image candidate identity and verification contract; not a signature or publication record)
- `sbom_manifest.schema.json` (closed v1 per-subject CycloneDX 1.7 identity, Python declarations, source npm-lock inventory, image-scan generator, digest, completeness, and verification contract; not a vulnerability or license assessment)
- `engine_parity_matrix.schema.json` (reviewed Python/Pandas/DuckDB lower/current CI contract; configuration is not execution evidence)
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
- `currency_registry.schema.json` (offline currency precision/rounding policies and registry provenance)
- `sqlite_matching_rule.schema.json` (bounded recursive SQLite matching-rule object; historical spaced canonical text remains compatible)
- `redis_session.schema.json` (closed bounded tenant-scoped Redis session metadata; token digests only and explicit UTC expiry)
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
