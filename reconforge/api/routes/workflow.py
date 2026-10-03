"""Workflow state machine routes for the local API."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_local_db, require_any_permission, require_dynamic_policy_user
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.auth import AuthRepositoryError
from reconforge.auth.field_access import (
    FieldProjection,
    project_workflow_event,
    project_workflow_object,
    project_workflow_transition,
)
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.workflow import WorkflowRepositoryError, WorkflowService, WorkflowServiceError

router = APIRouter(prefix="/workflow", tags=["workflow"])

WorkflowRead = Annotated[
    LocalUser,
    Depends(
        require_any_permission(
            {"db.read", "reconciliation.prepare", "reconciliation.review", "reconciliation.approve", "controls.test"}
        )
    ),
]


class CreateWorkflowObjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    object_id: str
    status: str


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str
    reason: str = ""


def _local_connection(request: Request, connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if server_identity_enabled(request):
        raise APIError(
            status_code=501,
            code="workflow_server_backend_unavailable",
            message="The local workflow state machine is not exposed by the PostgreSQL server boundary.",
        )
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local workflow database is not configured.")
    return connection


def _project_workflow(
    value: object,
    projector: Callable[[dict[str, object]], FieldProjection],
) -> dict[str, object]:
    if not isinstance(value, BaseModel):
        raise APIError(
            status_code=503,
            code="workflow_projection_failed",
            message="Workflow repository returned an invalid response contract.",
        )
    try:
        return projector(value.model_dump(mode="json")).visible
    except (TypeError, ValueError, AttributeError) as exc:
        raise APIError(
            status_code=503,
            code="workflow_projection_failed",
            message="Workflow repository returned an invalid response contract.",
        ) from exc


@router.get("/transitions")
def list_transitions(
    object_type: str,
    request: Request,
    current_user: WorkflowRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List transition templates for a workflow object type."""

    try:
        transitions = [
            _project_workflow(transition, project_workflow_transition)
            for transition in WorkflowService(_local_connection(request, connection)).list_allowed_transitions(object_type=object_type)
        ]
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_transitions_failed", message=str(exc)) from exc
    return {"transitions": transitions}


@router.post("/objects")
def create_object(
    request: Request,
    payload: CreateWorkflowObjectRequest,
    current_user: WorkflowRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Initialize a local workflow object."""

    try:
        workflow_object = WorkflowService(_local_connection(request, connection)).initialize_object(
            object_type=payload.object_type,
            object_id=payload.object_id,
            status=payload.status,
        )
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_object_create_failed", message=str(exc)) from exc
    return {"object": _project_workflow(workflow_object, project_workflow_object)}


@router.get("/objects/{object_type}/{object_id}")
def get_object(
    object_type: str,
    object_id: str,
    request: Request,
    current_user: WorkflowRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Get local workflow object state."""

    try:
        workflow_object = WorkflowService(_local_connection(request, connection)).get_status(object_type=object_type, object_id=object_id)
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=404, code="workflow_object_not_found", message=str(exc)) from exc
    return {"object": _project_workflow(workflow_object, project_workflow_object)}


@router.post("/objects/{object_type}/{object_id}/transition")
def transition_object(
    object_type: str,
    object_id: str,
    request: Request,
    payload: TransitionRequest,
    current_user: LocalUser = Depends(require_dynamic_policy_user),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Perform a local workflow transition as the authenticated user."""

    try:
        workflow_object = WorkflowService(_local_connection(request, connection)).perform_transition(
            object_type=object_type,
            object_id=object_id,
            to_status=payload.to_status,
            actor_label=current_user.username,
            reason=payload.reason,
        )
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_transition_failed", message=str(exc)) from exc
    return {"object": _project_workflow(workflow_object, project_workflow_object)}


@router.get("/objects/{object_type}/{object_id}/history")
def object_history(
    object_type: str,
    object_id: str,
    request: Request,
    current_user: WorkflowRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List local workflow transition history."""

    try:
        history = [
            _project_workflow(event, project_workflow_event)
            for event in WorkflowService(_local_connection(request, connection)).list_history(object_type=object_type, object_id=object_id)
        ]
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_history_failed", message=str(exc)) from exc
    return {"history": history}
