"""High-level rule pack execution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.io.writers import ensure_output_dir, write_csv, write_json
from reconforge.rules.evaluator import evaluate_rule
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.results import RuleResult, results_to_records


def run_rule_pack(input_dir: Path | str, pack_path: Path | str) -> list[RuleResult]:
    """Run all rules in a control pack."""

    pack = load_rule_pack(pack_path)
    results: list[RuleResult] = []
    for rule in pack.rules:
        results.extend(evaluate_rule(input_dir, rule))
    return results


def write_rule_results(results: list[RuleResult], output_dir: Path | str) -> list[Path]:
    """Write rule results as CSV and JSON."""

    target = ensure_output_dir(output_dir)
    records = results_to_records(results)
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(
            columns=[
                "rule_id",
                "rule_name",
                "severity",
                "confidence",
                "entity_type",
                "source_file",
                "source_row",
                "affected_reference",
                "affected_work_order",
                "affected_product",
                "affected_customer",
                "amount_impact",
                "message",
                "business_impact",
                "recommended_action",
                "risk_impact",
                "evidence_fields",
                "triggered_at",
            ],
        )
    csv_path = write_csv(frame, target, "rule_results")
    json_path = write_json({"results": records}, target, "rule_results")
    return [csv_path, json_path]
