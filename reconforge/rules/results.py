"""Rule execution results."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from reconforge.utils.time import utc_now_text


class RuleResult(BaseModel):
    """A triggered rule result."""

    exception_id: str = ""
    rule_id: str
    rule_name: str
    severity: str
    confidence: float = 0.9
    entity_type: str
    source_file: str
    source_row: int
    affected_reference: str | None = None
    affected_work_order: str | None = None
    affected_product: str | None = None
    affected_customer: str | None = None
    amount_impact: Decimal | None = None
    message: str
    business_impact: str = "The control failed and should be reviewed before management or audit sign-off."
    recommended_action: str
    risk_impact: int
    evidence_fields: dict[str, Any] = Field(default_factory=dict)
    triggered_at: str = Field(default_factory=utc_now_text)


def results_to_records(results: list[RuleResult]) -> list[dict[str, Any]]:
    """Convert rule results to JSON-safe records."""

    return [result.model_dump(mode="json") for result in results]
