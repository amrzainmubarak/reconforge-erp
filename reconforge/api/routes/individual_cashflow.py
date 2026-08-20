"""Authenticated local API for stateless individual cashflow controls."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission
from reconforge.api.errors import APIError
from reconforge.application.individual_cashflow_control import run_individual_cashflow_control_records
from reconforge.auth.models import LocalUser
from reconforge.domain.individual_cashflow_control import IndividualCashflowControlError

router = APIRouter(prefix="/individual", tags=["individual-cashflow"])
IndividualCashflowRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"finance_core.read", "finance_core.manage", "finance_core.validate"})),
]


class IndividualCashflowRunRequest(BaseModel):
    """Bounded in-memory records for one local cashflow run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    transactions: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    budgets: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


@router.post("/cashflow-controls/run")
def run_individual_cashflow(
    request: IndividualCashflowRunRequest,
    current_user: IndividualCashflowRead,
) -> dict[str, object]:
    """Run a replay-verifiable, non-posting control over local records."""

    del current_user
    try:
        run = run_individual_cashflow_control_records(
            request.transactions,
            request.budgets,
            currency=request.currency,
        )
    except IndividualCashflowControlError as exc:
        raise APIError(status_code=400, code="individual_cashflow_control_failed", message=str(exc)) from exc
    return {
        "individual_cashflow": run.to_dict(),
        "network_dispatch": "disabled",
        "source": {"kind": "local-individual-cashflow-control", "server_mode": False},
    }


__all__ = ["router"]
