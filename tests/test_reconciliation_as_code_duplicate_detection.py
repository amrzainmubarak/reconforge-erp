from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.rules.recon_as_code import ReconciliationAsCodeSpec

_DUPLICATE_RAC = """
schema_version: "1.0.0"
reconciliation_id: "duplicate-rac"
title: "Duplicate evidence"
sources:
  - name: "ledger"
    format: "json"
    identifier_column: "id"
  - name: "statement"
    format: "json"
    identifier_column: "id"
canonical_mapping:
  amount: "amount"
matching_strategies:
  - name: "duplicate-fingerprint"
    strategy_type: "duplicate_detection"
    strategy_id: "bounded-duplicate-detection"
    mode: "duplicate-detection"
    exact_fields: ["amount", "date", "reference", "currency", "partition"]
test_cases:
  - id: "duplicate-case"
    strategy: "duplicate-fingerprint"
    expected_result: "one-duplicate-group"
    left_records:
      - {id: "L-2", amount: "10.00", date: "2026-01-01", reference: "INV-1", currency: "USD", partition: "AR"}
      - {id: "L-1", amount: "10", date: "2026-01-01", reference: "INV-1", currency: "USD", partition: "AR"}
    right_records:
      - {id: "R-1", amount: "20", date: "2026-01-01", reference: "SET-1", currency: "USD", partition: "BANK"}
expected_results:
  one-duplicate-group:
    matched_count: 0
    unmatched_left_count: 0
    unmatched_right_count: 0
    ambiguous_count: 0
    duplicate_group_count: 1
    decision_digest: ""
"""


def test_reconciliation_as_code_executes_duplicate_detection_adapter() -> None:
    spec = ReconciliationAsCodeSpec.from_yaml(_DUPLICATE_RAC)
    result = spec.run_embedded_tests()

    assert result["all_passed"] is True
    assert result["results"][0]["strategy_id"] == "bounded-duplicate-detection"
    actual = result["results"][0]["actual"]
    assert actual["duplicate_group_count"] == 1
    assert actual["matched_count"] == 0


def test_reconciliation_as_code_duplicate_document_matches_closed_schema() -> None:
    spec = ReconciliationAsCodeSpec.from_yaml(_DUPLICATE_RAC)
    schema = json.loads(Path("docs/schemas/reconciliation_as_code.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(spec.canonical_document())
    legacy_document = spec.canonical_document()
    for expected in legacy_document["expected_results"].values():
        expected.pop("duplicate_group_count", None)
    Draft202012Validator(schema).validate(legacy_document)


def test_reconciliation_as_code_rejects_duplicate_strategy_id_mismatch() -> None:
    with pytest.raises(ValueError, match="Duplicate-detection mode requires"):
        ReconciliationAsCodeSpec.from_yaml(_DUPLICATE_RAC.replace(
            'strategy_id: "bounded-duplicate-detection"',
            'strategy_id: "indexed-composite-one-to-one"',
        ))
