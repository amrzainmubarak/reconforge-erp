from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_ownership_changes import (
    OWNERSHIP_CHANGE_ALGORITHM_VERSION,
    OwnershipChangeAdjustmentRequest,
    prepare_ownership_change_adjustment,
    verify_ownership_change_adjustment_payload,
)
from reconforge.utils.money import Money

ROOT = Path(__file__).resolve().parents[1]


def _request() -> OwnershipChangeAdjustmentRequest:
    return OwnershipChangeAdjustmentRequest(
        change_id="CHANGE-001",
        subsidiary_entity_code="SUB",
        period_id="2026-Q2",
        effective_date="2026-04-01",
        reporting_currency="USD",
        prior_group_ownership_percentage=Decimal("0.80"),
        new_group_ownership_percentage=Decimal("0.70"),
        net_assets=Money.from_exact(Decimal("1000.00"), "USD", strict_precision=True),
        consideration_effect=Money.from_exact(Decimal("-120.00"), "USD", strict_precision=True),
        nci_account_code="NCI",
        consideration_account_code="CASH",
        parent_equity_account_code="PARENT-EQUITY",
        policy_id="OWNERSHIP-POLICY",
        policy_version="1.0.0",
        source_reference="ownership-register-001",
        source_digest="a" * 64,
        prepared_by="preparer",
        prepared_at="2026-04-01T12:00:00Z",
        approved_by="reviewer",
        approved_at="2026-04-01T11:00:00Z",
    )


def test_ownership_change_adjustment_is_exact_balanced_and_non_posting() -> None:
    result = prepare_ownership_change_adjustment(_request())

    assert result.algorithm_version == OWNERSHIP_CHANGE_ALGORITHM_VERSION
    assert result.prior_nci_percentage == Decimal("0.20")
    assert result.new_nci_percentage == Decimal("0.30")
    assert result.unrounded_nci_effect == Decimal("100.00")
    assert result.nci_rounding_delta == Decimal("0.00")
    assert [line.amount.amount for line in result.lines] == [Decimal("100.00"), Decimal("-120.00"), Decimal("20.00")]
    assert sum((line.amount.amount for line in result.lines), Decimal("0")) == Decimal("0")
    assert all(line.source_reference == "ownership-register-001" for line in result.lines)
    assert result.posted is False


def test_ownership_change_replay_is_digest_stable_under_equivalent_decimal_scale() -> None:
    first = prepare_ownership_change_adjustment(_request())
    second = prepare_ownership_change_adjustment(
        replace(
            _request(),
            prior_group_ownership_percentage=Decimal(".8000"),
            new_group_ownership_percentage=Decimal(".7000"),
        )
    )

    assert first.result_digest == second.result_digest
    assert first.request_digest == second.request_digest


def test_ownership_change_rounding_is_visible_and_parent_line_absorbs_it() -> None:
    request = replace(
        _request(),
        net_assets=Money.from_exact(Decimal("100.01"), "USD", strict_precision=True),
        prior_group_ownership_percentage=Decimal("0.75"),
        new_group_ownership_percentage=Decimal("0.73"),
        consideration_effect=Money.from_exact(Decimal("0"), "USD", strict_precision=True),
    )
    result = prepare_ownership_change_adjustment(request)

    assert result.unrounded_nci_effect == Decimal("2.0002")
    assert result.nci_rounding_delta == Decimal("-0.0002")
    assert result.lines[0].amount.amount == Decimal("2.00")
    assert result.lines[2].amount.amount == Decimal("-2.00")


@pytest.mark.parametrize(
    "field,value",
    [
        ("reporting_currency", "EUR"),
        ("net_assets", Money.from_exact(Decimal("1.00"), "EUR", strict_precision=True)),
    ],
)
def test_ownership_change_rejects_currency_mismatch(field: str, value: object) -> None:
    with pytest.raises(ConsolidationError, match="reporting currency"):
        OwnershipChangeAdjustmentRequest(**{**_request().__dict__, field: value})


def test_ownership_change_rejects_self_approval_and_late_approval() -> None:
    with pytest.raises(ConsolidationError, match="different actors"):
        OwnershipChangeAdjustmentRequest(**{**_request().__dict__, "approved_by": "preparer"})
    with pytest.raises(ConsolidationError, match="precede"):
        OwnershipChangeAdjustmentRequest(**{**_request().__dict__, "approved_at": "2026-04-01T13:00:00Z"})


def test_ownership_change_payload_verification_detects_tampering() -> None:
    result = prepare_ownership_change_adjustment(_request())
    payload = result.to_dict()
    assert verify_ownership_change_adjustment_payload(payload)["result_digest"] == result.result_digest
    payload["lines"][0]["amount"]["amount"] = "101.00"  # type: ignore[index]
    with pytest.raises(ConsolidationError, match="digest mismatch"):
        verify_ownership_change_adjustment_payload(payload)


def test_ownership_change_payload_verification_requires_exact_balance() -> None:
    result = prepare_ownership_change_adjustment(_request())
    payload = result.to_dict()
    payload["lines"] = payload["lines"][:2]  # type: ignore[index]
    unsigned = dict(payload)
    unsigned.pop("result_digest")
    payload["result_digest"] = sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    with pytest.raises(ConsolidationError, match="exactly three"):
        verify_ownership_change_adjustment_payload(payload)


def test_ownership_change_schema_accepts_the_typed_result() -> None:
    schema = json.loads(
        (ROOT / "docs/schemas/ownership_change_adjustment_v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    result = prepare_ownership_change_adjustment(_request())
    Draft202012Validator(schema).validate(result.to_dict())
