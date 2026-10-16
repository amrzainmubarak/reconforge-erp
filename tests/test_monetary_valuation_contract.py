"""Malformed public valuation ACKs are refused before transaction success."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from reconforge.api.monetary_public_contract import MonetaryResponseError
from reconforge.api.monetary_valuation_contract import project_monetary_valuation

FIXTURE = json.loads((Path(__file__).parents[1] / "apps/web/src/monetary-valuation-test-fixture.json").read_text(encoding="utf-8"))
SCOPE = {key: FIXTURE[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}


def test_current_residual_valuation_and_copied_inverse_keep_distinct_accounting_date() -> None:
    assert project_monetary_valuation(FIXTURE, SCOPE, FIXTURE["source_order_id"]) == FIXTURE
    inverse = {**deepcopy(FIXTURE), "id": "FX1-" + "2" * 32, "kind": "reverse_revaluation", "original_id": FIXTURE["id"], "posting_date": "2026-10-16"}
    assert project_monetary_valuation(inverse, SCOPE, inverse["source_order_id"])["closing_rate"] == FIXTURE["closing_rate"]


@pytest.mark.parametrize("mutation", ["extra", "scope", "source", "plan", "identity", "registry", "gain-loss", "turnover", "residual", "money-float", "money-bool", "zero", "phase", "reviewer", "poster", "effect", "original", "rate", "date", "account"])
def test_closed_valuation_rejects_inconsistent_native_evidence(mutation: str) -> None:
    row = deepcopy(FIXTURE)
    if mutation == "extra":
        row["snapshot"] = {"private": "must not publish"}
    elif mutation == "scope":
        row["legal_entity_id"] = "other"
    elif mutation == "source":
        row["source_order_id"] = "other"
    elif mutation == "plan":
        row["id"] = "FX1-" + "3" * 32
    elif mutation == "identity":
        row["transaction_policy"] = deepcopy(row["functional_policy"])
    elif mutation == "registry":
        row["transaction_policy"]["currency_registry_version"] = "other"
    elif mutation == "gain-loss":
        row["monetary"]["functional_unrealized_loss_minor"] = "1"
    elif mutation == "turnover":
        row["monetary"]["functional_turnover_minor"] = "141"
    elif mutation == "residual":
        row["monetary"]["functional_valued_outstanding_minor"] = "841"
    elif mutation == "money-float":
        row["monetary"]["functional_turnover_minor"] = 140.0
    elif mutation == "money-bool":
        row["monetary"]["functional_turnover_minor"] = True
    elif mutation == "zero":
        row["monetary"].update(functional_unrealized_gain_minor="0", functional_turnover_minor="0", functional_valued_outstanding_minor="700")
    elif mutation == "phase":
        row["phase"] = True
    elif mutation == "reviewer":
        row["reviewer_actor_id"] = row["preparer_actor_id"]
    elif mutation == "poster":
        row["posted_actor_id"] = row["reviewer_actor_id"]
    elif mutation == "effect":
        row["posting_effect_id"] = None
    elif mutation == "original":
        row["original_id"] = "FX1-" + "2" * 32
    elif mutation == "rate":
        row["closing_rate"]["effective_at"] = "2026-10-16T12:00:00Z"
    elif mutation == "date":
        row["posting_date"] = "2026-02-30"
    elif mutation == "account":
        row["unrealized_loss_account_code"] = row["unrealized_gain_account_code"]
    with pytest.raises(MonetaryResponseError):
        project_monetary_valuation(row, SCOPE, FIXTURE["source_order_id"], FIXTURE["id"])


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_valuation_has_real_entry_at_every_phase_with_independent_current_humans(phase: int) -> None:
    row = {**deepcopy(FIXTURE), "phase": phase, "status": ("Prepared", "Reviewed", "Posted")[phase],
           "reviewer_actor_id": "checker" if phase >= 1 else None, "posted_actor_id": "poster" if phase == 2 else None,
           "posting_effect_id": "valuation-effect" if phase == 2 else None}
    assert project_monetary_valuation(row, SCOPE, row["source_order_id"])["entry_id"] == "valuation-entry"


def test_canonical_large_money_is_never_rounded_through_float() -> None:
    row = deepcopy(FIXTURE)
    row["monetary"].update(functional_historical_outstanding_minor="9007199254740993", functional_valued_outstanding_minor="9007199254741133")
    assert project_monetary_valuation(row, SCOPE, row["source_order_id"])["monetary"]["functional_historical_outstanding_minor"] == "9007199254740993"
