"""Workflow state machine service with optional local RBAC and SoD checks."""

from __future__ import annotations

import sqlite3

from reconforge.auth import AuthRepositoryError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.auth.rbac import check_sod_conflict
from reconforge.platform.common import (
    PlatformError,
    audit,
    commit_audited,
    current_server_principal,
    is_trusted_local_mode,
)
from reconforge.workflow.models import WorkflowObject, WorkflowTransition, WorkflowTransitionEvent
from reconforge.workflow.repositories import WorkflowRepository, WorkflowRepositoryError
from reconforge.workflow.state_machine import WorkflowStateError, WorkflowStateMachine


class WorkflowServiceError(ValueError):
    """Raised for safe, user-facing workflow service errors."""


_STATUS_TO_ACTION = {
    "Prepared": "prepare",
    "In Review": "submit",
    "Reviewed": "review",
    "Complete": "approve",
    "Accepted Risk": "approve",
}


class WorkflowService:
    """Reusable local workflow service."""

    def __init__(self, connection: sqlite3.Connection, *, autocommit: bool = True) -> None:
        self.connection = connection
        self.repository = WorkflowRepository(connection, autocommit=autocommit)
        self.auth = LocalAuthService(connection)

    def list_allowed_transitions(self, *, object_type: str, status: str | None = None) -> list[WorkflowTransition]:
        transitions = self.repository.list_transitions(object_type=object_type)
        if status is None:
            return transitions
        return WorkflowStateMachine(transitions).allowed_from(status)

    def initialize_object(self, *, object_type: str, object_id: str, status: str) -> WorkflowObject:
        transitions = self.repository.list_transitions(object_type=object_type)
        known_statuses = {transition.from_status for transition in transitions} | {
            transition.to_status for transition in transitions
        }
        if status not in known_statuses:
            raise WorkflowServiceError(f"Unknown workflow status for {object_type}: {status}.")
        try:
            return self.repository.create_object(object_type=object_type, object_id=object_id, status=status)
        except WorkflowRepositoryError as exc:
            raise WorkflowServiceError(str(exc)) from exc

    def get_status(self, *, object_type: str, object_id: str) -> WorkflowObject:
        workflow_object = self.repository.get_object(object_type=object_type, object_id=object_id)
        if workflow_object is None:
            raise WorkflowServiceError("Workflow object not found.")
        return workflow_object

    def validate_transition(
        self, *, object_type: str, from_status: str, to_status: str, reason: str = ""
    ) -> WorkflowTransition:
        transitions = self.repository.list_transitions(object_type=object_type)
        try:
            return (
                WorkflowStateMachine(transitions)
                .validate(
                    from_status=from_status,
                    to_status=to_status,
                    reason=reason,
                )
                .transition
            )
        except WorkflowStateError as exc:
            raise WorkflowServiceError(str(exc)) from exc

    def perform_transition(
        self,
        *,
        object_type: str,
        object_id: str,
        to_status: str,
        actor_label: str = "local-cli",
        reason: str = "",
    ) -> WorkflowObject:
        workflow_object = self.get_status(object_type=object_type, object_id=object_id)
        transitions = self.repository.list_transitions(object_type=object_type)
        try:
            validation = WorkflowStateMachine(transitions).validate(
                from_status=workflow_object.status,
                to_status=to_status,
                reason=reason,
            )
        except WorkflowStateError as exc:
            raise WorkflowServiceError(str(exc)) from exc

        actor_user = self._resolve_actor_user(actor_label)
        principal = current_server_principal()
        if principal is not None and actor_user is None:
            raise WorkflowServiceError("Authenticated actor label must match the current server principal.")
        if actor_user is None and not is_trusted_local_mode():
            raise WorkflowServiceError("Authenticated actor required outside trusted local mode.")
        self._check_permission_if_needed(actor_user=actor_user, transition=validation.transition)
        self._check_sod_if_needed(
            workflow_object=workflow_object,
            actor_user=actor_user,
            actor_label=actor_label,
            transition=validation.transition,
        )

        try:
            updated = self.repository.update_status(
                workflow_object=workflow_object,
                status=to_status,
                autocommit=False,
            )
            self.repository.record_event(
                workflow_object=workflow_object,
                from_status=workflow_object.status,
                to_status=to_status,
                actor_user_id=actor_user.id if actor_user is not None else None,
                actor_label=actor_label or "local-cli",
                reason=validation.reason,
                autocommit=False,
            )
            if self.repository.autocommit:
                commit_audited(
                    self.connection,
                    actor_label=actor_label,
                    object_type=object_type,
                    object_id=object_id,
                    action="workflow_transition",
                    metadata={
                        "object_type": object_type,
                        "object_id": object_id,
                        "from_status": workflow_object.status,
                        "to_status": to_status,
                        "actor_label": actor_label or "local-cli",
                        "reason": validation.reason,
                    },
                )
            else:
                audit(
                    self.connection,
                    actor_label=actor_label,
                    object_type=object_type,
                    object_id=object_id,
                    action="workflow_transition",
                    metadata={
                        "object_type": object_type,
                        "object_id": object_id,
                        "from_status": workflow_object.status,
                        "to_status": to_status,
                        "actor_label": actor_label or "local-cli",
                        "reason": validation.reason,
                    },
                )
        except (WorkflowRepositoryError, PlatformError) as exc:
            if not self.repository.autocommit:
                self.connection.rollback()
            raise WorkflowServiceError("Unable to persist workflow transition with audit evidence.") from exc
        return updated

    def list_history(self, *, object_type: str, object_id: str) -> list[WorkflowTransitionEvent]:
        workflow_object = self.get_status(object_type=object_type, object_id=object_id)
        try:
            return self.repository.list_events(workflow_object_id=workflow_object.id)
        except WorkflowRepositoryError as exc:
            raise WorkflowServiceError(str(exc)) from exc

    def _resolve_actor_user(self, actor_label: str) -> LocalUser | None:
        if not actor_label:
            return None
        principal = current_server_principal()
        if principal is not None:
            return principal.user if principal.user.username == actor_label else None
        try:
            return self.auth.users.get_by_username(actor_label)
        except AuthRepositoryError as exc:
            raise WorkflowServiceError(str(exc)) from exc

    def _check_permission_if_needed(self, *, actor_user: LocalUser | None, transition: WorkflowTransition) -> None:
        if actor_user is None or transition.required_permission is None:
            return
        principal = current_server_principal()
        if principal is not None:
            if transition.required_permission not in principal.permissions:
                raise WorkflowServiceError("Workflow actor does not have the required permission.")
            return
        if not self.auth.user_has_permission(username=actor_user.username, permission=transition.required_permission):
            raise WorkflowServiceError("Workflow actor does not have the required permission.")

    def _check_sod_if_needed(
        self,
        *,
        workflow_object: WorkflowObject,
        actor_user: LocalUser | None,
        actor_label: str,
        transition: WorkflowTransition,
    ) -> None:
        if transition.sod_rule is None:
            return
        action = _STATUS_TO_ACTION.get(transition.to_status)
        if action is None:
            return
        prior_actions: list[tuple[str, str, str, str]] = []
        for event in self.repository.list_events(workflow_object_id=workflow_object.id):
            prior_action = _STATUS_TO_ACTION.get(event.to_status)
            if prior_action is None:
                continue
            prior_identity = event.actor_user_id or f"label:{event.actor_label.strip().casefold()}"
            prior_actions.append(
                (
                    prior_identity,
                    workflow_object.object_type,
                    workflow_object.object_id,
                    prior_action,
                )
            )
        actor_identity = actor_user.id if actor_user is not None else f"label:{actor_label.strip().casefold()}"
        result = check_sod_conflict(
            user_id=actor_identity,
            object_type=workflow_object.object_type,
            object_id=workflow_object.object_id,
            action=action,
            prior_actions=prior_actions,
        )
        if not result.allowed:
            raise WorkflowServiceError(result.reason)
