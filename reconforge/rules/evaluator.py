"""Rule evaluation over loaded datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.io.readers import normalize_columns, read_table
from reconforge.rules.models import RuleDefinition
from reconforge.rules.operators import evaluate_condition
from reconforge.rules.results import RuleResult


def _load_source(input_dir: Path, source_file: str) -> pd.DataFrame:
    source_path = input_dir / source_file
    if not source_path.exists():
        raise FileNotFoundError(f"Rule source file not found: {source_path}")
    return normalize_columns(read_table(source_path))


def _load_related_sources(input_dir: Path) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(input_dir.glob("*.csv")):
        frames[path.name] = normalize_columns(read_table(path))
    return frames


def _evidence(row: pd.Series, fields: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in fields:
        value = row.get(field)
        if value is not None and hasattr(value, "item"):
            value = value.item()
        payload[field] = None if pd.isna(value) else value
    return payload


def _first_text(row: pd.Series, fields: list[str]) -> str | None:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip() and str(value).lower() not in {"nan", "none", "nat"}:
            return str(value)
    return None


def _amount_impact(row: pd.Series) -> float:
    for field in ("amount", "total_cost", "actual_cost", "estimated_cost", "invoice_amount", "total_price"):
        value = row.get(field)
        try:
            return abs(float(str(value)))
        except (TypeError, ValueError):
            continue
    return 0.0


def evaluate_rule(input_dir: Path | str, rule: RuleDefinition) -> list[RuleResult]:
    """Evaluate one rule against its source CSV."""

    base = Path(input_dir)
    frame = _load_source(base, rule.source_file)
    related_frames = _load_related_sources(base)
    results: list[RuleResult] = []
    for index, row in frame.iterrows():
        if evaluate_condition(row, rule.condition, frame=frame, related_frames=related_frames):
            source_row = int(str(index)) + 2
            results.append(
                RuleResult(
                    exception_id=f"{rule.rule_id}-{source_row:05d}",
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    severity=rule.severity,
                    confidence=rule.confidence,
                    entity_type=rule.entity_type,
                    source_file=rule.source_file,
                    source_row=source_row,
                    affected_reference=_first_text(row, ["source_document", "reference", "po_number", "invoice_number", "return_id"]),
                    affected_work_order=_first_text(row, ["work_order", "linked_work_order"]),
                    affected_product=_first_text(row, ["product_code", "product_code_stock", "product_code_po"]),
                    affected_customer=_first_text(row, ["customer_code"]),
                    amount_impact=_amount_impact(row),
                    message=rule.message,
                    business_impact=rule.business_impact
                    or "The control failed and should be reviewed before management or audit sign-off.",
                    recommended_action=rule.recommended_action,
                    risk_impact=rule.risk_impact,
                    evidence_fields=_evidence(row, rule.evidence_fields),
                ),
            )
    return results
