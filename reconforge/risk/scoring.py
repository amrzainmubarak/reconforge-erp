"""Risk scoring functions."""

from __future__ import annotations

from typing import Any

BASE_WEIGHTS: dict[str, int] = {
    "missing_gl": 75,
    "stock_without_gl": 75,
    "missing_stock": 72,
    "gl_without_stock": 72,
    "duplicate_reference": 55,
    "missing_work_order": 65,
    "old_wip": 70,
    "direct_purchase_fitting": 78,
    "old_part_return_missing": 68,
    "cancelled_po_linkage": 82,
    "closed_job_without_invoice": 66,
    "repeated_repairs": 58,
    "high_variance": 70,
    "high_risk_account": 68,
    "high_risk_user": 62,
    "backdated_transaction": 60,
    "manual_journal": 64,
    "weekend_after_hours": 50,
}


def score_exception(exception_type: str, factors: dict[str, Any] | None = None) -> int:
    """Score an exception from 0 to 100 using deterministic risk factors."""

    normalized = exception_type.lower()
    score = 25
    for key, weight in BASE_WEIGHTS.items():
        if key in normalized:
            score = max(score, weight)
    factors = factors or {}
    amount = abs(float(factors.get("amount", factors.get("amount_impact", 0)) or 0))
    variance = abs(float(factors.get("variance", factors.get("amount_difference", 0)) or 0))
    aging_days = int(float(factors.get("aging_days", 0) or 0))
    if amount >= 10000:
        score += 15
    elif amount >= 1000:
        score += 8
    if variance >= 1000:
        score += 12
    elif variance > 0:
        score += 5
    if aging_days >= 180:
        score += 15
    elif aging_days >= 90:
        score += 10
    for flag in ("manual_journal", "backdated_transaction", "high_risk_user", "weekend_after_hours"):
        if bool(factors.get(flag)):
            score += 7
    return max(0, min(100, int(score)))
