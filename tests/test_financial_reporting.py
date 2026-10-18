"""Exact classified statements and API money over the existing verified balance contract."""

from copy import deepcopy

import pytest

from reconforge.api.routes.financial_reporting import project
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.financial_reporting import build_financial_report
from tests.test_finance_balances import effect, report


def classification() -> dict:
    return {
        "id": "map",
        "workspace_id": "w",
        "organization_id": "o",
        "legal_entity_id": "le",
        "map_digest": "a" * 64,
        "accounts": [
            {
                "account_id": "cash",
                "account_code": "CASH",
                "account_name": "Cash",
                "account_type": "Asset",
                "normal_balance": "Debit",
                "section": "CurrentAsset",
                "is_cash": True,
            },
            {
                "account_id": "credit",
                "account_code": "EQUITY",
                "account_name": "Equity",
                "account_type": "Equity",
                "normal_balance": "Credit",
                "section": "Equity",
                "is_cash": False,
            },
        ],
    }


def test_classified_opening_and_negative_movement_retains_exact_large_money() -> None:
    from tests.test_finance_posting_domain import snapshot

    credit = snapshot()["lines"][1]["account_id"]
    mapping = classification()
    mapping["accounts"][1]["account_id"] = credit
    balances = report(
        [
            effect("opening", "2026-09-30", "sep", amount=9007199254740993),
            effect("inverse", "2026-10-02", "oct", amount=93, inverse=True),
        ]
    )
    statements = build_financial_report(balances, mapping)
    assert statements["balance_sheet"]["assets_minor"] == 9007199254740900
    assert statements["cash_movements"]["opening_minor"] == 9007199254740993
    assert statements["cash_movements"]["activity_minor"] == -93
    assert statements["cash_movements"]["outflow_minor"] == 93
    assert project(statements)["cash_movements"]["opening_minor"] == "9007199254740993"
    assert project(statements)["effect_count"] == 2


def test_reporting_refuses_unmapped_accounts_and_different_hierarchy() -> None:
    mapping = classification()
    balances = report([effect("movement", "2026-10-02", "oct")])
    with pytest.raises(FinancePostingError, match="explicit reviewed classification"):
        build_financial_report(balances, mapping)
    changed = deepcopy(mapping)
    changed["legal_entity_id"] = "other"
    with pytest.raises(FinancePostingError, match="different scope"):
        build_financial_report(balances, changed)
