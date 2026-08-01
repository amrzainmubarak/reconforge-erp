# ADR 0125: Evidence Graph v1 contract with manifest integrity and redaction

- Status: Accepted
- Date: 2026-07-27

## Context

Evidence lineage had a simple `EvidenceGraph` implementation with node/edge insertion and a
checksum that only included bare node IDs and relationship names. Governance now requires
the next slice to prove the complete graph contract: versioned envelope, stable hash
boundaries, redaction masking for sensitive payload fields, and tamper detection before
lineage reuse.

## Decision

Publish a versioned Evidence Graph contract and runtime behavior in `reconforge/evidence.graph`:

- Use a fixed artifact envelope with `artifact_type="reconforge-evidence-graph"` and
  `schema_version="1.0"`.
- Extend `EvidenceGraphNode` with `data_classification`, `retention_policy`, and a
  `redaction_mask` for deterministic payload masking.
- Compute deterministic node/edge hashes with stable key ordering and include edge metadata
  in the manifest material.
- Add `EvidenceGraph.to_payload(redact=...)` for exported payload views that keep lineage
  intact while allowing redacted payload redaction for constrained consumers.
- Add `EvidenceGraph.verify_manifest_hash(...)` to fail closed when manifest evidence
  changes without mutation control.
- Introduce `docs/schemas/evidence_graph.schema.json` to validate evidence-graph exports
  as an auditable artifact boundary.

## Consequence

E-115 closes P2-001 by adding a validated contract and tamper-evidence for graph
exports. `EvidenceGraph` now provides one canonical integrity boundary for node/edge
lineage and explicit redaction handling, and `test_phase2_deliverables.py` adds schema,
tamper, and redaction regression coverage.

## Reversibility

Schema evolution remains additive and additive payload fields are introduced through
versioned manifest updates and compatibility tests.
