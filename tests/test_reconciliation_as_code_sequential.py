from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from reconforge.rules.recon_as_code import ReconciliationAsCodeSpec

_SEQUENTIAL_RAC = """
schema_version: "1.0.0"
reconciliation_id: "sequential-controls"
title: "Sequential matching controls"
description: "Bounded carry-forward and reversal pairing simulations"
sources:
  - name: "obligations"
    format: "json"
    identifier_column: "id"
  - name: "settlements"
    format: "json"
    identifier_column: "id"
canonical_mapping:
  id: "id"
  amount: "amount"
  date: "date"
matching_strategies:
  - name: "FIFO carry forward"
    strategy_type: "carry_forward"
    mode: "carry-forward"
    date_tolerance_days: 30
  - name: "Explicit reversal pairing"
    strategy_type: "reversal_pairing"
    mode: "reversal-pairing"
    amount_tolerance: "0.01"
    date_tolerance_days: 30
test_cases:
  - id: "carry-case"
    description: "A settlement is allocated FIFO and leaves a visible obligation residual"
    strategy: "fifo-carry-forward"
    left_records:
      - {id: "O1", amount: "100", date: "2026-01-01", currency: "USD", partition: "P1"}
      - {id: "O2", amount: "50", date: "2026-01-02", currency: "USD", partition: "P1"}
    right_records:
      - {id: "S1", amount: "120", date: "2026-01-03", currency: "USD", partition: "P1"}
    expected_result: "carry-result"
  - id: "reversal-case"
    description: "An explicit opposite-sign reversal link is paired once"
    strategy: "explicit-reversal-pairing"
    left_records:
      - {id: "J1", amount: "100", date: "2026-01-01", currency: "USD", partition: "P1"}
    right_records:
      - {id: "R1", amount: "-100", date: "2026-01-02", currency: "USD", partition: "P1", reversal_of: "J1"}
    expected_result: "reversal-result"
expected_results:
  carry-result:
    matched_count: 2
    unmatched_left_count: 1
    unmatched_right_count: 0
  reversal-result:
    matched_count: 1
    unmatched_left_count: 0
    unmatched_right_count: 0
workflow:
  requires_human_approval: true
  autonomous_financial_approval: false
  maker_checker: true
"""


def test_reconciliation_as_code_executes_sequential_strategies() -> None:
    spec = ReconciliationAsCodeSpec.from_yaml(_SEQUENTIAL_RAC)
    result = spec.run_embedded_tests()

    assert result["all_passed"] is True
    assert result["passed_count"] == 2
    assert [item["strategy_id"] for item in result["results"]] == [
        "bounded-carry-forward-fifo",
        "bounded-reversal-pairing",
    ]
    assert all(len(str(item["actual"]["decision_digest"])) == 64 for item in result["results"])


def test_reconciliation_as_code_sequential_schema_is_closed() -> None:
    spec = ReconciliationAsCodeSpec.from_yaml(_SEQUENTIAL_RAC)
    schema = json.loads(Path("docs/schemas/reconciliation_as_code.schema.json").read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(spec.canonical_document())
    assert spec.simulation_plan()["steps"]["matching"] == [
        {
            "name": "fifo-carry-forward",
            "strategy_id": "bounded-carry-forward-fifo",
            "strategy_version": "1.0.0",
            "mode": "carry-forward",
        },
        {
            "name": "explicit-reversal-pairing",
            "strategy_id": "bounded-reversal-pairing",
            "strategy_version": "1.0.0",
            "mode": "reversal-pairing",
        },
    ]


def test_reconciliation_as_code_rejects_wrong_sequential_adapter() -> None:
    invalid = _SEQUENTIAL_RAC.replace(
        'strategy_type: "reversal_pairing"',
        'strategy_type: "reversal_pairing"\n    strategy_id: "bounded-carry-forward-fifo"',
    )

    try:
        ReconciliationAsCodeSpec.from_yaml(invalid)
    except ValueError as exc:
        assert "Sequential matching modes" in str(exc)
    else:
        raise AssertionError("wrong sequential adapter must fail closed")
