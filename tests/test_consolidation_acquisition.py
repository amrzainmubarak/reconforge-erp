from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_acquisition import (
    ACQUISITION_BRIDGE_ALGORITHM_VERSION,
    AcquisitionFairValueBridgeRequest,
    prepare_acquisition_fair_value_bridge,
    verify_acquisition_fair_value_bridge_payload,
)
from reconforge.utils.money import Money

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _request(**overrides: object) -> AcquisitionFairValueBridgeRequest:
    values: dict[str, object] = {
        "acquisition_id": "ACQ-001",
        "subsidiary_entity_code": "SUB",
        "period_id": "2026-Q3",
        "acquisition_date": "2026-07-01",
        "reporting_currency": "USD",
        "consideration": Money.from_exact(Decimal("120.00"), "USD", strict_precision=True),
        "nci_fair_value": Money.from_exact(Decimal("30.00"), "USD", strict_precision=True),
        "identifiable_net_assets_fair_value": Money.from_exact(Decimal("100.00"), "USD", strict_precision=True),
        "allow_bargain_purchase": False,
        "consideration_account_code": "CONSIDERATION",
        "nci_account_code": "NCI",
        "identifiable_net_assets_account_code": "NET-ASSETS",
        "goodwill_account_code": "GOODWILL",
        "bargain_purchase_account_code": "BARGAIN",
        "policy_id": "ACQ-POLICY",
        "policy_version": "1.0.0",
        "source_reference": "purchase-agreement-001",
        "source_digest": "a" * 64,
        "prepared_by": "preparer",
        "prepared_at": "2026-07-01T12:00:00Z",
        "approved_by": "reviewer",
        "approved_at": "2026-07-01T11:00:00Z",
    }
    values.update(overrides)
    return AcquisitionFairValueBridgeRequest(**values)  # type: ignore[arg-type]


def test_acquisition_bridge_calculates_exact_goodwill_and_balances() -> None:
    result = prepare_acquisition_fair_value_bridge(_request())

    assert result.algorithm_version == ACQUISITION_BRIDGE_ALGORITHM_VERSION
    assert result.goodwill.amount == Decimal("50.00")
    assert result.bargain_purchase.amount == Decimal("0.00")
    assert [line.line_type for line in result.lines] == [
        "consideration",
        "nci",
        "identifiable_net_assets",
        "goodwill",
    ]
    assert sum((line.amount.amount for line in result.lines), Decimal("0")) == Decimal("0")
    assert result.posted is False


def test_acquisition_bridge_exact_balance_has_no_zero_value_line() -> None:
    request = replace(
        _request(),
        consideration=Money.from_exact(Decimal("70.00"), "USD", strict_precision=True),
        nci_fair_value=Money.from_exact(Decimal("30.00"), "USD", strict_precision=True),
    )
    result = prepare_acquisition_fair_value_bridge(request)

    assert len(result.lines) == 3
    assert result.goodwill.amount == Decimal("0.00")
    assert result.bargain_purchase.amount == Decimal("0.00")
    assert verify_acquisition_fair_value_bridge_payload(result.to_dict())["result_digest"] == result.result_digest


def test_acquisition_bridge_replay_is_digest_stable_for_equivalent_decimal_scale() -> None:
    first = prepare_acquisition_fair_value_bridge(_request())
    second = prepare_acquisition_fair_value_bridge(
        replace(
            _request(),
            consideration=Money.from_exact(Decimal("120.000"), "USD", strict_precision=True),
            nci_fair_value=Money.from_exact(Decimal("30.000"), "USD", strict_precision=True),
        )
    )

    assert first.request_digest == second.request_digest
    assert first.result_digest == second.result_digest


def test_acquisition_bridge_rejects_bargain_purchase_unless_policy_allows_it() -> None:
    request = replace(
        _request(),
        consideration=Money.from_exact(Decimal("80.00"), "USD", strict_precision=True),
        nci_fair_value=Money.from_exact(Decimal("10.00"), "USD", strict_precision=True),
    )
    with pytest.raises(ConsolidationError, match="bargain purchase"):
        prepare_acquisition_fair_value_bridge(request)

    result = prepare_acquisition_fair_value_bridge(replace(request, allow_bargain_purchase=True))
    assert result.goodwill.amount == Decimal("0.00")
    assert result.bargain_purchase.amount == Decimal("10.00")
    assert result.lines[-1].line_type == "bargain_purchase"
    assert sum((line.amount.amount for line in result.lines), Decimal("0")) == Decimal("0")


def test_acquisition_bridge_rejects_currency_mismatch_and_self_approval() -> None:
    with pytest.raises(ConsolidationError, match="reporting currency"):
        AcquisitionFairValueBridgeRequest(**{**_request().__dict__, "reporting_currency": "EUR"})
    with pytest.raises(ConsolidationError, match="different actors"):
        AcquisitionFairValueBridgeRequest(**{**_request().__dict__, "approved_by": "preparer"})


def test_acquisition_bridge_payload_verification_detects_tampering() -> None:
    result = prepare_acquisition_fair_value_bridge(_request())
    payload = result.to_dict()
    assert verify_acquisition_fair_value_bridge_payload(payload)["result_digest"] == result.result_digest
    payload["lines"][0]["amount"]["amount"] = "121.00"  # type: ignore[index]
    with pytest.raises(ConsolidationError, match="digest mismatch"):
        verify_acquisition_fair_value_bridge_payload(payload)

    payload = result.to_dict()
    payload["goodwill"]["amount"] = "49.00"  # type: ignore[index]
    unsigned = dict(payload)
    unsigned.pop("result_digest")
    payload["result_digest"] = sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    with pytest.raises(ConsolidationError, match="goodwill line"):
        verify_acquisition_fair_value_bridge_payload(payload)


def test_acquisition_bridge_schema_accepts_typed_result() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/acquisition_fair_value_goodwill_bridge_v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    result = prepare_acquisition_fair_value_bridge(_request())
    Draft202012Validator(schema).validate(result.to_dict())


def test_acquisition_bridge_cli_is_read_only_and_json_contract_bound(tmp_path: Path) -> None:
    input_path = tmp_path / "acquisition-request.json"
    input_path.write_text(json.dumps(_request().to_dict()), encoding="utf-8")

    result = runner.invoke(app, ["consolidation", "acquisition-bridge", "--input", str(input_path)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["algorithm_version"] == ACQUISITION_BRIDGE_ALGORITHM_VERSION
    assert payload["posted"] is False
    assert payload["goodwill"]["amount"] == "50.00"

    output_path = tmp_path / "artifacts" / "bridge.json"
    written = runner.invoke(
        app,
        [
            "consolidation",
            "acquisition-bridge",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )
    assert written.exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["result_digest"] == payload["result_digest"]

    invalid = json.loads(input_path.read_text(encoding="utf-8"))
    invalid["unexpected"] = True
    input_path.write_text(json.dumps(invalid), encoding="utf-8")
    rejected = runner.invoke(app, ["consolidation", "acquisition-bridge", "--input", str(input_path)])
    assert rejected.exit_code == 1
    assert "exactly the declared contract" in rejected.output
