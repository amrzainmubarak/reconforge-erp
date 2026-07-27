"""Models for audit evidence folders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt, model_validator

from reconforge.utils.time import utc_now_text


class EvidenceCase(BaseModel):
    """A single exception evidence case."""

    exception_id: str
    exception_type: str
    severity: str
    risk_score: StrictInt | None
    risk_score_status: Literal["valid", "missing", "invalid"] = "valid"
    risk_score_policy: str = "integer-0-to-100-v1"
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

    @model_validator(mode="after")
    def validate_risk_score_policy(self) -> EvidenceCase:
        """Keep risk score value and explicit quality status consistent."""

        if self.risk_score_status == "valid":
            if self.risk_score is None or self.risk_score < 0 or self.risk_score > 100:
                raise ValueError("valid risk_score must be an integer between 0 and 100")
        elif self.risk_score is not None:
            raise ValueError("missing or invalid risk_score must be null")
        return self


class EvidenceArtifact(BaseModel):
    """Generated evidence artifact."""

    exception_id: str
    folder: Path
