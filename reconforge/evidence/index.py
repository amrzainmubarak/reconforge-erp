"""Evidence binder index writers."""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from reconforge.evidence.models import EvidenceCase


def _risk_score_display(case: EvidenceCase) -> str:
    if case.risk_score_status == "valid" and case.risk_score is not None:
        return str(case.risk_score)
    return f"Unavailable ({case.risk_score_status})"


def evidence_register_frame(cases: list[EvidenceCase]) -> pd.DataFrame:
    """Return an evidence register DataFrame."""

    return pd.DataFrame(
        [
            {
                "exception_id": case.exception_id,
                "exception_type": case.exception_type,
                "severity": case.severity,
                "risk_score": case.risk_score,
                "risk_score_status": case.risk_score_status,
                "risk_score_policy": case.risk_score_policy,
                "affected_work_order": case.affected_work_order,
                "affected_product": case.affected_product,
                "affected_customer": case.affected_customer,
                "responsible_department": case.responsible_department,
                "recommended_action": case.recommended_action,
                "status": case.review_status,
                "reviewer": case.reviewer,
                "note": case.review_note,
                "updated_at": case.review_updated_at,
                "decision_reason": case.decision_reason,
                "accepted_risk_reason": case.accepted_risk_reason,
                "escalation_owner": case.escalation_owner,
                "prepared_by": case.prepared_by,
                "prepared_at": case.prepared_at,
                "reviewed_by": case.reviewed_by,
                "reviewed_at": case.reviewed_at,
                "certification_status": case.certification_status,
                "certification_note": case.certification_note,
                "generated_at": case.generated_at,
            }
            for case in cases
        ],
    )


def write_evidence_register(cases: list[EvidenceCase], output_dir: Path | str) -> Path:
    """Write the Excel evidence register."""

    target = Path(output_dir)
    register = target / "evidence_register.xlsx"
    with pd.ExcelWriter(register, engine="openpyxl") as writer:
        evidence_register_frame(cases).to_excel(writer, sheet_name="Evidence Register", index=False)
    return register


def write_evidence_index_html(cases: list[EvidenceCase], output_dir: Path | str) -> Path:
    """Write a local HTML evidence index."""

    target = Path(output_dir)
    rows = []
    for case in cases:
        rows.append(
            "<tr>"
            f"<td><a href='{quote(case.exception_id, safe='')}/summary.md'>{escape(case.exception_id)}</a></td>"
            f"<td>{escape(case.exception_type)}</td>"
            f"<td>{escape(case.severity)}</td>"
            f"<td>{escape(_risk_score_display(case))}</td>"
            f"<td>{escape(case.review_status)}</td>"
            f"<td>{escape(case.affected_work_order or '')}</td>"
            f"<td>{escape(case.responsible_department)}</td>"
            "</tr>",
        )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ReconForge Evidence Binder</title>
  <style>
    body {{ font-family: Inter, Segoe UI, Arial, sans-serif; margin: 32px; color: #182230; }}
    h1 {{ color: #17324d; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #e4e7ec; padding: 10px; text-align: left; }}
    th {{ background: #edf3f8; }}
  </style>
</head>
<body>
  <h1>ReconForge Evidence Binder</h1>
  <p>High and Critical exception evidence folders generated locally.</p>
  <table>
    <thead><tr><th>Case</th><th>Type</th><th>Severity</th><th>Risk</th><th>Status</th><th>Work Order</th><th>Owner</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""
    path = target / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
