"""Independent integer conservation and malformed-source refusal."""

from dataclasses import replace
from fractions import Fraction

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_operations import MAX_MINOR, IntercompanyPreparation, equation


def request(amount: int = 10001) -> IntercompanyPreparation:
    return IntercompanyPreparation(workspace_id="work", organization_id="org", organization_code="ORG",
        seller_entity_id="seller", seller_entity_code="SELLER", buyer_entity_id="buyer", buyer_entity_code="BUYER",
        adjustment_entity_id="group", adjustment_entity_code="GROUP", reference="SERVICE-1", amount_minor=amount,
        period_id="period", posting_date="2026-10-01", journal_code="IC", receivable_account_code="IC_AR",
        payable_account_code="IC_AP", revenue_account_code="IC_REVENUE", expense_account_code="IC_EXPENSE",
        cash_account_code="CASH", reason="Synthetic original reviewed intercompany service")


@pytest.mark.parametrize("amount,parts", [(10001, (3000,)), (1, (1,)), (MAX_MINOR, (MAX_MINOR - 1, 1)),
                                        (101, (33, 33, 35)), (997, (2, 5, 17))])
def test_paired_native_journals_and_group_adjustment_conserve_exact_integer_oracle(amount, parts):
    req = request(amount).payload()
    by_book = {book: {} for book in ("seller", "buyer", "adjustment")}
    operations = [equation(req, "recognize")]
    settled = 0
    for installment in parts:
        operations.append(equation(req, "settle", settled_before_minor=settled, settlement_minor=installment))
        settled += installment
    operations.append(equation(req, "eliminate", settled_before_minor=settled))
    for operation in operations:
        for book, lines in operation["books"].items():
            assert sum(Fraction(row["debit_minor"]) for row in lines) == sum(Fraction(row["credit_minor"]) for row in lines)
            for row in lines:
                account = row["account_code"]
                by_book[book][account] = by_book[book].get(account, 0) + row["debit_minor"] - row["credit_minor"]
    assert by_book["seller"].get("IC_AR", 0) == amount - settled
    assert by_book["seller"].get("CASH", 0) == settled
    assert by_book["buyer"].get("IC_AP", 0) == -(amount - settled)
    assert by_book["buyer"].get("CASH", 0) == -settled
    accounts = {account for rows in by_book.values() for account in rows}
    assert {account: sum(rows.get(account, 0) for rows in by_book.values()) for account in accounts} == {account: 0 for account in accounts}
    assert operations[-1]["amount_minor"] == 2 * amount - settled


@pytest.mark.parametrize("amount", [False, True, 0, -1, "100", 1.0, MAX_MINOR + 1])
def test_noninteger_or_unbounded_money_is_never_implicitly_converted(amount):
    with pytest.raises(FinancePostingError, match="exact integer"):
        request(amount).payload()


@pytest.mark.parametrize("changes", [{"buyer_entity_id": "seller"}, {"adjustment_entity_code": "SELLER"},
    {"payable_account_code": "IC_AR"}, {"posting_date": "2026-2-1"}, {"reference": " SERVICE-1 "}])
def test_explicit_three_scope_canonical_and_distinct_account_contract(changes):
    with pytest.raises(FinancePostingError):
        replace(request(), **changes).payload()


def test_overallocation_zero_cash_and_original_replay_equations_fail_closed():
    req = request().payload()
    for kind, before, installment in (("settle", 10000, 2), ("settle", 0, 0), ("recognize", 1, 0),
                                      ("eliminate", 0, 1), ("settle", 10002, 1)):
        with pytest.raises(FinancePostingError):
            equation(req, kind, settled_before_minor=before, settlement_minor=installment)
    assert equation(req, "recognize") == equation(dict(reversed(list(req.items()))), "recognize")
