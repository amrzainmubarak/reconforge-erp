"""Risk explanation helpers."""

from __future__ import annotations


def explain_risk(exception_type: str, score: int) -> str:
    """Create a deterministic risk explanation."""

    return (
        f"{exception_type} scored {score}/100 because it may affect ERP traceability, financial statement accuracy, "
        "operational accountability, or audit evidence completeness."
    )


def recommended_action(exception_type: str) -> str:
    """Return a recommended action for a risk category."""

    normalized = exception_type.lower()
    if "gl" in normalized:
        return "Reconcile the accounting entry to source evidence or post an approved correction."
    if "wip" in normalized:
        return "Confirm job status, expected closure date, billing status, and provisioning need."
    if "old_part" in normalized:
        return "Collect return evidence or approve a documented exception."
    if "purchase" in normalized or "po" in normalized:
        return "Confirm purchase approval, receipt, issue, and work-order linkage."
    return "Assign an owner, document root cause, and record remediation."


def responsible_department(exception_type: str) -> str:
    """Infer the primary owner."""

    normalized = exception_type.lower()
    if "invoice" in normalized or "gl" in normalized or "variance" in normalized:
        return "Finance"
    if "stock" in normalized or "old_part" in normalized or "purchase" in normalized:
        return "Stores / Workshop"
    if "wip" in normalized or "work_order" in normalized:
        return "Workshop"
    return "Finance Controller"
