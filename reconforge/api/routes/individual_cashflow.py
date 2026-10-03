"""Authenticated local API for stateless individual cashflow controls."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.application.individual_cashflow_control import run_individual_cashflow_control_records
from reconforge.auth.field_access import project_individual_cashflow
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
    request: Request,
    payload: IndividualCashflowRunRequest,
    current_user: IndividualCashflowRead,
) -> dict[str, object]:
    """Run a replay-verifiable, non-posting control over local records."""

    del current_user
    if server_identity_enabled(request):
        raise APIError(
            status_code=501,
            code="individual_cashflow_server_backend_unavailable",
            message="Individual cashflow control is available only in the local profile.",
        )
    try:
        run = run_individual_cashflow_control_records(
            payload.transactions,
            payload.budgets,
            currency=payload.currency,
        )
    except IndividualCashflowControlError as exc:
        raise APIError(status_code=400, code="individual_cashflow_control_failed", message=str(exc)) from exc
    return {
        "individual_cashflow": project_individual_cashflow(run.to_dict()).visible,
        "network_dispatch": "disabled",
        "source": {"kind": "local-individual-cashflow-control", "server_mode": False},
    }


__all__ = ["router"]
