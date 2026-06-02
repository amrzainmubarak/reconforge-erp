"""Risk assessment engine."""

from __future__ import annotations

from typing import Any

from reconforge.risk.explain import explain_risk, recommended_action, responsible_department
from reconforge.risk.matrix import escalation_level, risk_level
from reconforge.risk.models import RiskAssessment
from reconforge.risk.scoring import score_exception


def assess_exception_risk(exception_type: str, factors: dict[str, Any] | None = None) -> RiskAssessment:
    """Assess risk for an exception with deterministic logic."""

    score = score_exception(exception_type, factors)
    level = risk_level(score)
    return RiskAssessment(
        score=score,
        level=level,
        explanation=explain_risk(exception_type, score),
        recommended_action=recommended_action(exception_type),
        responsible_department=responsible_department(exception_type),
        escalation_level=escalation_level(score),
        suggested_audit_note=(
            f"Reviewed {exception_type} exception rated {level}. Management should document source evidence, "
            "root cause, financial impact, and remediation owner."
        ),
    )
