"""Fail-closed, provider-neutral write-back intent lifecycle.

This module deliberately does not perform network I/O.  It records the
authorization and acknowledgement contract that a future connector adapter
must satisfy before it can send a provider mutation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WritebackError(ValueError):
    """Raised when a write-back lifecycle transition is unsafe or invalid."""


class WritebackStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    COMPENSATION_REQUESTED = "compensation_requested"
    COMPENSATED = "compensated"
    REJECTED = "rejected"
    FAILED = "failed"


class WritebackApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=256)
    approved_at: datetime
    assurance: Literal["step_up", "mfa"]
    reason: str = Field(min_length=1, max_length=2_000)


class WritebackAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_reference: str = Field(min_length=1, max_length=512)
    acknowledged_at: datetime
    response_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    accepted: bool


class WritebackIntent(BaseModel):
    """An immutable description of one proposed provider mutation.

    The payload itself is intentionally absent.  A connector resolves the
    digest-bound payload from an authorized, short-lived store at dispatch;
    this contract never persists or returns credentials or financial rows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["connector-writeback-intent-v1"]
    intent_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)
    connector_id: str = Field(min_length=1, max_length=128)
    operation: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,127}$")
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=256)
    requested_at: datetime
    feature_enabled: bool = False
    status: WritebackStatus = WritebackStatus.PROPOSED
    approval: WritebackApproval | None = None
    acknowledgement: WritebackAcknowledgement | None = None
    compensation_reason: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_state(self) -> WritebackIntent:
        if self.status is not WritebackStatus.PROPOSED and not self.feature_enabled:
            raise ValueError("write-back feature flag must be enabled before transition")
        if self.status in {
            WritebackStatus.APPROVED,
            WritebackStatus.DISPATCHED,
            WritebackStatus.ACKNOWLEDGED,
            WritebackStatus.COMPENSATION_REQUESTED,
            WritebackStatus.COMPENSATED,
        } and self.approval is None:
            raise ValueError("human approval is required for this write-back state")
        if self.approval is not None and self.approval.actor_id == self.requested_by:
            raise ValueError("requester cannot approve their own write-back")
        if self.status in {WritebackStatus.ACKNOWLEDGED, WritebackStatus.COMPENSATED} and self.acknowledgement is None:
            raise ValueError("acknowledgement is required for this write-back state")
        if self.status is WritebackStatus.COMPENSATED and not self.compensation_reason:
            raise ValueError("compensation reason is required")
        return self

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WritebackPolicy:
    """Operator policy for one connector registration."""

    connector_id: str
    allowed_operations: frozenset[str]
    feature_enabled: bool = False
    require_step_up: bool = True

    def authorize(self, intent: WritebackIntent) -> None:
        if not self.feature_enabled or not intent.feature_enabled:
            raise WritebackError("writeback_feature_disabled")
        if intent.connector_id != self.connector_id:
            raise WritebackError("writeback_connector_not_allowed")
        if intent.operation not in self.allowed_operations:
            raise WritebackError("writeback_operation_not_allowed")
        if self.require_step_up and intent.approval is not None and intent.approval.assurance not in {"step_up", "mfa"}:
            raise WritebackError("writeback_assurance_required")


def approve_writeback(
    intent: WritebackIntent,
    *,
    policy: WritebackPolicy,
    actor_id: str,
    approved_at: datetime,
    assurance: Literal["step_up", "mfa"],
    reason: str,
) -> WritebackIntent:
    """Approve once, with a distinct human actor and explicit assurance."""

    if intent.status is not WritebackStatus.PROPOSED:
        raise WritebackError("writeback_approval_state_invalid")
    if actor_id == intent.requested_by:
        raise WritebackError("writeback_self_approval_denied")
    approval = WritebackApproval(
        actor_id=actor_id,
        approved_at=approved_at,
        assurance=assurance,
        reason=reason,
    )
    approved = intent.model_copy(update={"status": WritebackStatus.APPROVED, "approval": approval})
    policy.authorize(approved)
    return approved


def dispatch_writeback(intent: WritebackIntent, *, policy: WritebackPolicy) -> WritebackIntent:
    """Mark an approved intent ready for exactly-once provider dispatch."""

    policy.authorize(intent)
    if intent.status is not WritebackStatus.APPROVED:
        raise WritebackError("writeback_dispatch_requires_approval")
    return intent.model_copy(update={"status": WritebackStatus.DISPATCHED})


def acknowledge_writeback(
    intent: WritebackIntent,
    *,
    provider_reference: str,
    response_digest: str,
    acknowledged_at: datetime,
    accepted: bool,
) -> WritebackIntent:
    """Bind one provider acknowledgement to the original idempotency key."""

    if intent.status is not WritebackStatus.DISPATCHED:
        raise WritebackError("writeback_acknowledgement_state_invalid")
    acknowledgement = WritebackAcknowledgement(
        provider_reference=provider_reference,
        acknowledged_at=acknowledged_at,
        response_digest=response_digest,
        idempotency_key=intent.idempotency_key,
        accepted=accepted,
    )
    return intent.model_copy(update={"status": WritebackStatus.ACKNOWLEDGED, "acknowledgement": acknowledgement})


def request_compensation(intent: WritebackIntent, *, reason: str) -> WritebackIntent:
    """Request a separately auditable compensation after dispatch/ack."""

    if intent.status not in {WritebackStatus.DISPATCHED, WritebackStatus.ACKNOWLEDGED}:
        raise WritebackError("writeback_compensation_state_invalid")
    if not reason.strip():
        raise WritebackError("writeback_compensation_reason_required")
    return intent.model_copy(
        update={"status": WritebackStatus.COMPENSATION_REQUESTED, "compensation_reason": reason}
    )


def complete_compensation(intent: WritebackIntent, *, acknowledgement: WritebackAcknowledgement) -> WritebackIntent:
    if intent.status is not WritebackStatus.COMPENSATION_REQUESTED:
        raise WritebackError("writeback_compensation_not_requested")
    if acknowledgement.idempotency_key != intent.idempotency_key + ":compensation":
        raise WritebackError("writeback_compensation_idempotency_mismatch")
    return intent.model_copy(update={"status": WritebackStatus.COMPENSATED, "acknowledgement": acknowledgement})
