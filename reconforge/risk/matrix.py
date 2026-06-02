"""Risk matrix helpers."""

from __future__ import annotations


def risk_level(score: int) -> str:
    """Map a numeric risk score to a risk level."""

    if score >= 81:
        return "Critical"
    if score >= 61:
        return "High"
    if score >= 31:
        return "Medium"
    return "Low"


def escalation_level(score: int) -> str:
    """Map risk score to escalation level."""

    if score >= 81:
        return "CFO / Internal Audit"
    if score >= 61:
        return "Finance Controller"
    if score >= 31:
        return "Department Manager"
    return "Process Owner"
