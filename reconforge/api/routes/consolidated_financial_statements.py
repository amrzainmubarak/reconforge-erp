"""FastAPI routes for multi-entity consolidated financial statements, balance sheet, and cash flow."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidated_financial_statements import (
    EntityTrialBalance,
    GroupIntercompanyEliminations,
    generate_consolidated_statements,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.sqlite_consolidated_statements import (
    SQLiteConsolidatedStatementsRepository,
)

router = APIRouter(prefix="/finance/consolidated-statements", tags=["consolidated-statements"])

FinanceRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
FinanceManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class EntityTrialBalanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    entity_id: str = Field(min_length=1, max_length=64)
    functional_currency: str = Field(min_length=3, max_length=3)
    fx_rate_to_group_scaled: int = Field(gt=0)
    parent_ownership_bips: int = Field(ge=0, le=10_000)

    cash_minor: int = Field(ge=0)
    trade_receivables_minor: int = Field(ge=0)
    intercompany_receivables_minor: int = Field(ge=0)
    inventory_minor: int = Field(ge=0)
    ppe_minor: int = Field(ge=0)
    other_assets_minor: int = Field(ge=0)

    trade_payables_minor: int = Field(ge=0)
    intercompany_payables_minor: int = Field(ge=0)
    short_term_debt_minor: int = Field(ge=0)
    long_term_debt_minor: int = Field(ge=0)
    other_liabilities_minor: int = Field(ge=0)

    share_capital_minor: int = Field(ge=0)
    retained_earnings_opening_minor: int

    gross_revenue_minor: int = Field(ge=0)
    intercompany_revenue_minor: int = Field(ge=0)
    cogs_minor: int = Field(ge=0)
    intercompany_cogs_minor: int = Field(ge=0)
    operating_expenses_minor: int = Field(ge=0)
    depreciation_minor: int = Field(ge=0)
    finance_costs_minor: int = Field(ge=0)
    tax_expense_minor: int = Field(ge=0)

    def to_domain(self) -> EntityTrialBalance:
        return EntityTrialBalance(
            entity_id=self.entity_id,
            functional_currency=self.functional_currency,
            fx_rate_to_group_scaled=self.fx_rate_to_group_scaled,
            parent_ownership_bips=self.parent_ownership_bips,
            cash_minor=self.cash_minor,
            trade_receivables_minor=self.trade_receivables_minor,
            intercompany_receivables_minor=self.intercompany_receivables_minor,
            inventory_minor=self.inventory_minor,
            ppe_minor=self.ppe_minor,
            other_assets_minor=self.other_assets_minor,
            trade_payables_minor=self.trade_payables_minor,
            intercompany_payables_minor=self.intercompany_payables_minor,
            short_term_debt_minor=self.short_term_debt_minor,
            long_term_debt_minor=self.long_term_debt_minor,
            other_liabilities_minor=self.other_liabilities_minor,
            share_capital_minor=self.share_capital_minor,
            retained_earnings_opening_minor=self.retained_earnings_opening_minor,
            gross_revenue_minor=self.gross_revenue_minor,
            intercompany_revenue_minor=self.intercompany_revenue_minor,
            cogs_minor=self.cogs_minor,
            intercompany_cogs_minor=self.intercompany_cogs_minor,
            operating_expenses_minor=self.operating_expenses_minor,
            depreciation_minor=self.depreciation_minor,
            finance_costs_minor=self.finance_costs_minor,
            tax_expense_minor=self.tax_expense_minor,
        )


class IntercompanyEliminationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intercompany_receivables_eliminated_minor: int = Field(ge=0)
    intercompany_payables_eliminated_minor: int = Field(ge=0)
    intercompany_revenue_eliminated_minor: int = Field(ge=0)
    intercompany_cogs_eliminated_minor: int = Field(ge=0)
    profit_in_stock_eliminated_minor: int = Field(ge=0)

    def to_domain(self) -> GroupIntercompanyEliminations:
        return GroupIntercompanyEliminations(
            intercompany_receivables_eliminated_minor=self.intercompany_receivables_eliminated_minor,
            intercompany_payables_eliminated_minor=self.intercompany_payables_eliminated_minor,
            intercompany_revenue_eliminated_minor=self.intercompany_revenue_eliminated_minor,
            intercompany_cogs_eliminated_minor=self.intercompany_cogs_eliminated_minor,
            profit_in_stock_eliminated_minor=self.profit_in_stock_eliminated_minor,
        )


class GenerateConsolidatedStatementsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    group_id: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=1, max_length=64)
    reporting_currency: str = Field(min_length=3, max_length=3)
    period_id: str = Field(min_length=1, max_length=64)
    period_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    entities: list[EntityTrialBalanceInput] = Field(min_length=1, max_length=100)
    eliminations: IntercompanyEliminationsInput


def _get_repository(request: Request) -> tuple[sqlite3.Connection, SQLiteConsolidatedStatementsRepository]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return conn, SQLiteConsolidatedStatementsRepository(conn)


@router.post("/generate")
def generate_statements_endpoint(
    request: Request,
    payload: GenerateConsolidatedStatementsRequest,
    user: FinanceManage,
) -> dict[str, Any]:
    """Generate, verify mathematical invariants, and persist consolidated financial statements."""
    conn, repo = _get_repository(request)
    try:
        domain_entities = [e.to_domain() for e in payload.entities]
        domain_eliminations = payload.eliminations.to_domain()

        statements = generate_consolidated_statements(
            group_id=payload.group_id,
            organization_id=payload.organization_id,
            reporting_currency=payload.reporting_currency,
            period_id=payload.period_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            as_of_date=payload.as_of_date,
            entities=domain_entities,
            eliminations=domain_eliminations,
        )

        workspace_id = getattr(request.state, "workspace_id", "default")
        run_id = repo.save_run(
            workspace_id=workspace_id,
            statements=statements,
            prepared_by=user.username,
        )

        return {
            "status": "generated",
            "run_id": run_id,
            "report_digest": statements.report_digest,
            "statements": asdict(statements),
        }
    except FinancePostingError as exc:
        raise APIError(status_code=422, code=exc.code, message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/runs")
def list_statement_runs_endpoint(
    request: Request,
    user: FinanceRead,
    group_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """List historical consolidated statement runs for the user's workspace."""
    conn, repo = _get_repository(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        runs = repo.list_runs(workspace_id=workspace_id, group_id=group_id)
        return {"total_count": len(runs), "runs": runs}
    finally:
        conn.close()


@router.get("/runs/{run_id}")
def get_statement_run_endpoint(
    request: Request,
    run_id: str,
    user: FinanceRead,
) -> dict[str, Any]:
    """Retrieve an exact consolidated statement run by ID."""
    conn, repo = _get_repository(request)
    try:
        workspace_id = getattr(request.state, "workspace_id", "default")
        run = repo.get_run(workspace_id=workspace_id, run_id=run_id)
        if not run:
            raise APIError(status_code=404, code="statement_run_not_found", message=f"Run {run_id} not found.")
        return run
    finally:
        conn.close()
