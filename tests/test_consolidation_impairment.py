from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_impairment import (
    CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION,
    ConsolidationImpairmentBridgeRequest,
    ConsolidationImpairmentUnit,
    prepare_consolidation_impairment_bridge,
    verify_consolidation_impairment_bridge_payload,
)
from reconforge.utils.money import Money

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _money(value: str) -> Money:
    return Money.from_exact(Decimal(value), "USD", strict_precision=True)


def _request(**overrides: object) -> ConsolidationImpairmentBridgeRequest:
    values: dict[str, object] = {
        "impairment_test_id": "IMP-2026-Q3-001",
        "entity_code": "SUB",
        "period_id": "2026-Q3",
        "reporting_currency": "USD",
        "units": (
            ConsolidationImpairmentUnit(
                unit_id="goodwill-001",
                unit_kind="goodwill",
                account_code="GOODWILL",
                carrying_amount=_money("100.00"),
                recoverable_amount=_money("80.00"),
                source_reference="valuation-pack-001",
                source_digest="a" * 64,
            ),
            ConsolidationImpairmentUnit(
                unit_id="asset-001",
                unit_kind="asset",
                account_code="PROPERTY",
                carrying_amount=_money("40.00"),
                recoverable_amount=_money("50.00"),
                source_reference="valuation-pack-001",
                source_digest="b" * 64,
            ),
        ),
        "policy_id": "IMPAIRMENT-POLICY",
        "policy_version": "1.0.0",
        "source_reference": "valuation-pack-001",
        "source_digest": "c" * 64,
        "prepared_by": "preparer",
        "prepared_at": "2026-07-01T12:00:00Z",
        "approved_by": "reviewer",
        "approved_at": "2026-07-01T11:00:00Z",
    }
    values.update(overrides)
    return ConsolidationImpairmentBridgeRequest(**values)


def test_impairment_bridge_calculates_loss_and_headroom_without_posting() -> None:
    result = prepare_consolidation_impairment_bridge(_request())

    assert result.algorithm_version == CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION
    assert result.total_carrying_amount.amount == Decimal("140.00")
    assert result.total_recoverable_amount.amount == Decimal("130.00")
    assert result.total_impairment_loss.amount == Decimal("20.00")
    assert result.units[1].impairment_loss("USD").amount == Decimal("20.00")
    assert result.units[1].status("USD") == "impaired"
    assert result.units[0].recoverable_headroom("USD").amount == Decimal("10.00")
    assert result.posted is False
    assert verify_consolidation_impairment_bridge_payload(result.to_dict()) == result.to_dict()


def test_impairment_digest_is_stable_under_unit_permutation() -> None:
    request = _request()
    first = prepare_consolidation_impairment_bridge(request)
    second = prepare_consolidation_impairment_bridge(replace(request, units=tuple(reversed(request.units))))

    assert first.request_digest == second.request_digest
    assert first.result_digest == second.result_digest


def test_impairment_rejects_self_approval_and_mixed_currency() -> None:
    with pytest.raises(ConsolidationError, match="different actors"):
        _request(prepared_by="same", approved_by="same")

    with pytest.raises(ConsolidationError, match="one currency"):
        _request(
            units=(
                replace(
                    _request().units[0],
                    carrying_amount=Money.from_exact("1.00", "EUR", strict_precision=True),
                ),
            )
        )


def test_impairment_tamper_detection_rechecks_derived_fields() -> None:
    result = prepare_consolidation_impairment_bridge(_request())
    payload = result.to_dict()
    payload["units"][0]["impairment_loss"]["amount"] = "99.00"  # type: ignore[index]

    with pytest.raises(ConsolidationError, match="arithmetic"):
        verify_consolidation_impairment_bridge_payload(payload)


def test_impairment_schema_and_read_only_cli_contract(tmp_path: Path) -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/consolidation_impairment_v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    result = prepare_consolidation_impairment_bridge(_request())
    Draft202012Validator(schema).validate(result.to_dict())

    input_path = tmp_path / "impairment-request.json"
    input_path.write_text(json.dumps(_request().to_dict()), encoding="utf-8")
    completed = runner.invoke(app, ["consolidation", "impairment-bridge", "--input", str(input_path)])
    assert completed.exit_code == 0, completed.stdout
    output = json.loads(completed.stdout)
    assert output["posted"] is False
    assert output["total_impairment_loss"]["amount"] == "20.00"

    tampered = json.loads(input_path.read_text(encoding="utf-8"))
    tampered["unexpected"] = True
    input_path.write_text(json.dumps(tampered), encoding="utf-8")
    rejected = runner.invoke(app, ["consolidation", "impairment-bridge", "--input", str(input_path)])
    assert rejected.exit_code != 0
    assert "declared contract" in rejected.stdout
