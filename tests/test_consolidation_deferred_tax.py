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
from reconforge.domain.consolidation_deferred_tax import (
    ACQUISITION_DEFERRED_TAX_ALGORITHM_VERSION,
    AcquisitionDeferredTaxBridgeRequest,
    AcquisitionDeferredTaxItem,
    prepare_acquisition_deferred_tax_bridge,
    verify_acquisition_deferred_tax_bridge_payload,
)
from reconforge.utils.money import Money

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _money(value: str) -> Money:
    return Money.from_exact(Decimal(value), "USD", strict_precision=True)


def _request(**overrides: object) -> AcquisitionDeferredTaxBridgeRequest:
    values: dict[str, object] = {
        "acquisition_id": "ACQ-TAX-001",
        "subsidiary_entity_code": "SUB",
        "period_id": "2026-Q3",
        "acquisition_date": "2026-07-01",
        "reporting_currency": "USD",
        "items": (
            AcquisitionDeferredTaxItem(
                item_id="asset-001",
                item_kind="asset",
                account_code="PROPERTY-FV",
                fair_value=_money("150.00"),
                tax_basis=_money("100.00"),
                tax_rate=Decimal("0.25"),
                source_reference="valuation-pack-001",
                tax_basis_reference="tax-register-001",
            ),
            AcquisitionDeferredTaxItem(
                item_id="liability-001",
                item_kind="liability",
                account_code="PROVISION-FV",
                fair_value=_money("120.00"),
                tax_basis=_money("100.00"),
                tax_rate=Decimal("0.25"),
                source_reference="valuation-pack-001",
                tax_basis_reference="tax-register-002",
            ),
        ),
        "deferred_tax_asset_account_code": "DTA",
        "deferred_tax_liability_account_code": "DTL",
        "policy_id": "TAX-POLICY",
        "policy_version": "1.0.0",
        "source_reference": "purchase-agreement-tax-001",
        "source_digest": "a" * 64,
        "prepared_by": "preparer",
        "prepared_at": "2026-07-01T12:00:00Z",
        "approved_by": "reviewer",
        "approved_at": "2026-07-01T11:00:00Z",
    }
    values.update(overrides)
    return AcquisitionDeferredTaxBridgeRequest(**values)


def test_deferred_tax_bridge_calculates_signed_differences_and_totals() -> None:
    result = prepare_acquisition_deferred_tax_bridge(_request())

    assert result.algorithm_version == ACQUISITION_DEFERRED_TAX_ALGORITHM_VERSION
    assert result.items[0].item_id == "asset-001"
    assert result.items[0].temporary_difference("USD").amount == Decimal("50.00")
    assert result.items[0].tax_effect("USD").amount == Decimal("12.50")
    assert result.items[0].classification("USD") == "deferred_tax_liability"
    assert result.items[1].temporary_difference("USD").amount == Decimal("-20.00")
    assert result.items[1].tax_effect("USD").amount == Decimal("-5.00")
    assert result.items[1].classification("USD") == "deferred_tax_asset"
    assert result.deferred_tax_asset.amount == Decimal("5.00")
    assert result.deferred_tax_liability.amount == Decimal("12.50")
    assert result.net_deferred_tax.amount == Decimal("7.50")
    assert result.posted is False
    assert verify_acquisition_deferred_tax_bridge_payload(result.to_dict())["result_digest"] == result.result_digest


def test_deferred_tax_digest_is_stable_under_item_permutation() -> None:
    request = _request()
    first = prepare_acquisition_deferred_tax_bridge(request)
    second = prepare_acquisition_deferred_tax_bridge(replace(request, items=tuple(reversed(request.items))))

    assert first.request_digest == second.request_digest
    assert first.result_digest == second.result_digest


def test_deferred_tax_rejects_self_approval_and_invalid_rates() -> None:
    with pytest.raises(ConsolidationError, match="different actors"):
        _request(prepared_by="same", approved_by="same")
    with pytest.raises(ConsolidationError, match="outside the supported range"):
        AcquisitionDeferredTaxItem(
            item_id="bad-rate",
            item_kind="asset",
            account_code="ASSET",
            fair_value=_money("1.00"),
            tax_basis=_money("0.00"),
            tax_rate=Decimal("1.01"),
            source_reference="source",
            tax_basis_reference="basis",
        )


def test_deferred_tax_tamper_detection_rechecks_arithmetic() -> None:
    result = prepare_acquisition_deferred_tax_bridge(_request())
    payload = result.to_dict()
    payload["items"][0]["tax_amount"]["amount"] = "99.00"  # type: ignore[index]
    with pytest.raises(ConsolidationError, match="digest mismatch"):
        verify_acquisition_deferred_tax_bridge_payload(payload)


def test_deferred_tax_schema_and_read_only_cli_contract(tmp_path: Path) -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/acquisition_deferred_tax_v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    result = prepare_acquisition_deferred_tax_bridge(_request())
    Draft202012Validator(schema).validate(result.to_dict())

    input_path = tmp_path / "deferred-tax-request.json"
    input_path.write_text(json.dumps(_request().to_dict()), encoding="utf-8")
    completed = runner.invoke(app, ["consolidation", "acquisition-deferred-tax", "--input", str(input_path)])
    assert completed.exit_code == 0, completed.stdout
    output = json.loads(completed.stdout)
    assert output["posted"] is False
    assert output["net_deferred_tax"]["amount"] == "7.50"

    tampered = json.loads(input_path.read_text(encoding="utf-8"))
    tampered["unexpected"] = True
    input_path.write_text(json.dumps(tampered), encoding="utf-8")
    rejected = runner.invoke(app, ["consolidation", "acquisition-deferred-tax", "--input", str(input_path)])
    assert rejected.exit_code != 0
    assert "declared contract" in rejected.stdout
