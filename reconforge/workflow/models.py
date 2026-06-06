"""Workflow state machine foundation models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from reconforge.domain.models import new_domain_id, utc_now_text


class _WorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowObject(_WorkflowModel):
    """A local workflow-enabled object reference."""

    id: str = Field(default_factory=lambda: new_domain_id("WF"))
    object_type: str
    object_id: str
    status: str
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)


class WorkflowTransition(_WorkflowModel):
    """An allowed local workflow transition."""

    id: int
    object_type: str
    from_status: str
    to_status: str
    required_permission: str | None = None
    sod_rule: str | None = None
    reason_required: bool = False
    active: bool = True


class WorkflowTransitionEvent(_WorkflowModel):
    """A recorded workflow transition event."""

    id: str = Field(default_factory=lambda: new_domain_id("WFE"))
    workflow_object_id: str
    from_status: str
    to_status: str
    actor_user_id: str | None = None
    actor_label: str
    reason: str = ""
    created_at: str = Field(default_factory=utc_now_text)
