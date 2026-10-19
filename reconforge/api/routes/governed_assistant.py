"""FastAPI route for Governed Business AI Assistant with prompt injection defense, source grounding, and confidence gating."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.ai.governed_assistant import (
    GovernedAISecurityError,
    GovernedAssistantEngine,
)
from reconforge.api.dependencies import require_any_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser

router = APIRouter(prefix="/ai/assistant", tags=["governed-ai"])
AIUser = Annotated[LocalUser, Depends(require_any_permission({"ai.query", "finance_core.read"}))]


class AssistantQueryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query_id: str = Field(min_length=1, max_length=64)
    query_text: str = Field(min_length=1, max_length=1000)
    authorized_records: list[dict[str, Any]] = Field(default_factory=list)
    confidence_override: float | None = Field(default=None, ge=0.0, le=1.0)


@router.post("/query")
def evaluate_assistant_query(
    user: AIUser,
    payload: AssistantQueryPayload,
    request: Request,
) -> dict[str, Any]:
    """Evaluates an enterprise query under strict permission, tenant, and non-autonomous invariants."""
    workspace_id = getattr(request.state, "workspace_id", "default")
    user_perms: set[str] = {"finance_core.read", "ai.query"}
    principal = getattr(request.state, "server_principal", None)
    if principal is not None:
        perms = getattr(principal, "permissions", None)
        if perms:
            user_perms.update(perms)

    engine = GovernedAssistantEngine(
        workspace_id=workspace_id,
        granted_permissions=frozenset(user_perms),
    )
    try:
        response = engine.evaluate_query(
            query_id=payload.query_id,
            query_text=payload.query_text,
            authorized_records=payload.authorized_records,
            confidence_override=payload.confidence_override,
        )
    except GovernedAISecurityError as exc:
        raise APIError(status_code=403, code=exc.code, message=str(exc)) from exc

    return {
        "query_id": response.query_id,
        "answer": response.answer,
        "confidence_score": response.confidence_score,
        "cited_evidence_ids": list(response.cited_evidence_ids),
        "data_classification": response.data_classification,
        "requires_clarification": response.requires_clarification,
        "proposals": [
            {
                "proposal_id": p.proposal_id,
                "action_type": p.action_type,
                "target_entity_id": p.target_entity_id,
                "summary": p.summary,
                "requires_maker_checker": p.requires_maker_checker,
                "required_permission": p.required_permission,
            }
            for p in response.proposals
        ],
        "citation_graph": [
            {
                "node_id": c.node_id,
                "entity_type": c.entity_type,
                "record_id": c.record_id,
                "version_digest": c.version_digest,
                "summary": c.summary,
            }
            for c in response.citation_graph
        ],
    }
