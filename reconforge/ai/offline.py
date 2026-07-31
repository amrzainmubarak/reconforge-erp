"""Deterministic offline explanation provider."""

from __future__ import annotations


def offline_exception_explanation(exception: dict[str, object]) -> str:
    """Explain an exception without external services."""

    exception_id = str(exception.get("exception_id") or exception.get("rule_id") or "EXC-UNKNOWN")
    exception_type = str(exception.get("exception_type") or exception.get("rule_name") or "unclassified exception")
    risk = str(exception.get("risk_score") or exception.get("risk_impact") or "not scored")
    work_order = str(exception.get("work_order") or exception.get("affected_work_order") or "")
    reference = str(
        exception.get("source_document") or exception.get("reference") or exception.get("affected_reference") or ""
    )
    action = str(
        exception.get("recommended_action") or "Assign an owner, review source evidence, and document remediation."
    )
    return (
        f"{exception_id}: {exception_type} has risk score {risk}. "
        f"Reference: {reference or 'not identified'}. Work order: {work_order or 'not identified'}. "
        f"Recommended action: {action}"
    )
