"""Markdown templates for evidence binders."""

from __future__ import annotations

from reconforge.evidence.models import EvidenceCase


def business_impact(exception_type: str) -> str:
    """Return a business impact statement for an exception type."""

    normalized = exception_type.lower()
    if "stock_without_gl" in normalized or "missing_gl" in normalized:
        return "Inventory consumption may not be reflected in financial statements, creating understatement risk."
    if "gl_without_stock" in normalized:
        return "A GL expense may lack operational source evidence, creating unsupported posting risk."
    if "old_part" in normalized:
        return "Replacement-part control evidence is incomplete and may indicate missing returned cores or assets."
    if "direct_purchase" in normalized:
        return "Direct purchase-and-fit can bypass stores receipt and issue controls."
    if "wip" in normalized:
        return "Open WIP may be stale, unrecoverable, or missing closure action."
    return "The exception indicates a control gap that should be reviewed before audit sign-off."


def responsible_department(exception_type: str) -> str:
    """Infer the most likely responsible department."""

    normalized = exception_type.lower()
    if "gl" in normalized or "invoice" in normalized or "value" in normalized:
        return "Finance"
    if "stock" in normalized or "old_part" in normalized or "purchase" in normalized:
        return "Stores / Workshop"
    if "wip" in normalized or "work_order" in normalized:
        return "Workshop"
    return "Finance Controller"


def recommended_action(exception_type: str) -> str:
    """Infer a default recommended action."""

    normalized = exception_type.lower()
    if "stock_without_gl" in normalized:
        return "Trace the source movement to inventory valuation and post or explain the missing GL impact."
    if "gl_without_stock" in normalized:
        return "Obtain source-document support or reclassify/reverse the unsupported GL posting."
    if "old_part" in normalized:
        return "Collect the old part, attach disposal evidence, or approve a documented exception."
    if "direct_purchase" in normalized:
        return "Attach purchase approval, goods receipt evidence, installation confirmation, and work-order authorization."
    if "cancelled_po" in normalized:
        return "Confirm whether the PO was reinstated or reverse the linked movement and related accounting."
    if "invoice" in normalized:
        return "Confirm invoice status, billing hold reason, and expected closure date."
    return "Assign an owner, document root cause, and record the remediation decision."


def summary_markdown(case: EvidenceCase) -> str:
    """Render an evidence summary."""

    return f"""# Evidence Binder: {case.exception_id}

## Exception Summary

| Field | Value |
| --- | --- |
| Exception ID | {case.exception_id} |
| Exception Type | {case.exception_type} |
| Severity | {case.severity} |
| Risk Score | {case.risk_score} |
| Work Order | {case.affected_work_order or ""} |
| Product | {case.affected_product or ""} |
| Customer | {case.affected_customer or ""} |
| Equipment | {case.affected_equipment or ""} |
| Responsible Department | {case.responsible_department} |
| Review Status | {case.review_status} |
| Reviewer | {case.reviewer} |
| Review Updated At | {case.review_updated_at} |
| Review Note | {case.review_note} |

## Business Impact

{case.business_impact}

## Recommended Action

{case.recommended_action}

## Source Files

{chr(10).join(f"- {source}" for source in case.source_files) if case.source_files else "- Not identified"}

## Audit Note Template

- Observation:
- Evidence reviewed:
- Root cause:
- Financial impact:
- Operational impact:
- Management response:
- Target closure date:
- Reviewer:

Generated at: {case.generated_at}
"""


def action_markdown(case: EvidenceCase) -> str:
    """Render the recommended action file."""

    return f"""# Recommended Action: {case.exception_id}

Owner: {case.responsible_department}

{case.recommended_action}

Suggested evidence to collect:

- ERP source document screenshots or exports
- Work-order approval trail
- Stores receipt and issue evidence
- GL journal or inventory valuation posting
- Invoice, credit note, or billing hold explanation
- Management approval for unresolved exceptions
"""


def review_form_markdown(case: EvidenceCase) -> str:
    """Render an auditor/manager review form."""

    return f"""# Review Form: {case.exception_id}

## Review Questions

1. What happened?
   - {case.exception_type}

2. Why is it risky?
   - {case.business_impact}

3. Which records prove it?
   - See `source_records.csv` and `match_candidates.csv`.

4. Which control failed?
   - See `triggered_rules.yml` and exception type `{case.exception_type}`.

5. What should be done?
   - {case.recommended_action}

6. Who should review it?
   - {case.responsible_department}

## Current Local Review State

| Field | Value |
| --- | --- |
| Status | {case.review_status} |
| Reviewer | {case.reviewer} |
| Updated at | {case.review_updated_at} |
| Note | {case.review_note} |
| Decision reason | {case.decision_reason} |
| Accepted risk reason | {case.accepted_risk_reason} |
| Escalation owner | {case.escalation_owner} |

## Reviewer Completion

| Field | Response |
| --- | --- |
| Reviewer |  |
| Review date |  |
| Root cause |  |
| Financial impact confirmed |  |
| Operational impact confirmed |  |
| Corrective action owner |  |
| Target closure date |  |
| Final disposition | Open / Accepted / Remediated / False positive |

## Suggested Audit Note

Reviewed exception {case.exception_id}. The exception was rated {case.severity} with risk score {case.risk_score}. Management should document evidence reviewed, root cause, financial impact, and closure action.
"""
