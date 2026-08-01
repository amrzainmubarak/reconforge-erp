"""Control matrix exports generated from ReconForge rule packs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from reconforge.io.excel import write_excel_workbook
from reconforge.io.writers import ensure_output_dir, frame_to_records, json_default
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.models import ControlPack, RuleDefinition
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
)


@dataclass(frozen=True)
class ControlMatrixArtifacts:
    """Generated control matrix artifact paths."""

    workbook_path: Path
    csv_path: Path
    json_path: Path
    markdown_path: Path


def _clean(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _md_escape(value: object) -> str:
    return _clean(value).replace("<", "&lt;").replace(">", "&gt;")


def _expected_exceptions_summary(pack_root: Path) -> str:
    path = pack_root / "expected-exceptions.md"
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [_clean(line.lstrip("#- ").strip()) for line in text.splitlines()]
    return " ".join(line for line in lines if line)[:500]


def _risk_area(pack: ControlPack, rule: RuleDefinition) -> str:
    tags = ", ".join(pack.metadata.tags)
    parts = [rule.entity_type, rule.source_file]
    if tags:
        parts.append(tags)
    return " | ".join(part for part in parts if part)


def control_matrix_frame(
    pack_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> pd.DataFrame:
    """Build a control matrix from a local ReconForge rule pack."""

    try:
        pack = load_rule_pack(
            pack_path,
            financial_input_policy=financial_input_policy,
        )
    except (ValidationError, ValueError) as exc:
        raise ValueError("Control pack is invalid. Run `reconforge rules validate` for schema details.") from exc
    pack_root = Path(pack.root_path)
    expected_exceptions = _expected_exceptions_summary(pack_root)
    rows: list[dict[str, Any]] = []
    for rule in sorted(pack.rules, key=lambda item: item.rule_id):
        rows.append(
            {
                "control_id": rule.rule_id,
                "rule_id": rule.rule_id,
                "control_description": rule.rule_name,
                "risk_area": _risk_area(pack, rule),
                "severity": rule.severity,
                "expected_evidence": ", ".join(rule.evidence_fields) if rule.evidence_fields else "rule result row",
                "owner_placeholder": "",
                "frequency_placeholder": "",
                "related_exceptions_placeholder": expected_exceptions,
                "recommended_action": rule.recommended_action,
                "risk_impact": rule.risk_impact,
                "business_impact": rule.business_impact or "",
                "source_file": rule.source_file,
                "pack_id": pack.metadata.pack_id,
                "pack_name": pack.metadata.name,
            },
        )
    return pd.DataFrame(rows)


def _summary_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    severity_counts = matrix["severity"].astype(str).value_counts().to_dict() if not matrix.empty else {}
    rows: list[dict[str, object]] = [
        {"metric": "control_count", "value": len(matrix), "meaning": "Rules represented as control rows."},
        {
            "metric": "high_or_critical_controls",
            "value": int(sum(severity_counts.get(level, 0) for level in ["high", "critical"])),
            "meaning": "Controls with high or critical severity.",
        },
        {
            "metric": "owner_placeholders",
            "value": int(matrix["owner_placeholder"].astype(str).eq("").sum()) if not matrix.empty else 0,
            "meaning": "Rows left for local owner assignment.",
        },
        {
            "metric": "frequency_placeholders",
            "value": int(matrix["frequency_placeholder"].astype(str).eq("").sum()) if not matrix.empty else 0,
            "meaning": "Rows left for local frequency assignment.",
        },
    ]
    for severity, count in sorted(severity_counts.items()):
        rows.append({"metric": f"severity_{severity}", "value": int(count), "meaning": f"Controls marked {severity}."})
    return pd.DataFrame(rows)


def _write_markdown(path: Path, summary: pd.DataFrame, matrix: pd.DataFrame) -> None:
    lines = [
        "# ReconForge Control Matrix",
        "",
        "Generated locally from a ReconForge rule pack. Owner and frequency columns are placeholders for user-controlled workflow documentation.",
        "",
        "This file is not a compliance certification, legal conclusion, audit opinion, or vendor endorsement.",
        "",
        "## Summary",
        "",
        *[f"- {_md_escape(row['metric'])}: {_md_escape(row['value'])}" for _, row in summary.iterrows()],
        "",
        "## Controls",
        "",
    ]
    if matrix.empty:
        lines.append("No controls found.")
    else:
        for _, row in matrix.iterrows():
            lines.append(
                f"- `{_md_escape(row['control_id'])}` {_md_escape(row['control_description'])} "
                f"({_md_escape(row['severity'])}) | evidence: {_md_escape(row['expected_evidence'])}",
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_control_matrix(
    pack_path: Path | str,
    output_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> ControlMatrixArtifacts:
    """Write control matrix artifacts for a local rule pack."""

    matrix = control_matrix_frame(
        pack_path,
        financial_input_policy=financial_input_policy,
    )
    summary = _summary_frame(matrix)
    output_dir = ensure_output_dir(output_path)
    workbook_path = write_excel_workbook(
        {"Control Matrix Summary": summary, "Control Matrix": matrix}, output_dir / "control_matrix.xlsx"
    )
    csv_path = output_dir / "control_matrix.csv"
    matrix.to_csv(csv_path, index=False)
    json_path = output_dir / "control_matrix.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "pack": str(pack_path),
                "summary": frame_to_records(summary),
                "controls": frame_to_records(matrix),
                "workflow_boundary": "Generated control matrix only; no compliance certification, legal conclusion, audit opinion, or vendor endorsement is implied.",
            },
            handle,
            indent=2,
            default=json_default,
        )
    markdown_path = output_dir / "control_matrix.md"
    _write_markdown(markdown_path, summary, matrix)
    return ControlMatrixArtifacts(
        workbook_path=workbook_path,
        csv_path=csv_path,
        json_path=json_path,
        markdown_path=markdown_path,
    )
