from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.application.consolidation import ConsolidationApplicationService
from reconforge.domain.consolidation import (
    ConsolidationAccountType,
    ConsolidationBalance,
    ConsolidationError,
    ConsolidationPolicy,
    ConsolidationRate,
    ConsolidationRequest,
    TranslationRateType,
    translate_consolidation,
)
from reconforge.domain.consolidation_lifecycle import (
    ConsolidationElimination,
    ConsolidationEliminationLine,
    ConsolidationLifecyclePolicy,
    ConsolidationOwnershipInterest,
    ConsolidationWorksheetRequest,
    prepare_consolidation_worksheet,
    verify_consolidation_worksheet_payload,
)
from reconforge.utils.money import Money

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/schemas/consolidation-worksheet-v1.schema.json"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _balance(
    line_id: str,
    entity: str,
    source_account: str,
    group_account: str,
    account_type: ConsolidationAccountType,
    amount: str,
    currency: str = "USD",
    rate_type: TranslationRateType = "closing",
    rate_bucket: str | None = None,
) -> ConsolidationBalance:
    return ConsolidationBalance(
        source_line_id=line_id,
        source_trial_balance_digest=_digest(f"trial-balance:{entity}"),
        entity_code=entity,
        source_account_code=source_account,
        group_account_code=group_account,
        account_type=account_type,
        period_id="2026-08",
        amount=Decimal(amount),
        currency=currency,
        rate_type=rate_type,
        rate_bucket=rate_bucket or f"{entity}-{rate_type}",
    )


def _translation_result():
    balances = (
        _balance("P-CASH", "PARENT", "1100", "1000", "Asset", "50.00"),
        _balance("P-EQUITY", "PARENT", "3100", "3000", "Equity", "-50.00", rate_type="historical"),
        _balance("S-CASH", "SUB-EU", "1200", "1000", "Asset", "100.00", "EUR"),
        _balance(
            "S-EQUITY",
            "SUB-EU",
            "3200",
            "3000",
            "Equity",
            "-70.00",
            "EUR",
            "historical",
        ),
        _balance("S-REVENUE", "SUB-EU", "4100", "4000", "Income", "-30.00", "EUR", "average"),
    )
    rates = (
        ConsolidationRate(
            rate_id="EUR-USD-CLOSE",
            period_id="2026-08",
            rate_type="closing",
            base_currency="EUR",
            reporting_currency="USD",
            rate=Decimal("1.20"),
            source="Synthetic approved rate table",
            source_digest=_digest("rate-table"),
            effective_at="2026-08-31T23:59:59+02:00",
            rate_bucket="SUB-EU-closing",
        ),
        ConsolidationRate(
            rate_id="EUR-USD-HIST",
            period_id="2026-08",
            rate_type="historical",
            base_currency="EUR",
            reporting_currency="USD",
            rate=Decimal("1.00"),
            source="Synthetic approved rate table",
            source_digest=_digest("rate-table"),
            effective_at="2026-08-31T23:59:59+02:00",
            rate_bucket="SUB-EU-historical",
        ),
        ConsolidationRate(
            rate_id="EUR-USD-AVG",
            period_id="2026-08",
            rate_type="average",
            base_currency="EUR",
            reporting_currency="USD",
            rate=Decimal("1.10"),
            source="Synthetic approved rate table",
            source_digest=_digest("rate-table"),
            effective_at="2026-08-31T23:59:59+02:00",
            rate_bucket="SUB-EU-average",
        ),
    )
    return translate_consolidation(
        ConsolidationRequest(
            group_code="GLOBAL-GROUP",
            period_id="2026-08",
            reporting_currency="USD",
            actor_id="controller-a",
            calculated_at="2026-08-31T22:00:00Z",
            policy=ConsolidationPolicy(
                policy_id="group-translation-policy",
                version="1.0.0",
                translation_adjustment_account_code="CTA-999",
                translation_adjustment_account_type="Equity",
            ),
            balances=balances,
            rates=rates,
        )
    )


def _policy() -> ConsolidationLifecyclePolicy:
    return ConsolidationLifecyclePolicy(
        policy_id="group-close-policy",
        version="1.0.0",
        parent_entity_code="PARENT",
        nci_net_assets_presentation_account_code="NCI-NET-ASSETS",
        nci_profit_presentation_account_code="NCI-PROFIT",
    )


def _ownership(
    *,
    interest_id: str = "OWN-P-S",
    parent: str = "PARENT",
    subsidiary: str = "SUB-EU",
    percentage: object = Decimal("0.80"),
    effective_from: str = "2026-01-01",
    effective_to: str = "",
) -> ConsolidationOwnershipInterest:
    return ConsolidationOwnershipInterest(
        interest_id=interest_id,
        parent_entity_code=parent,
        subsidiary_entity_code=subsidiary,
        direct_ownership_percentage=percentage,  # type: ignore[arg-type]
        effective_from=effective_from,
        effective_to=effective_to,
        version="1.0.0",
        source_digest=_digest(f"ownership:{interest_id}"),
        prepared_by="legal-entity-admin",
        approved_by="group-controller",
        approved_at="2026-01-02T10:00:00Z",
    )


def _elimination(*, reverse_lines: bool = False) -> ConsolidationElimination:
    lines = (
        ConsolidationEliminationLine(
            line_id="ELIM-IC-1-DR",
            entity_code="SUB-EU",
            group_account_code="3000",
            account_type="Equity",
            amount=Money.from_exact("12.00", "USD", strict_precision=True),
            source_reference="intercompany-case:IC-1:sub",
            source_digest=_digest("intercompany-case:IC-1:sub"),
        ),
        ConsolidationEliminationLine(
            line_id="ELIM-IC-1-CR",
            entity_code="PARENT",
            group_account_code="1000",
            account_type="Asset",
            amount=Money.from_exact("-12.00", "USD", strict_precision=True),
            source_reference="intercompany-case:IC-1:parent",
            source_digest=_digest("intercompany-case:IC-1:parent"),
        ),
    )
    return ConsolidationElimination(
        elimination_id="ELIM-IC-1",
        elimination_type="intercompany_balance",
        version="1.0.0",
        lines=tuple(reversed(lines)) if reverse_lines else lines,
        prepared_by="consolidation-preparer",
        prepared_at="2026-08-31T22:05:00Z",
        rationale="Eliminate the synthetic reciprocal group balance.",
    )


def _request(
    *,
    ownerships: tuple[ConsolidationOwnershipInterest, ...] | None = None,
    eliminations: tuple[ConsolidationElimination, ...] | None = None,
) -> ConsolidationWorksheetRequest:
    return ConsolidationWorksheetRequest(
        translation_result=_translation_result(),
        policy=_policy(),
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
        reporting_date="2026-08-31",
        ownership_interests=(_ownership(),) if ownerships is None else ownerships,
        eliminations=(_elimination(),) if eliminations is None else eliminations,
        prepared_by="consolidation-preparer",
        prepared_at="2026-08-31T22:10:00Z",
    )


def _payload_digest(payload: dict[str, object]) -> str:
    material = {key: value for key, value in payload.items() if key != "result_digest"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def test_effective_ownership_eliminations_and_nci_are_exact_balanced_and_nonposting() -> None:
    result = ConsolidationApplicationService.prepare_worksheet(_request())

    assert result.schema_version == 1
    assert result.algorithm_version == "consolidation-worksheet-v1"
    assert result.reporting_date == "2026-08-31"
    assert result.pre_elimination_balance == Money.from_exact("0.00", "USD", strict_precision=True)
    assert result.post_elimination_balance == Money.from_exact("0.00", "USD", strict_precision=True)
    assert result.posting_effect == "none"
    assert result.translation_result_digest == _translation_result().result_digest

    allocation = result.ownership_allocations[0]
    assert allocation.subsidiary_entity_code == "SUB-EU"
    assert allocation.direct_ownership_percentage == Decimal("0.80")
    assert allocation.effective_group_ownership_percentage == Decimal("0.80")
    assert allocation.non_controlling_percentage == Decimal("0.20")
    assert allocation.ownership_path == ("PARENT", "SUB-EU")

    nci = result.nci_allocations[0]
    assert nci.subsidiary_entity_code == "SUB-EU"
    assert nci.net_assets == Money.from_exact("120.00", "USD", strict_precision=True)
    assert nci.period_profit == Money.from_exact("33.00", "USD", strict_precision=True)
    assert nci.nci_net_assets == Money.from_exact("24.00", "USD", strict_precision=True)
    assert nci.nci_period_profit == Money.from_exact("6.60", "USD", strict_precision=True)
    assert nci.net_assets_presentation_account_code == "NCI-NET-ASSETS"
    assert nci.profit_presentation_account_code == "NCI-PROFIT"
    assert nci.posted is False

    accounts = {account.group_account_code: account.amount for account in result.worksheet_accounts}
    assert accounts == {
        "1000": Money.from_exact("158.00", "USD", strict_precision=True),
        "3000": Money.from_exact("-108.00", "USD", strict_precision=True),
        "4000": Money.from_exact("-33.00", "USD", strict_precision=True),
        "CTA-999": Money.from_exact("-17.00", "USD", strict_precision=True),
    }
    assert result.eliminations[0].posted is False
    assert result.eliminations[0].balance == Money.from_exact("0.00", "USD", strict_precision=True)


@given(
    ownership_order=st.permutations(
        (
            _ownership(effective_from="2025-01-01", effective_to="2025-12-31", percentage=Decimal("0.70")),
            _ownership(interest_id="OWN-P-S-V2", effective_from="2026-01-01"),
        )
    ),
    reverse_elimination=st.booleans(),
)
@settings(max_examples=30, deadline=None)
def test_worksheet_is_permutation_stable_and_selects_exactly_one_effective_interest(
    ownership_order: list[ConsolidationOwnershipInterest],
    reverse_elimination: bool,
) -> None:
    baseline = prepare_consolidation_worksheet(
        _request(
            ownerships=(
                _ownership(effective_from="2025-01-01", effective_to="2025-12-31", percentage=Decimal("0.70")),
                _ownership(interest_id="OWN-P-S-V2", effective_from="2026-01-01"),
            )
        )
    )
    candidate = prepare_consolidation_worksheet(
        _request(ownerships=tuple(ownership_order), eliminations=(_elimination(reverse_lines=reverse_elimination),))
    )

    assert candidate.request_digest == baseline.request_digest
    assert candidate.result_digest == baseline.result_digest
    assert candidate.worksheet_id == baseline.worksheet_id
    assert candidate.to_dict() == baseline.to_dict()
    assert candidate.ownership_allocations[0].active_interest_id == "OWN-P-S-V2"


def test_indirect_ownership_uses_exact_path_product_and_visible_nci() -> None:
    balances = (
        _balance("P-A", "PARENT", "1100", "1000", "Asset", "100.00"),
        _balance("P-E", "PARENT", "3100", "3000", "Equity", "-100.00", rate_type="historical"),
        _balance("A-A", "SUB-A", "1100", "1000", "Asset", "80.00"),
        _balance("A-E", "SUB-A", "3100", "3000", "Equity", "-80.00", rate_type="historical"),
        _balance("B-A", "SUB-B", "1100", "1000", "Asset", "50.00"),
        _balance("B-E", "SUB-B", "3100", "3000", "Equity", "-50.00", rate_type="historical"),
    )
    translation = translate_consolidation(
        ConsolidationRequest(
            group_code="GLOBAL-GROUP",
            period_id="2026-08",
            reporting_currency="USD",
            actor_id="controller-a",
            calculated_at="2026-08-31T22:00:00Z",
            policy=ConsolidationPolicy(
                policy_id="group-translation-policy",
                version="1.0.0",
                translation_adjustment_account_code="CTA-999",
                translation_adjustment_account_type="Equity",
            ),
            balances=balances,
            rates=(),
        )
    )
    request = replace(
        _request(ownerships=(), eliminations=()),
        translation_result=translation,
        ownership_interests=(
            _ownership(interest_id="OWN-P-A", subsidiary="SUB-A", percentage=Decimal("0.80")),
            _ownership(
                interest_id="OWN-A-B",
                parent="SUB-A",
                subsidiary="SUB-B",
                percentage=Decimal("0.75"),
            ),
        ),
    )

    result = prepare_consolidation_worksheet(request)
    allocations = {item.subsidiary_entity_code: item for item in result.ownership_allocations}

    assert allocations["SUB-A"].effective_group_ownership_percentage == Decimal("0.80")
    assert allocations["SUB-B"].effective_group_ownership_percentage == Decimal("0.6000")
    assert allocations["SUB-B"].non_controlling_percentage == Decimal("0.4000")
    assert allocations["SUB-B"].ownership_path == ("PARENT", "SUB-A", "SUB-B")
    nci = {item.subsidiary_entity_code: item for item in result.nci_allocations}
    assert nci["SUB-B"].nci_net_assets.amount == Decimal("20.000000")


@pytest.mark.parametrize(
    ("ownerships", "message"),
    [
        ((), "exactly one active ownership"),
        (
            (
                _ownership(),
                _ownership(interest_id="OWN-P-S-DUP", percentage=Decimal("0.90")),
            ),
            "overlap",
        ),
        (
            (
                _ownership(parent="SUB-EU", subsidiary="PARENT"),
            ),
            "root",
        ),
        (
            (_ownership(percentage=Decimal("0.50")),),
            "control",
        ),
    ],
)
def test_invalid_ownership_graphs_fail_closed(
    ownerships: tuple[ConsolidationOwnershipInterest, ...],
    message: str,
) -> None:
    with pytest.raises(ConsolidationError, match=message):
        prepare_consolidation_worksheet(_request(ownerships=ownerships))


def test_dates_actor_separation_and_decimal_ownership_fail_closed() -> None:
    with pytest.raises(ConsolidationError, match="within the declared period"):
        prepare_consolidation_worksheet(replace(_request(), reporting_date="2026-09-01"))
    with pytest.raises(ConsolidationError, match="different human actors"):
        _ownership().__class__(
            **{
                **_ownership().__dict__,
                "approved_by": "legal-entity-admin",
            }
        )
    with pytest.raises(ConsolidationError, match="finite Decimal"):
        _ownership(percentage=0.8)


def test_ownership_approval_and_elimination_preparation_cannot_postdate_the_worksheet() -> None:
    future_ownership = replace(_ownership(), approved_at="2026-09-01T00:00:00Z")
    with pytest.raises(ConsolidationError, match="approval must not follow"):
        _request(ownerships=(future_ownership,))

    future_elimination = replace(_elimination(), prepared_at="2026-09-01T00:00:00Z")
    with pytest.raises(ConsolidationError, match="preparation must not follow"):
        _request(eliminations=(future_elimination,))


def test_eliminations_reject_unbalanced_unknown_entity_currency_and_account_type_conflicts() -> None:
    base = _elimination()
    unbalanced = replace(
        base,
        lines=(replace(base.lines[0], amount=Money.from_exact("11.00", "USD", strict_precision=True)), base.lines[1]),
    )
    with pytest.raises(ConsolidationError, match="balance to zero"):
        prepare_consolidation_worksheet(_request(eliminations=(unbalanced,)))

    unknown_entity = replace(base, lines=(replace(base.lines[0], entity_code="OUTSIDER"), base.lines[1]))
    with pytest.raises(ConsolidationError, match="entity is outside"):
        prepare_consolidation_worksheet(_request(eliminations=(unknown_entity,)))

    wrong_currency = replace(
        base,
        lines=(replace(base.lines[0], amount=Money.from_exact("12.00", "EUR", strict_precision=True)), base.lines[1]),
    )
    with pytest.raises(ConsolidationError, match="reporting currency"):
        prepare_consolidation_worksheet(_request(eliminations=(wrong_currency,)))

    conflict = replace(base, lines=(replace(base.lines[0], group_account_code="1000", account_type="Liability"), base.lines[1]))
    with pytest.raises(ConsolidationError, match="account type conflict"):
        prepare_consolidation_worksheet(_request(eliminations=(conflict,)))


def test_closed_schema_and_replay_reject_rehashed_financial_tampering() -> None:
    result = prepare_consolidation_worksheet(_request())
    payload = result.to_dict()

    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(payload)
    assert verify_consolidation_worksheet_payload(payload).to_dict() == payload

    tampered = json.loads(json.dumps(payload))
    tampered["worksheet_accounts"][0]["amount"]["amount"] = "999"
    tampered["result_digest"] = _payload_digest(tampered)
    with pytest.raises(ConsolidationError, match="does not reproduce"):
        verify_consolidation_worksheet_payload(tampered)


def test_schema_and_runtime_are_in_distribution_manifest() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "docs/schemas/consolidation-worksheet-v1.schema.json" in manifest
    assert "tests/test_consolidation_lifecycle.py" in manifest
    assert "reconforge/domain/consolidation_lifecycle.py" in manifest
