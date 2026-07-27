"""Rule explanation helpers."""

from __future__ import annotations

from reconforge.rules.loader import load_rule_pack
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
)


def explain_rule(
    pack_path: str,
    rule_id: str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> str:
    """Return a deterministic plain-English explanation for a rule."""

    pack = load_rule_pack(
        pack_path,
        financial_input_policy=financial_input_policy,
    )
    for rule in pack.rules:
        if rule.rule_id == rule_id:
            evidence = ", ".join(rule.evidence_fields) if rule.evidence_fields else "source row fields"
            return (
                f"{rule.rule_id} - {rule.rule_name}\n"
                f"Severity: {rule.severity}\n"
                f"Entity: {rule.entity_type} from {rule.source_file}\n"
                f"Condition operator: {rule.condition.operator}\n"
                f"Business impact: {rule.business_impact or rule.message}\n"
                f"Evidence captured: {evidence}\n"
                f"Recommended action: {rule.recommended_action}"
            )
    raise ValueError(f"Rule not found in pack: {rule_id}")
