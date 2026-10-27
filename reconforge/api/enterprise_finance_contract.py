"""Explicit command contracts for governed native financial source adapters."""

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.domain.finance_posting import FinancePostingError


class FinancialContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)


class FinancialPhaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class FinancialReversalRequest(FinancialPhaseRequest):
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


def financial_scope(request: Request, payload: FinancialContext) -> dict[str, str]:
    if any(not isinstance(getattr(request.state, key, None), str) or not getattr(request.state, key).strip()
           for key in ("workspace_id", "organization_id", "legal_entity_id")):
        raise APIError(status_code=403, code="financial_scope_required", message="Authenticated workspace, organization and legal entity are required.")
    return {"workspace_id": request.state.workspace_id, "organization_id": request.state.organization_id,
        "legal_entity_id": request.state.legal_entity_id, "organization_code": payload.organization_code,
        "entity_code": payload.entity_code}


def financial_error(exc: FinancePostingError) -> APIError:
    status = 403 if any(token in exc.code for token in ("denied", "permission", "step_up", "scope")) else 404 if "not_found" in exc.code else 409
    return APIError(status_code=status, code=exc.code, message=str(exc))
