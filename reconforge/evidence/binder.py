"""Generate audit evidence binders from ReconForge output."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pandas as pd

from reconforge.evidence.index import write_evidence_index_html, write_evidence_register
from reconforge.evidence.models import EvidenceArtifact, EvidenceCase
from reconforge.evidence.templates import business_impact, recommended_action, responsible_department
from reconforge.evidence.writer import write_evidence_case
from reconforge.io.writers import write_json


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, keep_default_na=False)
    return pd.DataFrame()


def _candidate_files(input_dir: Path) -> list[Path]:
    preferred = [
        input_dir / "management_pack_stock_gl_all_exceptions.csv",
        input_dir / "management_pack_workorders_all_exceptions.csv",
        input_dir / "stock_gl_all_exceptions.csv",
        input_dir / "workorders_all_exceptions.csv",
    ]
    return [path for path in preferred if path.exists()]


def _risk_filter(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    risk_source = frame["risk_score"] if "risk_score" in frame.columns else pd.Series([0] * len(frame))
    risk_score = pd.to_numeric(risk_source, errors="coerce").fillna(0)
    risk_level = frame.get("risk_level", pd.Series([""] * len(frame))).astype(str).str.lower()
    return frame[(risk_score >= 61) | risk_level.isin({"high", "critical"})].copy()


def _first_nonempty(row: pd.Series, names: list[str]) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() and str(value).lower() not in {"nan", "none"}:
            return str(value)
    return None


def _match_candidates(input_dir: Path, row: pd.Series) -> list[dict[str, Any]]:
    matched = _read_csv_if_exists(input_dir / "stock_gl_matched_transactions.csv")
    if matched.empty:
        matched = _read_csv_if_exists(input_dir / "management_pack_stock_gl_matched_transactions.csv")
    if matched.empty:
        return []
    work_order = _first_nonempty(row, ["work_order", "linked_work_order"])
    source_document = _first_nonempty(row, ["source_document", "reference", "po_number"])
    mask = pd.Series([False] * len(matched))
    if work_order and "work_order" in matched.columns:
        mask = mask | matched["work_order"].astype(str).eq(work_order)
    if source_document:
        for column in ("source_document", "gl_reference"):
            if column in matched.columns:
                mask = mask | matched[column].astype(str).eq(source_document)
    return cast(list[dict[str, Any]], matched[mask].head(10).to_dict(orient="records"))


def _rule_results(input_dir: Path, row: pd.Series) -> list[dict[str, Any]]:
    rules = _read_csv_if_exists(input_dir / "rules" / "rule_results.csv")
    if rules.empty:
        rules = _read_csv_if_exists(input_dir / "rule_results.csv")
    if rules.empty:
        return []
    work_order = _first_nonempty(row, ["work_order", "linked_work_order"])
    if work_order and "evidence_fields" in rules.columns:
        return cast(
            list[dict[str, Any]],
            rules[rules["evidence_fields"].astype(str).str.contains(work_order, regex=False)].head(10).to_dict(
                orient="records",
            ),
        )
    return cast(list[dict[str, Any]], rules.head(10).to_dict(orient="records"))


def _case_from_row(input_dir: Path, row: pd.Series, index: int) -> EvidenceCase:
    exception_type = _first_nonempty(row, ["exception_type", "rule_name"]) or "unclassified_exception"
    risk_score = int(float(row.get("risk_score", row.get("risk_impact", 0)) or 0))
    severity = _first_nonempty(row, ["risk_level", "severity"]) or ("Critical" if risk_score >= 81 else "High")
    source_file = _first_nonempty(row, ["source_file"]) or "generated_report"
    return EvidenceCase(
        exception_id=f"EXC-{index:04d}",
        exception_type=exception_type,
        severity=severity,
        risk_score=risk_score,
        affected_work_order=_first_nonempty(row, ["work_order", "linked_work_order"]),
        affected_product=_first_nonempty(row, ["product_code", "product_code_stock", "product_code_po"]),
        affected_customer=_first_nonempty(row, ["customer_code", "customer_code_stock"]),
        affected_equipment=_first_nonempty(row, ["equipment_serial", "equipment_serial_stock"]),
        source_files=[source_file],
        source_record=row.to_dict(),
        match_candidates=_match_candidates(input_dir, row),
        triggered_rules=_rule_results(input_dir, row),
        business_impact=business_impact(exception_type),
        recommended_action=recommended_action(exception_type),
        responsible_department=responsible_department(exception_type),
    )


def collect_evidence_cases(input_dir: Path | str) -> list[EvidenceCase]:
    """Collect High/Critical exception cases from a generated output folder."""

    base = Path(input_dir)
    frames = [_risk_filter(_read_csv_if_exists(path)) for path in _candidate_files(base)]
    combined = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True, sort=False)
    if combined.empty:
        return []
    cases: list[EvidenceCase] = []
    for index, (_, row) in enumerate(combined.iterrows(), start=1):
        cases.append(_case_from_row(base, row, index))
    return cases


def generate_evidence_binder(input_dir: Path | str, output_dir: Path | str) -> list[EvidenceArtifact]:
    """Generate enterprise-style audit evidence folders."""

    cases = collect_evidence_cases(input_dir)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    artifacts = [write_evidence_case(case, target) for case in cases]
    write_evidence_index_html(cases, target)
    write_evidence_register(cases, target)
    write_json(
        {
            "case_count": len(cases),
            "cases": [case.model_dump(mode="json") for case in cases],
        },
        target,
        "evidence_index",
    )
    return artifacts
