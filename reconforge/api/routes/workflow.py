"""Workflow state machine routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_db, require_any_permission, require_dynamic_policy_user
from reconforge.api.errors import APIError
from reconforge.auth import AuthRepositoryError
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


@router.get("/transitions")
def list_transitions(
    object_type: str,
    current_user: WorkflowRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List transition templates for a workflow object type."""

    try:
        transitions = [
            transition.model_dump(mode="json")
            for transition in WorkflowService(connection).list_allowed_transitions(object_type=object_type)
        ]
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_transitions_failed", message=str(exc)) from exc
    return {"transitions": transitions}


@router.post("/objects")
def create_object(
    payload: CreateWorkflowObjectRequest,
    current_user: WorkflowRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Initialize a local workflow object."""

    try:
        workflow_object = WorkflowService(connection).initialize_object(
            object_type=payload.object_type,
            object_id=payload.object_id,
            status=payload.status,
        )
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_object_create_failed", message=str(exc)) from exc
    return {"object": workflow_object.model_dump(mode="json")}


@router.get("/objects/{object_type}/{object_id}")
def get_object(
    object_type: str,
    object_id: str,
    current_user: WorkflowRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Get local workflow object state."""

    try:
        workflow_object = WorkflowService(connection).get_status(object_type=object_type, object_id=object_id)
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=404, code="workflow_object_not_found", message=str(exc)) from exc
    return {"object": workflow_object.model_dump(mode="json")}


@router.post("/objects/{object_type}/{object_id}/transition")
def transition_object(
    object_type: str,
    object_id: str,
    payload: TransitionRequest,
    current_user: LocalUser = Depends(require_dynamic_policy_user),
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Perform a local workflow transition as the authenticated user."""

    try:
        workflow_object = WorkflowService(connection).perform_transition(
            object_type=object_type,
            object_id=object_id,
            to_status=payload.to_status,
            actor_label=current_user.username,
            reason=payload.reason,
        )
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_transition_failed", message=str(exc)) from exc
    return {"object": workflow_object.model_dump(mode="json")}


@router.get("/objects/{object_type}/{object_id}/history")
def object_history(
    object_type: str,
    object_id: str,
    current_user: WorkflowRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List local workflow transition history."""

    try:
        history = [
            event.model_dump(mode="json")
            for event in WorkflowService(connection).list_history(object_type=object_type, object_id=object_id)
        ]
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        raise APIError(status_code=400, code="workflow_history_failed", message=str(exc)) from exc
    return {"history": history}
