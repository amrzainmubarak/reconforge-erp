"""Unit tests for Phase 2 deliverables (Evidence Graph, Recon-as-Code, Arabic/RTL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.evidence.graph import EvidenceGraph, EvidenceGraphNode
from reconforge.rules.recon_as_code import ReconciliationAsCodeSpec
from reconforge.utils.rtl import (
    contains_arabic_text,
    detect_direction,
    format_rtl_html_attributes,
    normalize_arabic_numbers,
)

RECONCILIATION_AS_CODE_FIXTURE = """
schema_version: "1.0.0"
reconciliation_id: "bank_to_gl_monthly"
title: "Bank Statement vs GL Reconciliation"
description: "Synthetic monthly close control pack"
sources:
  - name: "bank_statement"
    format: "csv"
    schema_version: "1.0.0"
    required_columns: ["id", "amount", "date", "reference", "currency"]
    identifier_column: "id"
  - name: "general_ledger"
    format: "csv"
    schema_version: "1.0.0"
    required_columns: ["id", "amount", "date", "reference", "currency"]
    identifier_column: "id"
canonical_mapping:
  id: "record_id"
  amount: "amount"
  date: "business_date"
  reference: "reference"
  currency: "currency"
matching_strategies:
  - name: "exact-match"
    strategy_type: "exact_1to1"
    amount_tolerance: "0.00"
    date_tolerance_days: 0
evidence_requirements:
  - id: "decision-lineage"
    node_types: ["source_record", "match_decision", "rule_version"]
    minimum_count: 3
    required_for_status: "all"
test_cases:
  - id: "exact-pair"
    description: "One synthetic deterministic USD pair"
    strategy: "exact-match"
    left_records:
      - id: "L-001"
        amount: "10.00"
        date: "2026-01-01"
        reference: "REF-001"
        currency: "USD"
    right_records:
      - id: "R-001"
        amount: "10.00"
        date: "2026-01-01"
        reference: "REF-001"
        currency: "USD"
    expected_result: "exact-pair"
expected_results:
  exact-pair:
    matched_count: 1
    unmatched_left_count: 0
    unmatched_right_count: 0
    ambiguous_count: 0
"""


def test_evidence_graph_lineage_and_manifest() -> None:
    graph = EvidenceGraph(graph_id="GRAPH-001", workspace_id="alpha")

    # Nodes
    file_node = EvidenceGraphNode(
        id="FILE-001",
        node_type="source_file",
        label="bank_statement.csv",
        payload={"filename": "bank_statement.csv", "checksum": "abc123hash"},
    )
    rec_node = EvidenceGraphNode(
        id="REC-001",
        node_type="source_record",
        label="TXN-1001",
        payload={"amount": "1500.00", "date": "2026-01-10"},
    )
    match_node = EvidenceGraphNode(
        id="MATCH-001",
        node_type="match_decision",
        label="Level 1 Exact Match",
        payload={"score": "1.0"},
    )

    graph.add_node(file_node)
    graph.add_node(rec_node)
    graph.add_node(match_node)

    # Edges
    graph.add_edge("REC-001", "FILE-001", "derived_from")
    graph.add_edge("MATCH-001", "REC-001", "matched_to")

    manifest = graph.compute_manifest_hash()
    assert len(manifest) == 64
    assert graph.manifest_hash == manifest

    payload = graph.to_payload()
    schema = json.loads((Path("docs/schemas/evidence_graph.schema.json")).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    assert payload["graph_id"] == "GRAPH-001"
    assert payload["schema_version"] == "1.0"
    assert "nodes" in payload and "edges" in payload
    assert payload["manifest_hash"] == manifest

    # Trace lineage
    lineage = graph.trace_lineage("MATCH-001")
    lineage_ids = {n.id for n in lineage}
    assert "FILE-001" in lineage_ids
    assert "REC-001" in lineage_ids
    assert "MATCH-001" in lineage_ids


def test_evidence_graph_manifest_tamper_detection() -> None:
    graph = EvidenceGraph(graph_id="GRAPH-002")
    file_node = EvidenceGraphNode(
        id="FILE-002",
        node_type="source_file",
        label="source.csv",
        payload={"sha256": "abc123"},
    )
    match_node = EvidenceGraphNode(
        id="MATCH-002",
        node_type="match_decision",
        label="Matched",
        payload={"amount": "100.00"},
    )
    graph.add_node(file_node)
    graph.add_node(match_node)
    graph.add_edge("MATCH-002", "FILE-002", "matched_to")

    expected = graph.compute_manifest_hash()

    graph.nodes["FILE-002"].payload["sha256"] = "tampered"

    with pytest.raises(ValueError, match="Manifest hash mismatch"):
        graph.verify_manifest_hash(expected)


def test_evidence_graph_redaction_preserves_lineage() -> None:
    graph = EvidenceGraph(graph_id="GRAPH-003")
    sensitive_node = EvidenceGraphNode(
        id="NODE-001",
        node_type="source_record",
        label="record",
        payload={
            "account_number": "IBAN12345",
            "amount": "42.00",
            "customer": {"name": "Acme Inc", "id": "cust-1"},
        },
        redaction_mask=["account_number", "customer.id"],
    )
    graph.add_node(sensitive_node)

    normal_payload = graph.to_payload()
    redacted_payload = graph.to_payload(redact=True)

    assert normal_payload["nodes"]["NODE-001"]["payload"]["account_number"] == "IBAN12345"
    assert normal_payload["nodes"]["NODE-001"]["payload"]["customer"]["id"] == "cust-1"
    assert redacted_payload["nodes"]["NODE-001"]["payload"]["account_number"] == "***redacted***"
    assert redacted_payload["nodes"]["NODE-001"]["payload"]["customer"]["id"] == "***redacted***"
    assert redacted_payload["nodes"]["NODE-001"]["payload"]["amount"] == "42.00"

    schema = json.loads((Path("docs/schemas/evidence_graph.schema.json")).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(redacted_payload)


def test_reconciliation_as_code_yaml_parsing() -> None:
    yaml_text = """
schema_version: "1.0.0"
reconciliation_id: "bank_to_gl_monthly"
title: "Bank Statement vs GL Reconciliation"
description: "Monthly close control pack"
sources:
  - name: "bank_statement"
    format: "csv"
    identifier_column: "txn_id"
canonical_mapping:
  txn_id: "move_id"
  amount: "total_cost"
matching_strategies:
  - name: "Exact Match"
    strategy_type: "exact_1to1"
    amount_tolerance: "0.00"
"""
    spec = ReconciliationAsCodeSpec.from_yaml(yaml_text)
    assert spec.reconciliation_id == "bank_to_gl_monthly"
    assert spec.title == "Bank Statement vs GL Reconciliation"
    assert len(spec.sources) == 1
    assert spec.sources[0].name == "bank_statement"
    assert len(spec.matching_strategies) == 1
    assert spec.matching_strategies[0].strategy_type == "exact_1to1"

    # Roundtrip YAML serialization
    output_yaml = spec.to_yaml()
    assert "bank_to_gl_monthly" in output_yaml


def test_reconciliation_as_code_schema_digest_lint_simulation_and_diff() -> None:
    spec = ReconciliationAsCodeSpec.from_yaml(RECONCILIATION_AS_CODE_FIXTURE)
    schema = json.loads(Path("docs/schemas/reconciliation_as_code.schema.json").read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(spec.canonical_document())
    assert len(spec.content_digest()) == 64
    assert ReconciliationAsCodeSpec.from_json(spec.to_json()).content_digest() == spec.content_digest()
    assert not [finding for finding in spec.lint() if finding["severity"] == "error"]
    assert spec.simulation_plan()["side_effects"] == "none"

    first = spec.run_embedded_tests()
    second = spec.run_embedded_tests()
    assert first["all_passed"] is True
    assert first["passed_count"] == 1
    assert first["results"][0]["actual"]["decision_digest"] == second["results"][0]["actual"]["decision_digest"]

    candidate = ReconciliationAsCodeSpec.from_yaml(
        RECONCILIATION_AS_CODE_FIXTURE.replace('amount_tolerance: "0.00"', 'amount_tolerance: "0.01"')
    )
    changes = spec.diff(candidate)
    assert changes == [
        {
            "operation": "replace",
            "path": "$.matching_strategies[0].amount_tolerance",
            "before": "0.00",
            "after": "0.01",
        }
    ]


def test_reconciliation_as_code_rejects_executable_hooks_and_unsafe_money() -> None:
    executable = RECONCILIATION_AS_CODE_FIXTURE + '\nscript: "run.py"\n'
    scientific = RECONCILIATION_AS_CODE_FIXTURE.replace('amount_tolerance: "0.00"', 'amount_tolerance: "1e-2"')

    with pytest.raises(ValueError, match="Executable hook field is forbidden"):
        ReconciliationAsCodeSpec.from_yaml(executable)
    with pytest.raises(ValueError, match="plain decimal string"):
        ReconciliationAsCodeSpec.from_yaml(scientific)


def test_arabic_rtl_utilities() -> None:
    arabic_sample = "مطابقة الحسابات المالية"
    english_sample = "Financial Account Reconciliation"

    assert contains_arabic_text(arabic_sample) is True
    assert contains_arabic_text(english_sample) is False

    assert detect_direction(arabic_sample) == "rtl"
    assert detect_direction(english_sample) == "ltr"

    assert 'dir="rtl" lang="ar"' in format_rtl_html_attributes(arabic_sample)
    assert 'dir="ltr" lang="en"' in format_rtl_html_attributes(english_sample)

    eastern_digits = "المبلغ الإجمالي: ١٢٥٠.٥٠"
    normalized = normalize_arabic_numbers(eastern_digits)
    assert "1250.50" in normalized
