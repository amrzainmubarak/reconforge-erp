"""Financial posting must never invent canonical ledger evidence.

These boundary tests use an independent recording adapter. They do not claim
native PostgreSQL, transaction atomicity, or API integration acceptance.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from reconforge.domain.intercompany_elimination import IntercompanyProfitInStockElimination
from reconforge.domain.project_milestone_billing import MilestoneBillingInvoice
from reconforge.infrastructure import postgres_intercompany_elimination, postgres_project_milestone_billing
from reconforge.infrastructure.postgres_intercompany_elimination import (
    PostgresIntercompanyEliminationError,
    PostgresIntercompanyEliminationRepository,
)
from reconforge.infrastructure.postgres_project_milestone_billing import PostgresProjectMilestoneBillingRepository
from reconforge.platform.common import PlatformError


class RecordingConnection:
    def __init__(self) -> None:
        self.transaction_count = 0
        self.statements: list[tuple[str, object]] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.transaction_count += 1
        yield

    def execute(self, statement: str, parameters: object = None) -> None:
        self.statements.append((statement, parameters))


class FinanceBoundary:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def create_entry(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return self.result


@pytest.fixture(params=["milestone", "profit_in_stock"])
def posting_case(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, Any], type[Exception], RecordingConnection, list[dict[str, Any]]]:
    connection = RecordingConnection()
    events: list[dict[str, Any]] = []

    class AuditBoundary:
        def __init__(self, *args: object) -> None:
            pass

        def append(self, **kwargs: Any) -> None:
            events.append(kwargs)

    if request.param == "milestone":
        module: Any = postgres_project_milestone_billing
        repo = PostgresProjectMilestoneBillingRepository(connection, "tenant-a")
        method = repo.post_milestone_invoice_to_finance_core
        kwargs: dict[str, Any] = {
            "invoice": MilestoneBillingInvoice(
                invoice_id="INV-1", workspace_id="ws-a", project_id="P-1",
                milestone_id="MS-1", customer_code="C-1", billed_amount_minor=12_345,
                currency="USD", issued_at="2026-10-25T12:00:00Z",
            ),
        }
        error: type[Exception] = PlatformError
    else:
        module = postgres_intercompany_elimination
        repo = PostgresIntercompanyEliminationRepository(connection, "tenant-a")
        method = repo.post_profit_in_stock_to_finance_core
        kwargs = {
            "elimination": IntercompanyProfitInStockElimination(
                elimination_id="ELIM-1", rule_id="RULE-1", unrealized_profit_minor=12_345,
                parent_share_minor=11_345, nci_share_minor=1_000, currency="USD",
                debit_account="COGS_ELIMINATION", credit_account="INVENTORY_VALUATION",
                rationale="Synthetic unrealized profit elimination",
            ),
            "posting_date": "2026-10-25",
            "workspace": "ws-a",
        }
        error = PostgresIntercompanyEliminationError

    monkeypatch.setattr(module, "PostgresAuditEventRepository", AuditBoundary)
    monkeypatch.setattr(module, "set_local_tenant_scope", lambda *args: None)
    kwargs.update(organization_code="ORG", entity_code="ENTITY", period_id="PERIOD", actor_label="reviewer")
    return method, kwargs, error, connection, events


def test_missing_finance_core_rejects_before_any_write_or_audit(posting_case: Any) -> None:
    method, kwargs, error, connection, events = posting_case

    with pytest.raises(error, match="Finance Core repository is required"):
        method(**kwargs)

    assert connection.transaction_count == 0
    assert connection.statements == []
    assert events == []


@pytest.mark.parametrize("response", [{}, {"id": None}, {"id": ""}, {"id": " "}, {"id": 123}, None])
def test_missing_canonical_entry_id_never_creates_posted_evidence(posting_case: Any, response: object) -> None:
    method, kwargs, error, connection, events = posting_case
    finance = FinanceBoundary(response)

    with pytest.raises(error, match="canonical entry identifier"):
        method(**kwargs, finance_core_repo=finance)

    assert len(finance.calls) == 1
    assert connection.statements == []
    assert events == []


def test_supplied_finance_core_reference_and_exact_balanced_lines_are_preserved(posting_case: Any) -> None:
    method, kwargs, _error, connection, events = posting_case
    finance = FinanceBoundary({"id": "GLE-existing-canonical-entry"})

    result = method(**kwargs, finance_core_repo=finance)

    assert result == "GLE-existing-canonical-entry"
    assert len(finance.calls) == 1
    call = finance.calls[0]
    assert call["workspace"] == "ws-a"
    assert call["actor_label"] == "reviewer"
    assert call["posting_date"] == "2026-10-25"
    assert sum(Decimal(line["debit"]) for line in call["lines"]) == Decimal("123.45")
    assert sum(Decimal(line["credit"]) for line in call["lines"]) == Decimal("123.45")
    assert len(connection.statements) == 1
    assert connection.statements[0][1][0] == result
    assert len(events) == 1
    assert events[0]["metadata"]["finance_entry_id"] == result


def test_finance_core_failure_never_creates_posted_evidence(posting_case: Any) -> None:
    method, kwargs, error, connection, events = posting_case

    class UnavailableFinanceCore:
        def create_entry(self, **kwargs: Any) -> object:
            raise RuntimeError("synthetic Finance Core failure")

    with pytest.raises(error, match="synthetic Finance Core failure"):
        method(**kwargs, finance_core_repo=UnavailableFinanceCore())

    assert connection.statements == []
    assert events == []
