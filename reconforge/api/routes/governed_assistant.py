"""FastAPI route for Governed Business AI Assistant with prompt injection defense, source grounding, and confidence gating."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.ai.governed_assistant import (
    GovernedAISecurityError,
    GovernedAssistantEngine,
)
from reconforge.api.dependencies import require_any_permission
from reconforge.api.enterprise_scope import enterprise_transaction
from reconforge.api.errors import APIError
from reconforge.audit.events import append_audit_event
from reconforge.auth import LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.finance_core import FinanceCoreService

router = APIRouter(prefix="/ai/assistant", tags=["governed-ai"])
AIUser = Annotated[LocalUser, Depends(require_any_permission({"ai.query", "finance_core.read"}))]


class AssistantQueryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query_id: str = Field(min_length=1, max_length=64)
    query_text: str = Field(min_length=1, max_length=1000)
    authorized_records: list[dict[str, Any]] = Field(default_factory=list)
    confidence_override: float | None = Field(default=None, ge=0.0, le=1.0)
    record_ids: list[str] = Field(default_factory=list, max_length=25)


def _source_digest(entry: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _evaluate(
    user: LocalUser, payload: AssistantQueryPayload, workspace: str, permissions: frozenset[str], repository: Any
) -> Any:
    if payload.authorized_records or payload.confidence_override is not None:
        raise APIError(
            status_code=403,
            code="assistant_untrusted_context",
            message="Sources and confidence are resolved by the server, not supplied by the caller.",
        )
    if len(set(payload.record_ids)) != len(payload.record_ids) or any(
        not identifier.strip() or len(identifier) > 140 for identifier in payload.record_ids
    ):
        raise APIError(
            status_code=422, code="assistant_record_ids_invalid", message="Select unique bounded source identifiers."
        )
    sources = []
    if payload.record_ids:
        if "finance_core.read" not in permissions:
            raise APIError(
                status_code=403,
                code="assistant_source_permission_denied",
                message="Finance Core read authority is required for selected entries.",
            )
        # The existing repository binds workspace and field/financial policy. A
        # bounded list establishes membership before retrieving any full record.
        allowed = {
            entry["id"] for entry in repository.list_entries(workspace=workspace, limit=500, actor_label=user.username)
        }
        if not set(payload.record_ids) <= allowed:
            raise APIError(
                status_code=404,
                code="assistant_source_not_found",
                message="A selected source is unavailable in the authorized workspace.",
            )
        for identifier in sorted(payload.record_ids):
            entry = repository.get_entry(identifier, actor_label=user.username)
            sources.append(
                {
                    "id": identifier,
                    "workspace_id": workspace,
                    "entity_type": "finance_core_entry",
                    "version_digest": _source_digest(entry),
                    "summary": f"Finance Core entry {entry['entry_number']} ({entry['status']}); no autonomous financial action.",
                }
            )
    engine = GovernedAssistantEngine(workspace_id=workspace, granted_permissions=permissions)
    return engine.evaluate_query(query_id=payload.query_id, query_text=payload.query_text, authorized_records=sources)


@router.post("/query")
def evaluate_assistant_query(user: AIUser, payload: AssistantQueryPayload, request: Request) -> dict[str, Any]:
    with enterprise_transaction(
        request, permissions=frozenset({"ai.query", "finance_core.read"}), permission_mode="any"
    ) as business:
        local_connection = None
        try:
            if business is not None:
                workspace = business.scope.workspace_id
                principal = request.state.server_principal
                permissions = principal.permissions
                repository = PostgresFinanceCoreRepository(business.connection, business.scope.tenant_id)
                response = _evaluate(user, payload, workspace, permissions, repository)
            else:
                db_path = getattr(request.app.state, "db_path", None)
                if db_path is None:
                    raise APIError(
                        status_code=500, code="db_not_configured", message="API database path is not configured."
                    )
                local_connection = sqlite3.connect(db_path)
                local_connection.row_factory = sqlite3.Row
                workspace = getattr(request.state, "workspace_id", "default")
                permissions = frozenset(LocalAuthService(local_connection).roles.user_permissions(user.username))
                response = _evaluate(user, payload, workspace, permissions, FinanceCoreService(local_connection))
            values = {
                "query_id": response.query_id,
                "answer": response.answer,
                "confidence_score": response.confidence_score,
                "cited_evidence_ids": list(response.cited_evidence_ids),
                "data_classification": response.data_classification,
                "requires_clarification": response.requires_clarification,
                "proposals": [asdict(proposal) for proposal in response.proposals],
                "citation_graph": [asdict(node) for node in response.citation_graph],
                "model_version": "deterministic-retrieval-v1",
                "prompt_template_version": "governed-query-v1",
                "confidence_basis": "source-presence heuristic; not a calibrated probability",
                "human_action_required": True,
            }
            metadata = {
                "workspace_id": workspace,
                "query_digest": hashlib.sha256(payload.query_text.encode()).hexdigest(),
                "response_digest": _source_digest(values),
                "source_count": len(response.cited_evidence_ids),
                "model_version": values["model_version"],
                "prompt_template_version": values["prompt_template_version"],
                "tool_version": "finance-core-read-v1",
            }
            if business is not None:
                event = PostgresAuditEventRepository(business.connection, business.scope.tenant_id).append(
                    actor_user_id=user.id,
                    actor_label=user.username,
                    object_type="governed_assistant_query",
                    object_id=payload.query_id,
                    action="assistant_evaluated",
                    metadata=metadata,
                )
            else:
                if local_connection is None:
                    raise APIError(status_code=503, code="assistant_audit_unavailable", message="The assistant audit connection is unavailable.")
                event = append_audit_event(
                    local_connection,
                    actor_user_id=user.id,
                    actor_label=user.username,
                    object_type="governed_assistant_query",
                    object_id=payload.query_id,
                    action="assistant_evaluated",
                    metadata=metadata,
                )
            values["audit_reference"] = event.id
            return values
        except GovernedAISecurityError as exc:
            raise APIError(status_code=403, code=exc.code, message=str(exc)) from exc
        except (FinancePostingError, PlatformError) as exc:
            raise APIError(
                status_code=422,
                code=getattr(exc, "code", "assistant_source_invalid"),
                message="The selected source cannot be evaluated.",
            ) from exc
        finally:
            if local_connection is not None:
                local_connection.close()
