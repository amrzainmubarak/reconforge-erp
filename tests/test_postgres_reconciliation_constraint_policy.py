"""Persisted worker rules must preserve the selected matching constraint contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from reconforge.reconciliation.deterministic_engine import (
    LEGACY_CONSTRAINT_POLICY,
    STRICT_ONE_TO_ONE_CONSTRAINT_POLICY,
)
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorkerError,
    ReconciliationExecutionContext,
)


def _context(rule: dict[str, Any], *, amount: str = "10.01", date: str = "2000-01-01") -> ReconciliationExecutionContext:
    def record(identity: str, value: str, day: str) -> dict[str, Any]:
        return {
            "source_id": identity,
            "amount_decimal": value,
            "currency_code": "USD",
            "attributes_json": {"id": identity, "amount": value, "currency": "USD", "date": day, "reference": "same"},
        }

    return ReconciliationExecutionContext(
        run={"rule_json": {
            "financial_input_policy": STRICT_FINANCIAL_INPUT_POLICY,
            "record_identity_policy": RECORD_IDENTITY_POLICY,
            "exact_fields": ["currency", "reference"],
            "amount_tolerance": "0", "date_window_days": 0, **rule,
        }},
        left_inputs=(record("L", "10.00", "2000-01-01"),),
        right_inputs=(record("R", amount, date),),
        heartbeat=lambda _progress: {}, cancellation_requested=lambda: False,
    )


@pytest.mark.parametrize("partitioned", [False, True])
@pytest.mark.parametrize("amount,date", [("10.01", "2000-01-01"), ("10.00", "2000-01-02")])
def test_persisted_strict_policy_rejects_over_tolerance_and_late_pairs(partitioned: bool, amount: str, date: str) -> None:
    rule: dict[str, Any] = {"constraint_policy": STRICT_ONE_TO_ONE_CONSTRAINT_POLICY}
    if partitioned:
        rule["partition_fields"] = ["currency"]
    output = LocalDeterministicMatcherAdapter()(_context(rule, amount=amount, date=date))
    assert [row["status"] for row in output.results] == ["Unmatched", "Unmatched"]
    assert all(row["lineage"]["constraint_policy"] == STRICT_ONE_TO_ONE_CONSTRAINT_POLICY for row in output.results)
    assert output.exceptions == ()


def test_persisted_strict_policy_accepts_inclusive_amount_and_date_boundaries() -> None:
    output = LocalDeterministicMatcherAdapter()(_context({
        "constraint_policy": STRICT_ONE_TO_ONE_CONSTRAINT_POLICY,
        "amount_tolerance": "0.01", "date_window_days": 1,
    }, date="2000-01-02"))
    assert len(output.results) == 1
    assert output.results[0]["status"] == "Matched"
    assert output.results[0]["amount_difference"] == "0.01"


@pytest.mark.parametrize("partitioned", [False, True])
@pytest.mark.parametrize("invalid_rule", [
    {"constraint_policy": "strict-v999"}, {"constraint_policy": None},
    {"constraint_policy": 1}, {"constraint_policy": [STRICT_ONE_TO_ONE_CONSTRAINT_POLICY]},
    *[{"constraint_policy": STRICT_ONE_TO_ONE_CONSTRAINT_POLICY, "date_window_days": value}
      for value in (True, -1, 1.5, "1", None)],
    *[{"constraint_policy": STRICT_ONE_TO_ONE_CONSTRAINT_POLICY, name: value}
      for name in ("allow_many_to_one", "allow_one_to_many", "allow_many_to_many")
      for value in (True, "false", 0)],
])
def test_invalid_persisted_policy_rejected_before_engine_or_heartbeat(
    invalid_rule: dict[str, Any], partitioned: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = LocalDeterministicMatcherAdapter()

    def unexpected_call(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Invalid policy reached the matcher or heartbeat")

    monkeypatch.setattr(adapter._engine, "match_records", unexpected_call)
    rule = {**invalid_rule, **({"partition_fields": ["currency"]} if partitioned else {})}
    initial = _context(rule)
    context = ReconciliationExecutionContext(
        run=initial.run, left_inputs=initial.left_inputs, right_inputs=initial.right_inputs,
        heartbeat=unexpected_call, cancellation_requested=lambda: False,
    )
    with pytest.raises(PostgresReconciliationWorkerError):
        adapter(context)


def test_missing_constraint_policy_preserves_historical_decisions_and_digest() -> None:
    adapter = LocalDeterministicMatcherAdapter()
    historical = adapter(_context({}))
    explicit = adapter(_context({"constraint_policy": LEGACY_CONSTRAINT_POLICY}))
    assert historical == explicit
    assert historical.results[0]["status"] == "Matched"
    assert "constraint_policy" not in historical.results[0]["lineage"]
    digest = hashlib.sha256(json.dumps(historical.results, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == "138da4c22f883fb0798f934c8ae455532d95dc5c20a95777fe9affc18f95a156"
