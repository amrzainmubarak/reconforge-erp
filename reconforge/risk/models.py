"""Risk intelligence models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    """Enterprise-oriented risk assessment for an exception."""

    score: int = Field(ge=0, le=100)
    level: str
    explanation: str
    recommended_action: str
    responsible_department: str
    escalation_level: str
    suggested_audit_note: str
