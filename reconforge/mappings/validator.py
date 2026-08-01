"""Validation for export-based ERP mapping profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from reconforge.io.structured import StructuredDocumentError, read_yaml_document
from reconforge.rules.models import PackMetadata, RuleDefinition
from reconforge.rules.operators import SUPPORTED_OPERATORS
from reconforge.schemas import REQUIRED_COLUMNS, DatasetName
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

CheckStatus = Literal["PASS", "FAIL"]

REQUIRED_PACK_FILES = [
    "pack.yml",
    "mapping.yml",
    "rules.yml",
    "risk_model.yml",
    "README.md",
    "expected-exceptions.md",
    "sample-command.md",
]
YAML_FILES = {"pack.yml", "mapping.yml", "rules.yml", "risk_model.yml"}
REQUIRED_MAPPING_KEYS = {
    "profile_id",
    "source_system",
    "version",
    "export_workflow",
    "canonical_datasets",
    "field_mappings",
    "join_keys",
    "quality_checks",
}
REQUIRED_CORE_DATASETS = {"stock_moves.csv", "gl_entries.csv"}
VALID_SEVERITIES = {"info", "low", "medium", "high", "critical"}
SOURCE_DOCUMENTATION_KEYS = {"source_objects", "source_reports", "source_files"}
PATH_REFERENCE_PATTERN = re.compile(r"\b(?:examples|control-packs|config|docs)/[A-Za-z0-9_.\-/]+")


@dataclass(frozen=True)
class MappingValidationCheck:
    """One actionable mapping-profile validation check."""

    name: str
    status: CheckStatus
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


@dataclass(frozen=True)
class MappingValidationResult:
    """Validation result for one mapping profile pack."""

    pack_path: Path
    checks: list[MappingValidationCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[MappingValidationCheck]:
        return [check for check in self.checks if not check.passed]


def _add_check(checks: list[MappingValidationCheck], name: str, passed: bool, detail: str) -> None:
    checks.append(MappingValidationCheck(name=name, status="PASS" if passed else "FAIL", detail=detail))


def _read_yaml(path: Path, checks: list[MappingValidationCheck]) -> dict[str, Any] | None:
    if not path.exists():
        _add_check(checks, f"{path.name} YAML", False, f"Missing required file: {path}")
        return None
    try:
        payload = (
            read_yaml_document(
                path,
                financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            )
            or {}
        )
    except StructuredDocumentError as exc:
        _add_check(checks, f"{path.name} YAML", False, f"Malformed YAML: {exc}")
        return None
    if not isinstance(payload, dict):
        _add_check(checks, f"{path.name} YAML", False, "YAML root must be an object.")
        return None
    _add_check(checks, f"{path.name} YAML", True, "Valid YAML object.")
    return payload


def _dataset_from_filename(filename: str) -> DatasetName | None:
    value = filename.removesuffix(".csv")
    try:
        return DatasetName(value)
    except ValueError:
        return None


def _operators(condition: object) -> list[str]:
    if not isinstance(condition, dict):
        return []
    values = [str(condition.get("operator", "")).lower()]
    for child in condition.get("conditions", []) or []:
        values.extend(_operators(child))
    return values


def _check_required_files(pack_path: Path, checks: list[MappingValidationCheck]) -> None:
    for filename in REQUIRED_PACK_FILES:
        path = pack_path / filename
        if not path.exists():
            _add_check(checks, f"{filename} exists", False, f"Missing required file: {path}")
            continue
        if filename in YAML_FILES:
            _add_check(checks, f"{filename} exists", True, "Required YAML file found.")
        else:
            text = path.read_text(encoding="utf-8").strip()
            _add_check(
                checks, f"{filename} exists", bool(text), "Required documentation file is present and non-empty."
            )


def _check_mapping_payload(mapping: dict[str, Any] | None, checks: list[MappingValidationCheck]) -> None:
    if mapping is None:
        return
    missing = sorted(REQUIRED_MAPPING_KEYS - set(mapping))
    _add_check(
        checks,
        "mapping sections",
        not missing,
        "Required mapping sections found." if not missing else f"Missing mapping sections: {', '.join(missing)}",
    )
    canonical = mapping.get("canonical_datasets")
    field_mappings = mapping.get("field_mappings")
    if not isinstance(canonical, dict):
        _add_check(checks, "canonical datasets", False, "mapping.yml must define canonical_datasets as an object.")
        return
    if not isinstance(field_mappings, dict):
        _add_check(checks, "field mappings", False, "mapping.yml must define field_mappings as an object.")
        return
    missing_core = sorted(REQUIRED_CORE_DATASETS - set(canonical))
    _add_check(
        checks,
        "required source files",
        not missing_core,
        "Core source files are documented."
        if not missing_core
        else f"Missing canonical datasets: {', '.join(missing_core)}",
    )

    undocumented_sources = []
    for dataset_name, dataset_doc in canonical.items():
        if not isinstance(dataset_doc, dict) or not any(dataset_doc.get(key) for key in SOURCE_DOCUMENTATION_KEYS):
            undocumented_sources.append(str(dataset_name))
    _add_check(
        checks,
        "source documentation",
        not undocumented_sources,
        "Each canonical dataset documents source exports."
        if not undocumented_sources
        else f"Datasets missing source export documentation: {', '.join(sorted(undocumented_sources))}",
    )

    datasets_to_check = set(REQUIRED_CORE_DATASETS) | set(field_mappings)
    missing_fields: list[str] = []
    for filename in sorted(datasets_to_check):
        dataset = _dataset_from_filename(str(filename))
        if dataset is None:
            continue
        mapped_fields = field_mappings.get(filename)
        if not isinstance(mapped_fields, dict):
            missing_fields.append(f"{filename}: missing field_mappings section")
            continue
        missing_for_dataset = [field for field in REQUIRED_COLUMNS[dataset] if field not in mapped_fields]
        if missing_for_dataset:
            missing_fields.append(f"{filename}: {', '.join(missing_for_dataset)}")
    _add_check(
        checks,
        "target schema fields",
        not missing_fields,
        "Required target schema fields are documented."
        if not missing_fields
        else "Missing mapped target fields: " + " | ".join(missing_fields),
    )


def _check_rule_payload(
    pack: dict[str, Any] | None, rules: dict[str, Any] | None, checks: list[MappingValidationCheck]
) -> None:
    if pack is not None:
        try:
            PackMetadata.model_validate(pack)
            _add_check(checks, "pack metadata schema", True, "pack.yml metadata is valid.")
        except ValidationError as exc:
            _add_check(checks, "pack metadata schema", False, f"Invalid pack.yml metadata: {exc}")

    if rules is None:
        return
    raw_rules = rules.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        _add_check(checks, "rules list", False, "rules.yml must contain a non-empty rules list.")
        return
    _add_check(checks, "rules list", True, f"{len(raw_rules)} rules found.")

    ids: list[str] = []
    duplicate_ids: set[str] = set()
    invalid_severities: list[str] = []
    unsupported_operators: list[str] = []
    schema_errors: list[str] = []
    for index, raw_rule in enumerate(raw_rules, start=1):
        if not isinstance(raw_rule, dict):
            schema_errors.append(f"rule {index}: rule must be an object")
            continue
        rule_id = str(raw_rule.get("rule_id", f"rule {index}"))
        if rule_id in ids:
            duplicate_ids.add(rule_id)
        ids.append(rule_id)
        severity = str(raw_rule.get("severity", "")).lower()
        if severity not in VALID_SEVERITIES:
            invalid_severities.append(f"{rule_id}: {severity or '<missing>'}")
        for operator in _operators(raw_rule.get("condition")):
            if operator not in SUPPORTED_OPERATORS:
                unsupported_operators.append(f"{rule_id}: {operator or '<missing>'}")
        try:
            RuleDefinition.model_validate(raw_rule)
        except ValidationError as exc:
            schema_errors.append(f"{rule_id}: {exc}")

    _add_check(
        checks,
        "unique rule IDs",
        not duplicate_ids,
        "Rule IDs are unique." if not duplicate_ids else f"Duplicate rule IDs: {', '.join(sorted(duplicate_ids))}",
    )
    _add_check(
        checks,
        "rule severities",
        not invalid_severities,
        "Rule severities are valid."
        if not invalid_severities
        else f"Invalid severities: {', '.join(invalid_severities)}",
    )
    _add_check(
        checks,
        "rule operators",
        not unsupported_operators,
        "Rule operators are supported."
        if not unsupported_operators
        else f"Unsupported operators: {', '.join(unsupported_operators)}",
    )
    _add_check(
        checks,
        "rule schema",
        not schema_errors,
        "Rules conform to the rule schema."
        if not schema_errors
        else "Rule schema errors: " + " | ".join(schema_errors),
    )


def _check_sample_commands(pack_path: Path, checks: list[MappingValidationCheck]) -> None:
    sample_path = pack_path / "sample-command.md"
    if not sample_path.exists():
        return
    repo_root = _infer_repo_root(pack_path)
    if repo_root is None:
        _add_check(
            checks,
            "sample command paths",
            True,
            "Sample command path checks skipped; repository root could not be inferred safely.",
        )
        return
    text = sample_path.read_text(encoding="utf-8")
    missing_paths = []
    for match in PATH_REFERENCE_PATTERN.findall(text):
        reference = match.rstrip("`.,)")
        if reference.startswith("output/"):
            continue
        if not (repo_root / reference).exists():
            missing_paths.append(reference)
    _add_check(
        checks,
        "sample command paths",
        not missing_paths,
        "Sample command references resolve where practical."
        if not missing_paths
        else f"Referenced paths do not exist: {', '.join(sorted(set(missing_paths)))}",
    )


def _infer_repo_root(pack_path: Path) -> Path | None:
    resolved = pack_path.resolve()
    for parent in [resolved, *resolved.parents]:
        if (parent / "control-packs").is_dir() and (parent / "examples").is_dir():
            return parent
    if resolved.parent.name == "control-packs":
        candidate = resolved.parent.parent
        if (candidate / "examples").is_dir():
            return candidate
    return None


def validate_mapping_pack(pack_path: Path | str) -> MappingValidationResult:
    """Validate a local ERP mapping control pack."""

    root = Path(pack_path)
    checks: list[MappingValidationCheck] = []
    if not root.exists() or not root.is_dir():
        _add_check(checks, "pack directory", False, f"Control pack directory not found: {root}")
        return MappingValidationResult(pack_path=root, checks=checks)
    _add_check(checks, "pack directory", True, f"Control pack directory found: {root}")

    _check_required_files(root, checks)
    pack = _read_yaml(root / "pack.yml", checks)
    mapping = _read_yaml(root / "mapping.yml", checks)
    rules = _read_yaml(root / "rules.yml", checks)
    _read_yaml(root / "risk_model.yml", checks)
    _check_mapping_payload(mapping, checks)
    _check_rule_payload(pack, rules, checks)
    _check_sample_commands(root, checks)
    return MappingValidationResult(pack_path=root, checks=checks)
