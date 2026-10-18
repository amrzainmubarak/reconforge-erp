from copy import deepcopy
from dataclasses import replace

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.intercompany_cashflow import classified_cashflow
from tests.intercompany_cashflow_fixture import fixture


def test_source_originals_derive_operating_zero_and_fx_on_cash101() -> None:
    evidence, context, opening = fixture()
    result = classified_cashflow(evidence["source"], evidence["report"], evidence["stages"], opening=opening, context=context)
    assert result["operating_inflow_minor"] == result["operating_outflow_minor"] == 3000
    assert result["opening_minor"] == result["operating_net_minor"] == 0
    assert result["fx_on_cash_minor"] == result["closing_minor"] == 101
    assert result["books"]["seller"]["closing_minor"] == 2955 and result["books"]["seller"]["fx_on_cash_minor"] == -45
    assert result["books"]["buyer"]["closing_minor"] == -2854 and result["books"]["buyer"]["fx_on_cash_minor"] == 146
    assert len(result["source_effect_ids"]) == 6 and len(result["native_adjustment_effect_ids"]) == 1
    assert evidence["native_execution_proven"] is False


@pytest.mark.parametrize("change", [
    {"seller_minor": 1}, {"buyer_minor": -1}, {"seller_minor": True}, {"buyer_minor": None},
    {"source_id": "unknown"}, {"source_digest": "0" * 64}, {"origin_plan_id": "unknown"},
    {"origin_plan_digest": "0" * 64}, {"basis": "whole-company-opening-unknown"},
])
def test_unknown_nonzero_or_detached_opening_is_refused(change) -> None:
    evidence, context, opening = fixture()
    with pytest.raises(FinancePostingError, match="explicit known zero opening"):
        classified_cashflow(evidence["source"], evidence["report"], evidence["stages"], opening=replace(opening, **change), context=context)


def test_rehashed_report_cash_total_cannot_replace_original_arithmetic() -> None:
    evidence, context, opening = fixture()
    report = deepcopy(evidence["report"])
    report["cash_net_movement_minor"] = 0
    report["report_digest"] = digest_payload({key: value for key, value in report.items() if key != "report_digest"})
    with pytest.raises(FinancePostingError, match="Original closing Cash"):
        classified_cashflow(evidence["source"], report, evidence["stages"], opening=opening, context=context)


def test_rehashed_report_historical_rate_must_match_original_reviewed_elimination() -> None:
    evidence, context, opening = fixture()
    report = deepcopy(evidence["report"])
    cash = next(row for row in report["entity_translations"]["seller"]["accounts"] if row["role"] == "cash")
    cash["contributions"][0]["income_rate"]["rate"] = "1.31"
    report["report_digest"] = digest_payload({key: value for key, value in report.items() if key != "report_digest"})
    with pytest.raises(FinancePostingError, match="exact reviewed original elimination membership"):
        classified_cashflow(evidence["source"], report, evidence["stages"], opening=opening, context=context)


@pytest.mark.parametrize("field", ["source_effect_ids", "native_adjustment_effect_ids"])
def test_uncovered_or_missing_native_effect_membership_is_refused(field: str) -> None:
    evidence, context, opening = fixture()
    report = deepcopy(evidence["report"])
    report[field] = ["uncovered"]
    report["report_digest"] = digest_payload({key: value for key, value in report.items() if key != "report_digest"})
    with pytest.raises(FinancePostingError, match="omits or introduces"):
        classified_cashflow(evidence["source"], report, evidence["stages"], opening=opening, context=context)


@pytest.mark.parametrize("field", ["source_effect_ids", "native_adjustment_effect_ids"])
def test_duplicate_native_effect_population_is_refused_even_after_resealing_report(field: str) -> None:
    evidence, context, opening = fixture()
    evidence["report"][field].append(evidence["report"][field][0])
    evidence["report"]["report_digest"] = digest_payload({key: value for key, value in evidence["report"].items() if key != "report_digest"})
    with pytest.raises(FinancePostingError, match="omits or introduces"):
        classified_cashflow(evidence["source"], evidence["report"], evidence["stages"], opening=opening, context=context)


@pytest.mark.parametrize("attack", ["missing_phase", "wrong_phase_actor", "wrong_phase_digest", "duplicate_phase_audit",
    "duplicate_phase_outbox", "missing_effect_audit", "missing_effect_outbox"])
def test_original_phase_and_effect_custody_cannot_be_inferred(attack: str) -> None:
    evidence, context, opening = fixture()
    stage = evidence["stages"][1]
    if attack == "missing_phase":
        stage["phases"].pop()
    elif attack == "wrong_phase_actor":
        stage["phases"][1]["actor_id"] = "maker"
    elif attack == "wrong_phase_digest":
        stage["phases"][1]["metadata_json"]["plan_digest"] = "0" * 64
    elif attack.startswith("duplicate_phase_"):
        field = "audit_event_id" if attack == "duplicate_phase_audit" else "outbox_event_id"
        stage["phases"][1][field] = stage["phases"][0][field]
    else:
        stage["native_effects"][0]["audit_event_id" if attack == "missing_effect_audit" else "outbox_event_id"] = ""
    with pytest.raises(FinancePostingError, match="phase evidence|posting membership"):
        classified_cashflow(evidence["source"], evidence["report"], evidence["stages"], opening=opening, context=context)
