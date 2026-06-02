"""Models for audit evidence folders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


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
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z")


class EvidenceArtifact(BaseModel):
    """Generated evidence artifact."""

    exception_id: str
    folder: Path
