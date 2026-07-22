"""Risk scoring for reconciliation exceptions."""

from __future__ import annotations

from dataclasses import dataclass

from reconforge.config import ReconForgeConfig


@dataclass(frozen=True)
class RiskAssessment:
    """Risk score and level."""

    score: int
    level: str


def risk_level(score: int) -> str:
    """Classify a numeric risk score."""

    if score <= 30:
        return "Low"
    if score <= 60:
        return "Medium"
    if score <= 80:
        return "High"
    return "Critical"


def amount_component(amount: float, baseline: float = 1000.0) -> int:
    """Scale amount exposure into a small risk component."""

    if amount <= 0:
        return 0
    return min(int((amount / baseline) * 20), 40)


def assess_risk(
    exception_type: str,
    config: ReconForgeConfig,
    *,
    amount: float = 0.0,
    amount_difference: float = 0.0,
    aging_days: int = 0,
) -> RiskAssessment:
    """Score a reconciliation exception from 0 to 100."""

    weights = config.risk_scoring_weights
    normalized = exception_type.lower()
    base_scores = {
        "amount_mismatch": weights.amount_mismatch,
        "value_difference": weights.amount_mismatch,
        "missing_gl_entry": weights.missing_gl_entry,
        "stock_without_gl": weights.missing_gl_entry,
        "missing_stock_movement": weights.missing_stock_movement,
        "gl_without_stock": weights.missing_stock_movement,
        "wip_over_90_days": weights.wip_over_90_days,
        "direct_purchase_fit": weights.direct_purchase_fit,
        "missing_old_part_return": weights.missing_old_part_return,
        "duplicate_reference": weights.duplicate_reference,
        "closed_work_order_without_invoice": weights.closed_work_order_without_invoice,
        "closed_work_order_with_pending_stock": weights.closed_work_order_without_invoice,
        "cancelled_po_linked_to_movement": weights.cancelled_po_linked_to_movement,
        "invalid_master_reference": weights.invalid_master_reference,
        "parts_issued_without_work_order": weights.invalid_master_reference,
        "work_order_cost_without_invoice": weights.closed_work_order_without_invoice,
        "data_quality": weights.invalid_financial_value,
        "reference_mismatch": weights.invalid_master_reference,
    }
    score = base_scores.get(normalized, 25)
    score += amount_component(abs(amount))
    score += amount_component(abs(amount_difference), baseline=250.0)
    if aging_days > 90:
        score += min((aging_days - 90) // 15, 15)
    score = max(0, min(score, 100))
    return RiskAssessment(score=score, level=risk_level(score))
