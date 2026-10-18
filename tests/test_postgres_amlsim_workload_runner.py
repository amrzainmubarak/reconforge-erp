"""The PostgreSQL workload oracle must detect incorrect persisted decisions."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from reconforge.benchmark.amlsim_reconciliation import load_amlsim_profile, parse_amlsim_sample

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("postgres_amlsim_verification", ROOT / ".github/scripts/verify_postgres_amlsim_reconciliation.py")
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
PROFILE = load_amlsim_profile(ROOT / "docs/validation/amlsim-workload.v1.yaml")
SOURCE_IDS = {row["source_id"] for row in parse_amlsim_sample((ROOT / "tests/fixtures/amlsim/tx.csv").read_bytes(), PROFILE)}


def _oracle_records() -> list[dict[str, Any]]:
    unmatched = {PROFILE.faults.missing_id, PROFILE.faults.changed_amount_id, PROFILE.faults.delayed_id}
    rows = [
        {"status": "Matched", "left_id": "L-" + identity, "right_id": "R-" + identity,
         "amount_difference": "0.000000000000000000", "date_difference_days": 0}
        for identity in sorted(SOURCE_IDS - unmatched)
    ]
    rows.extend({"status": "Unmatched", "left_id": "L-" + identity, "right_id": ""} for identity in sorted(unmatched))
    rows.extend({"status": "Unmatched", "left_id": "", "right_id": "R-" + identity} for identity in (PROFILE.faults.changed_amount_id, PROFILE.faults.delayed_id, PROFILE.faults.duplicate_id + "-duplicate"))
    return rows


def test_independent_worker_oracle_accepts_fault_derived_expected_pairs() -> None:
    assert RUNNER.assert_oracle(_oracle_records(), PROFILE, SOURCE_IDS)["oracle_passed"] is True


@pytest.mark.parametrize("mutation", ["extra", "drop", "wrong_pair", "foreign_id", "reuse", "amount", "late", "wrong_unmatched"])
def test_independent_worker_oracle_rejects_bad_decisions(mutation: str) -> None:
    rows = _oracle_records()
    if mutation == "extra":
        rows.append(deepcopy(rows[0]))
    elif mutation == "drop":
        rows.pop()
    elif mutation == "wrong_pair":
        rows[0]["right_id"], rows[1]["right_id"] = rows[1]["right_id"], rows[0]["right_id"]
    elif mutation == "foreign_id":
        rows[0].update(left_id="L-forged", right_id="R-forged")
    elif mutation == "reuse":
        rows[0]["right_id"] = rows[1]["right_id"]
    elif mutation == "amount":
        rows[0]["amount_difference"] = "0.000000000000000001"
    elif mutation == "late":
        rows[0]["date_difference_days"] = 1
    else:
        rows[-1]["right_id"] = "R-forged"
    with pytest.raises(ValueError):
        RUNNER.assert_oracle(rows, PROFILE, SOURCE_IDS)


def test_decision_digest_projection_retains_financial_values_and_full_lineage() -> None:
    row = {
        "left_id": "L-1", "right_id": "R-1", "match_type": "Exact", "confidence": "1",
        "explanation": "Exact", "amount_difference": "0", "date_difference_days": 0,
        "status": "Matched", "reason_code": "", "lineage_json": {"constraint_policy": "strict-one-to-one-v1", "rejections": [{"reason": "late"}]},
        "run_id": "volatile-run", "created_at": "volatile-time", "id": "volatile-row",
    }
    projected = RUNNER.decision_projection([row])[0]
    assert {"run_id", "created_at", "id"}.isdisjoint(projected)
    assert projected["lineage_json"] == row["lineage_json"]
    assert projected["amount_difference"] == row["amount_difference"]
