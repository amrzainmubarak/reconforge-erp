"""Control pack loading and validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from reconforge.io.structured import StructuredDocumentError, read_yaml_document
from reconforge.rules.models import ControlPack, PackMetadata, RuleDefinition
from reconforge.rules.operators import SUPPORTED_OPERATORS
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    validate_financial_input_policy,
)


def _read_yaml(
    path: Path,
    *,
    financial_input_policy: FinancialInputPolicy,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing control pack file: {path}")
    try:
        payload = (
            read_yaml_document(
                path,
                financial_input_policy=financial_input_policy,
            )
            or {}
        )
    except StructuredDocumentError as exc:
        raise ValueError(f"Control pack YAML is invalid ({exc.code})") from exc
    if not isinstance(payload, dict):
        raise ValueError("Control pack YAML must contain an object")
    return payload


def _validate_condition_operators(condition: dict[str, Any], rule_id: str) -> None:
    operator = str(condition.get("operator", "")).lower()
    if operator not in SUPPORTED_OPERATORS:
        raise ValueError(f"Rule {rule_id} uses unsupported operator '{operator}'")
    for child in condition.get("conditions", []) or []:
        if not isinstance(child, dict):
            raise ValueError(f"Rule {rule_id} has an invalid nested condition")
        _validate_condition_operators(child, rule_id)


def _rule_pack_digest(
    metadata: PackMetadata,
    rules: list[RuleDefinition],
    *,
    financial_input_policy: FinancialInputPolicy,
) -> str:
    payload = {
        "schema_version": 1,
        "financial_input_policy": financial_input_policy,
        "metadata": metadata.model_dump(mode="json"),
        "rules": [rule.model_dump(mode="json") for rule in rules],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_rule_pack(
    pack_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> ControlPack:
    """Load and validate a control pack under a named financial policy."""

    try:
        input_policy = validate_financial_input_policy(financial_input_policy)
    except InvalidAmountError as exc:
        raise ValueError("Invalid control-pack financial-input policy") from exc

    root = Path(pack_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Control pack not found: {root}")
    validation_context = {"financial_input_policy": input_policy}
    metadata = PackMetadata.model_validate(
        _read_yaml(
            root / "pack.yml",
            financial_input_policy=input_policy,
        ),
        context=validation_context,
    )
    rules_payload = _read_yaml(
        root / "rules.yml",
        financial_input_policy=input_policy,
    )
    raw_rules = rules_payload.get("rules", [])
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError(f"Control pack has no rules: {root}")
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ValueError("Each rule must be a YAML object")
        _validate_condition_operators(raw_rule.get("condition", {}), str(raw_rule.get("rule_id", "<unknown>")))
    rules = [RuleDefinition.model_validate(raw_rule, context=validation_context) for raw_rule in raw_rules]
    return ControlPack(
        root_path=str(root),
        metadata=metadata,
        rules=rules,
        financial_input_policy=input_policy,
        rule_pack_digest=_rule_pack_digest(
            metadata,
            rules,
            financial_input_policy=input_policy,
        ),
    )
