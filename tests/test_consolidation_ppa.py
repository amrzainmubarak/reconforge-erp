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
from reconforge.domain.consolidation_ppa import (
    ACQUISITION_PPA_ALGORITHM_VERSION,
    AcquisitionPpaItem,
    AcquisitionPurchasePriceAllocationRequest,
    prepare_acquisition_purchase_price_allocation,
    verify_acquisition_purchase_price_allocation_payload,
)
from reconforge.utils.money import Money

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _money(value: str) -> Money:
    return Money.from_exact(Decimal(value), "USD", strict_precision=True)


def _request(**overrides: object) -> AcquisitionPurchasePriceAllocationRequest:
    values: dict[str, object] = {
        "acquisition_id": "ACQ-PPA-001",
        "subsidiary_entity_code": "SUB",
        "period_id": "2026-Q3",
        "acquisition_date": "2026-07-01",
        "reporting_currency": "USD",
        "consideration": _money("170.00"),
        "nci_fair_value": _money("30.00"),
        "items": (
            AcquisitionPpaItem(
                item_id="liability-001",
                item_kind="liability",
                class_code="DEBT",
                account_code="DEBT-FV",
                book_value=_money("30.00"),
                fair_value=_money("35.00"),
                valuation_reference="valuation-debt-001",
                source_reference="valuation-pack-001",
            ),
            AcquisitionPpaItem(
                item_id="asset-001",
                item_kind="asset",
                class_code="PROPERTY",
                account_code="PROPERTY-FV",
                book_value=_money("100.00"),
                fair_value=_money("125.00"),
                valuation_reference="valuation-property-001",
                source_reference="valuation-pack-001",
            ),
        ),
        "allow_bargain_purchase": False,
        "consideration_account_code": "CONSIDERATION",
        "nci_account_code": "NCI",
        "identifiable_net_assets_account_code": "NET-ASSETS",
        "goodwill_account_code": "GOODWILL",
        "bargain_purchase_account_code": "BARGAIN",
        "policy_id": "PPA-POLICY",
        "policy_version": "1.0.0",
        "source_reference": "purchase-agreement-ppa-001",
        "source_digest": "a" * 64,
        "prepared_by": "preparer",
        "prepared_at": "2026-07-01T12:00:00Z",
        "approved_by": "reviewer",
        "approved_at": "2026-07-01T11:00:00Z",
    }
    values.update(overrides)
    return AcquisitionPurchasePriceAllocationRequest(**values)


def test_ppa_reconciles_asset_liability_detail_and_goodwill() -> None:
    result = prepare_acquisition_purchase_price_allocation(_request())

    assert result.algorithm_version == ACQUISITION_PPA_ALGORITHM_VERSION
    assert result.book_net_assets.amount == Decimal("70.00")
    assert result.fair_value_net_assets.amount == Decimal("90.00")
    assert result.fair_value_adjustment.amount == Decimal("20.00")
    assert result.bridge.goodwill.amount == Decimal("110.00")
    assert result.bridge.bargain_purchase.amount == Decimal("0.00")
    assert [item.item_id for item in result.items] == ["asset-001", "liability-001"]
    assert verify_acquisition_purchase_price_allocation_payload(result.to_dict())["result_digest"] == result.result_digest


def test_ppa_digest_is_stable_under_item_permutation() -> None:
    request = _request()
    reversed_request = replace(request, items=tuple(reversed(request.items)))
    first = prepare_acquisition_purchase_price_allocation(request)
    second = prepare_acquisition_purchase_price_allocation(reversed_request)

    assert first.request_digest == second.request_digest
    assert first.result_digest == second.result_digest


def test_ppa_rejects_negative_fair_value_net_assets_and_self_approval() -> None:
    liability_only = AcquisitionPpaItem(
        item_id="liability-001",
        item_kind="liability",
        class_code="DEBT",
        account_code="DEBT-FV",
        book_value=_money("30.00"),
        fair_value=_money("35.00"),
        valuation_reference="valuation-debt-001",
        source_reference="valuation-pack-001",
    )
    with pytest.raises(ConsolidationError, match="different actors"):
        _request(items=(liability_only,), prepared_by="same", approved_by="same")
    request = _request(items=(liability_only,))
    with pytest.raises(ConsolidationError, match="net assets cannot be negative"):
        prepare_acquisition_purchase_price_allocation(request)


def test_ppa_tamper_detection_catches_item_adjustment() -> None:
    result = prepare_acquisition_purchase_price_allocation(_request())
    payload = result.to_dict()
    payload["items"][0]["fair_value_adjustment"]["amount"] = "999.00"  # type: ignore[index]
    with pytest.raises(ConsolidationError, match="digest mismatch"):
        verify_acquisition_purchase_price_allocation_payload(payload)


def test_ppa_schema_and_read_only_cli_contract(tmp_path: Path) -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/acquisition_purchase_price_allocation_v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    result = prepare_acquisition_purchase_price_allocation(_request())
    Draft202012Validator(schema).validate(result.to_dict())

    input_path = tmp_path / "ppa-request.json"
    input_path.write_text(json.dumps(_request().to_dict()), encoding="utf-8")
    completed = runner.invoke(app, ["consolidation", "acquisition-ppa", "--input", str(input_path)])
    assert completed.exit_code == 0, completed.stdout
    output = json.loads(completed.stdout)
    assert output["posted"] is False
    assert output["bridge"]["goodwill"]["amount"] == "110.00"

    tampered = json.loads(input_path.read_text(encoding="utf-8"))
    tampered["unexpected"] = True
    input_path.write_text(json.dumps(tampered), encoding="utf-8")
    rejected = runner.invoke(app, ["consolidation", "acquisition-ppa", "--input", str(input_path)])
    assert rejected.exit_code != 0
    assert "declared contract" in rejected.stdout
