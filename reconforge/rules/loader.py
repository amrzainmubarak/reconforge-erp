"""Control pack loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reconforge.rules.models import ControlPack, PackMetadata, RuleDefinition
from reconforge.rules.operators import SUPPORTED_OPERATORS


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing control pack file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Control pack YAML must contain an object: {path}")
    return payload


def _validate_condition_operators(condition: dict[str, Any], rule_id: str) -> None:
    operator = str(condition.get("operator", "")).lower()
    if operator not in SUPPORTED_OPERATORS:
        raise ValueError(f"Rule {rule_id} uses unsupported operator '{operator}'")
    for child in condition.get("conditions", []) or []:
        if not isinstance(child, dict):
            raise ValueError(f"Rule {rule_id} has an invalid nested condition")
        _validate_condition_operators(child, rule_id)


def load_rule_pack(pack_path: Path | str) -> ControlPack:
    """Load and validate a control pack directory."""

    root = Path(pack_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Control pack not found: {root}")
    metadata = PackMetadata.model_validate(_read_yaml(root / "pack.yml"))
    rules_payload = _read_yaml(root / "rules.yml")
    raw_rules = rules_payload.get("rules", [])
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError(f"Control pack has no rules: {root}")
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ValueError("Each rule must be a YAML object")
        _validate_condition_operators(raw_rule.get("condition", {}), str(raw_rule.get("rule_id", "<unknown>")))
    rules = [RuleDefinition.model_validate(raw_rule) for raw_rule in raw_rules]
    return ControlPack(root_path=str(root), metadata=metadata, rules=rules)
