"""Reusable workflow state transition validation."""

from __future__ import annotations

from dataclasses import dataclass

from reconforge.workflow.models import WorkflowTransition


class WorkflowStateError(ValueError):
    """Raised for safe, user-facing workflow state errors."""


@dataclass(frozen=True)
class TransitionValidation:
    """Validated workflow transition details."""

    transition: WorkflowTransition
    reason: str


class WorkflowStateMachine:
    """Validate state transitions from a known transition set."""

    def __init__(self, transitions: list[WorkflowTransition]) -> None:
        self._transitions = [transition for transition in transitions if transition.active]

    def allowed_from(self, status: str) -> list[WorkflowTransition]:
        """List active transitions allowed from a status."""

        return [transition for transition in self._transitions if transition.from_status == status]

    def validate(self, *, from_status: str, to_status: str, reason: str = "") -> TransitionValidation:
        """Validate a transition and required reason."""

        for transition in self.allowed_from(from_status):
            if transition.to_status != to_status:
                continue
            clean_reason = reason.strip()
            if transition.reason_required and not clean_reason:
                raise WorkflowStateError("Workflow transition requires a reason.")
            return TransitionValidation(transition=transition, reason=clean_reason)
        raise WorkflowStateError(f"Invalid workflow transition: {from_status} -> {to_status}.")
