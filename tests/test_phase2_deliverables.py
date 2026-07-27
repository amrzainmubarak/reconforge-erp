"""Unit tests for Phase 2 deliverables (Evidence Graph, Recon-as-Code, Arabic/RTL)."""

from __future__ import annotations

from reconforge.evidence.graph import EvidenceGraph, EvidenceGraphNode
from reconforge.rules.recon_as_code import ReconciliationAsCodeSpec
from reconforge.utils.rtl import (
    contains_arabic_text,
    detect_direction,
    format_rtl_html_attributes,
    normalize_arabic_numbers,
)


def test_evidence_graph_lineage_and_manifest() -> None:
    graph = EvidenceGraph(graph_id="GRAPH-001")

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
    graph.add_edge("rec-001".upper(), "file-001".upper(), "derived_from")
    graph.add_edge("match-001".upper(), "rec-001".upper(), "matched_to")

    manifest = graph.compute_manifest_hash()
    assert len(manifest) == 64  # SHA-256 hex string

    # Trace lineage
    lineage = graph.trace_lineage("MATCH-001")
    lineage_ids = {n.id for n in lineage}
    assert "FILE-001" in lineage_ids
    assert "REC-001" in lineage_ids
    assert "MATCH-001" in lineage_ids


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
