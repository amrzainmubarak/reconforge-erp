"""FastAPI routes for intercompany elimination and profit-in-stock accounting."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyProfitInStockRule,
    calculate_profit_in_stock_elimination,
    diagnose_intercompany_discrepancies,
    prepare_intercompany_eliminations,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres_intercompany_elimination import (
    PostgresIntercompanyEliminationRepository,
)
from reconforge.infrastructure.sqlite_intercompany_elimination import (
    SQLiteIntercompanyEliminationRepository,
)
from reconforge.platform.common import PlatformError
from reconforge.utils.money import InvalidAmountError, Money

router = APIRouter(prefix="/intercompany/eliminations", tags=["intercompany-eliminations"])

FinanceRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
FinanceManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class CanonicalMoneyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=1, max_length=8)
    minor_units: int = Field(ge=0, le=8)
    rounding_policy: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"


class IntercompanyLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str = Field(min_length=1, max_length=160)
    period_name: str = Field(min_length=1, max_length=160)
    entity_code: str = Field(min_length=1, max_length=160)
    counterparty_code: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=160)
    group_account_code: str = Field(min_length=1, max_length=160)
    account_type: Literal["Asset", "Liability", "Equity", "Income", "Expense"]
    amount: CanonicalMoneyInput
    source_reference: str = Field(min_length=1, max_length=500)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    def to_domain(self) -> IntercompanyEliminationInputLine:
        try:
            money = Money.from_exact(
                self.amount.amount,
                self.amount.currency,
                strict_precision=True,
            )
            return IntercompanyEliminationInputLine(
                transaction_id=self.transaction_id,
                period_name=self.period_name,
                entity_code=self.entity_code,
                counterparty_code=self.counterparty_code,
                reference=self.reference,
                group_account_code=self.group_account_code,
                account_type=self.account_type,
                amount=money,
                source_reference=self.source_reference,
                source_digest=self.source_digest,
            )
        except (ConsolidationError, InvalidAmountError) as exc:
            raise APIError(status_code=422, code="invalid_intercompany_line", message=str(exc)) from exc


class ProposeEliminationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reporting_currency: str = Field(min_length=3, max_length=6)
    version: str = Field(default="1.0.0", pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    lines: list[IntercompanyLineInput] = Field(min_length=1, max_length=100_000)


class ProfitInStockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rule_id: str = Field(min_length=1, max_length=160)
    selling_entity: str = Field(min_length=1, max_length=160)
    buying_entity: str = Field(min_length=1, max_length=160)
    inventory_item_code: str = Field(min_length=1, max_length=160)
    margin_basis_points: int = Field(ge=0, le=10_000)
    ending_inventory_cost_minor: int = Field(ge=0)
    nci_share_basis_points: int = Field(default=0, ge=0, le=10_000)
    currency: str = Field(min_length=3, max_length=6)
    debit_account: str = Field(default="COGS_ELIMINATION", min_length=1, max_length=64)
    credit_account: str = Field(default="INVENTORY_VALUATION", min_length=1, max_length=64)


def _get_repository(request: Request) -> tuple[Any, SQLiteIntercompanyEliminationRepository | PostgresIntercompanyEliminationRepository]:
    server_mode = bool(getattr(request.app.state, "server_mode", False))
    factory = (
        getattr(request.app.state, "postgres_finance_core_factory", None)
        or getattr(request.app.state, "postgres_identity_factory", None)
        or getattr(request.app.state, "postgres_connection_factory", None)
    )
    if server_mode:
        if factory is None:
            raise APIError(
                status_code=503,
                code="server_postgres_unavailable",
                message="Enterprise production profile requires PostgreSQL.",
            )
        try:
            conn = factory.connect()
        except Exception as exc:
            raise APIError(
                status_code=503,
                code="server_postgres_unavailable",
                message=f"Enterprise production profile database connection failed: {exc}",
            ) from exc
        raw_tenant = getattr(request.state, "tenant_id", None) or getattr(request.state, "workspace_id", "default")
        tenant_id = str(raw_tenant) if raw_tenant else "default"
        return conn, PostgresIntercompanyEliminationRepository(conn, tenant_id)

    if factory is not None:
        try:
            conn = factory.connect()
            raw_tenant = getattr(request.state, "tenant_id", None) or getattr(request.state, "workspace_id", "default")
            tenant_id = str(raw_tenant) if raw_tenant else "default"
            return conn, PostgresIntercompanyEliminationRepository(conn, tenant_id)
        except Exception:
            pass

    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return conn, SQLiteIntercompanyEliminationRepository(conn)


@router.post("/propose")
def propose_eliminations(
    request: Request,
    payload: ProposeEliminationRequest,
    user: FinanceManage,
) -> dict[str, Any]:
    """Calculate and persist deterministic reciprocal intercompany eliminations with diagnostics."""
    conn, repo = _get_repository(request)
    try:
        domain_lines = tuple(line.to_domain() for line in payload.lines)
        prepared_at = utc_now_text()
        result = prepare_intercompany_eliminations(
            domain_lines,
            reporting_currency=payload.reporting_currency,
            prepared_by=user.username,
            prepared_at=prepared_at,
            version=payload.version,
        )
        diagnostics = diagnose_intercompany_discrepancies(domain_lines, result)

        workspace = getattr(request.state, "workspace_id", "default")
        run_id = repo.save_elimination_result(workspace, result, actor_label=user.username)

        return {
            "diagnostics": [diag.to_dict() for diag in diagnostics],
            "prepared_at": result.prepared_at,
            "prepared_by": result.prepared_by,
            "reporting_currency": result.reporting_currency,
            "request_digest": result.request_digest,
            "resolutions": [res.to_dict() for res in result.resolutions],
            "result_digest": result.result_digest,
            "run_id": run_id,
            "schema_version": result.schema_version,
            "version": result.version,
        }
    except ConsolidationError as exc:
        raise APIError(status_code=400, code="intercompany_elimination_error", message=str(exc)) from exc
    except PlatformError as exc:
        raise APIError(status_code=409, code="intercompany_storage_conflict", message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/runs")
def list_elimination_runs(
    request: Request,
    user: FinanceRead,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List historical intercompany elimination runs."""
    conn, repo = _get_repository(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        runs = repo.list_elimination_runs(workspace, limit=limit)
        return {"runs": runs}
    finally:
        conn.close()


@router.get("/runs/{run_id}")
def get_elimination_run(
    request: Request,
    run_id: str,
    user: FinanceRead,
) -> dict[str, Any]:
    """Retrieve full audit details and proposals of a specific elimination run."""
    conn, repo = _get_repository(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        run = repo.get_elimination_run(workspace, run_id)
        if not run:
            raise APIError(status_code=404, code="elimination_run_not_found", message=f"Run {run_id} not found.")
        return run
    finally:
        conn.close()


@router.post("/profit-in-stock")
def eliminate_profit_in_stock(
    request: Request,
    payload: ProfitInStockRequest,
    user: FinanceManage,
) -> dict[str, Any]:
    """Calculate and persist profit-in-stock unrealized inventory elimination with NCI allocation."""
    conn, repo = _get_repository(request)
    try:
        rule = IntercompanyProfitInStockRule(
            rule_id=payload.rule_id,
            selling_entity=payload.selling_entity,
            buying_entity=payload.buying_entity,
            inventory_item_code=payload.inventory_item_code,
            margin_basis_points=payload.margin_basis_points,
            ending_inventory_cost_minor=payload.ending_inventory_cost_minor,
            nci_share_basis_points=payload.nci_share_basis_points,
            currency=payload.currency,
        )
        elimination = calculate_profit_in_stock_elimination(
            rule,
            debit_account=payload.debit_account,
            credit_account=payload.credit_account,
        )
        workspace = getattr(request.state, "workspace_id", "default")
        repo.save_profit_in_stock_elimination(workspace, rule, elimination, actor_label=user.username)

        return elimination.to_dict()
    except ConsolidationError as exc:
        raise APIError(status_code=400, code="profit_in_stock_error", message=str(exc)) from exc
    except PlatformError as exc:
        raise APIError(status_code=409, code="profit_in_stock_storage_conflict", message=str(exc)) from exc
    finally:
        conn.close()


@router.get("/profit-in-stock")
def list_profit_in_stock_eliminations(
    request: Request,
    user: FinanceRead,
) -> dict[str, Any]:
    """List historical profit-in-stock eliminations."""
    conn, repo = _get_repository(request)
    try:
        workspace = getattr(request.state, "workspace_id", "default")
        eliminations = repo.list_profit_in_stock_eliminations(workspace)
        return {"eliminations": eliminations}
    finally:
        conn.close()
