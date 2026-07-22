"""Models for audit evidence folders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from reconforge.utils.time import utc_now_text


class EvidenceCase(BaseModel):
    """A single exception evidence case."""

    exception_id: str
    exception_type: str
    severity: str
    risk_score: int
    affected_work_order: str | None = None
    affected_product: str | None = None
    affected_customer: str | None = None
    affected_equipment: str | None = None
    source_files: list[str] = Field(default_factory=list)
    source_record: dict[str, Any] = Field(default_factory=dict)
    match_candidates: list[dict[str, Any]] = Field(default_factory=list)
    triggered_rules: list[dict[str, Any]] = Field(default_factory=list)
    business_impact: str
    recommended_action: str
    responsible_department: str
    review_status: str = "New"
    reviewer: str = ""
    review_note: str = ""
    review_updated_at: str = ""
    decision_reason: str = ""
    accepted_risk_reason: str = ""
    escalation_owner: str = ""
    prepared_by: str = ""
    prepared_at: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    certification_status: str = ""
    certification_note: str = ""
    generated_at: str = Field(default_factory=utc_now_text)


class EvidenceArtifact(BaseModel):
    """Generated evidence artifact."""

    exception_id: str
    folder: Path
