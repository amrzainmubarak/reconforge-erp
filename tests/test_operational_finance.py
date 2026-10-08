"""Native AR/AP operational source money admission is exact and closed."""

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_finance import OperationalFinancePreparation, exact_minor_text
from reconforge.infrastructure.postgres_operational_finance_schema import POSTGRES_OPERATIONAL_FINANCE_SCHEMA_SQL


def request() -> OperationalFinancePreparation:
    return OperationalFinancePreparation(
        "work",
        "org",
        "entity",
        "ORG",
        "ENTITY",
        "ARInvoice",
        "invoice",
        "STOCK",
        "period",
        "2026-10-08",
        "AR",
        "REVENUE",
        "Native source",
    )


@pytest.mark.parametrize(
    ("amount", "precision", "expected"),
    [(1, 0, "1"), (1, 3, "0.001"), (12000, 2, "120.00"), (9_000_000_000_000_000_000, 8, "90000000000.00000000")],
)
def test_minor_serialization(amount: int, precision: int, expected: str) -> None:
    assert exact_minor_text(amount, precision) == expected


@pytest.mark.parametrize(("amount", "precision"), [(True, 2), (1.1, 2), (0, 2), (-1, 2), (1, True), (1, 9)])
def test_reject_inexact_or_unsupported_money(amount: int, precision: int) -> None:
    with pytest.raises(FinancePostingError):
        exact_minor_text(amount, precision)


def test_closed_native_source_request() -> None:
    assert request().payload()["source_kind"] == "ARInvoice"
    for invalid in (
        replace(request(), source_kind="Arbitrary"),
        replace(request(), credit_account_code="AR"),
        replace(request(), posting_date="2026-1-1"),
        replace(request(), source_id=" invoice"),
    ):
        with pytest.raises(FinancePostingError):
            invalid.payload()


def test_forward_migration_freezes_source_and_closure_installer() -> None:
    tree = ast.parse(Path("alembic/versions/0109_postgres_operational_finance.py").read_text())
    values = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert values["revision"] == "0109_pg_operational_finance"
    assert values["down_revision"] == "0108_pg_receipt_admission"
    assert values["UPGRADE_SQL"].strip() == POSTGRES_OPERATIONAL_FINANCE_SCHEMA_SQL.strip()
