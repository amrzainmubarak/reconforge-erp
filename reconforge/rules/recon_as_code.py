"""Versioned, deterministic Reconciliation-as-Code contracts and tooling.

The specification is intentionally declarative. It rejects executable hooks and
preserves exact financial values as strings so loading or linting a pack cannot
silently introduce binary floating-point values or execute arbitrary code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from reconforge.application.matching_strategies import canonical_payload
from reconforge.io.structured import (
    parse_json_document,
    parse_yaml_document,
    read_json_document,
    read_yaml_document,
)
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

RECONCILIATION_AS_CODE_SCHEMA_VERSION = "1.0.0"
RECONCILIATION_AS_CODE_POLICY = "reconciliation-as-code-v1"
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_PLAIN_NON_NEGATIVE_DECIMAL = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?$")
_FORBIDDEN_EXECUTION_KEYS = frozenset(
    {
        "callable",
        "command",
        "eval",
        "exec",
        "executable",
        "module",
        "python",
        "script",
        "shell",
        "subprocess",
    }
)


class ReconciliationAsCodeError(ValueError):
    """Raised when a specification or tooling request fails closed."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


ScalarValue = str | int | bool | None
RecordValue = ScalarValue | list[ScalarValue] | dict[str, ScalarValue]


def _normalize_id(value: str, *, field_name: str) -> str:
    cleaned = value.strip().lower()
    if not _ID_PATTERN.fullmatch(cleaned):
        raise ValueError(f"{field_name} must be a lowercase slug containing letters, digits, '-' or '_'.")
    return cleaned


def _validate_semver(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not _SEMVER_PATTERN.fullmatch(cleaned):
        raise ValueError(f"{field_name} must use MAJOR.MINOR.PATCH semantic versioning.")
    return cleaned


def _validate_exact_non_negative_decimal(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not _PLAIN_NON_NEGATIVE_DECIMAL.fullmatch(cleaned):
        raise ValueError(f"{field_name} must be a non-negative plain decimal string.")
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a non-negative plain decimal string.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative finite decimal string.")
    return cleaned


def _scan_for_executable_hooks(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.casefold().replace("-", "_") in _FORBIDDEN_EXECUTION_KEYS:
                raise ValueError(f"Executable hook field is forbidden at {path}.{key}.")
            _scan_for_executable_hooks(item, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _scan_for_executable_hooks(item, path=f"{path}[{index}]")


class SourceDefinition(_ContractModel):
    """One bounded input source; acquisition remains outside this contract."""

    name: str = Field(min_length=1, max_length=100)
    format: Literal["csv", "xlsx", "json", "xml", "fixed_width", "parquet"] = "csv"
    schema_version: str = "1.0.0"
    required_columns: list[str] = Field(default_factory=list, max_length=1_000)
    identifier_column: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _normalize_id(value, field_name="source.name")

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        return _validate_semver(value, field_name="source.schema_version")

    @field_validator("required_columns")
    @classmethod
    def validate_required_columns(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("Source required_columns cannot contain blank values.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Source required_columns must be unique.")
        return cleaned


class DeclarativeRuleStep(_ContractModel):
    """Safe, data-only validation, normalization, or blocking step."""

    id: str = Field(min_length=1, max_length=100)
    kind: Literal[
        "required",
        "type",
        "regex",
        "date",
        "currency",
        "amount",
        "trim",
        "casefold",
        "replace",
        "reference_normalize",
        "expression",
    ]
    field: str = Field(default="", max_length=200)
    parameters: dict[str, RecordValue] = Field(default_factory=dict)
    on_failure: Literal["reject", "exception", "warn"] = "exception"

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _normalize_id(value, field_name="rule.id")


class MatchingStrategySpec(_ContractModel):
    """Versioned matching stage referencing a registered deterministic adapter."""

    name: str = Field(min_length=1, max_length=100)
    strategy_type: Literal[
        "exact_1to1",
        "normalized_ref",
        "fuzzy_ref",
        "amount_date_proximity",
        "value_difference",
        "one_to_many",
        "many_to_one",
        "many_to_many",
    ]
    strategy_id: Literal["indexed-composite-one-to-one", "bounded-grouped-subset-sum"] | None = None
    strategy_version: str = "1.0.0"
    mode: Literal["one-to-one", "one-to-many", "many-to-one", "many-to-many"] = "one-to-one"
    amount_tolerance: str = "0"
    date_tolerance_days: int = Field(default=0, ge=0, le=3_660)
    confidence_weight: str = "1"
    exact_fields: list[str] = Field(default_factory=list, max_length=100)
    reference_field: str = Field(default="reference", min_length=1, max_length=200)
    partition_field: str = Field(default="partition", min_length=1, max_length=200)
    netting_mode: Literal["gross", "net"] = "gross"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        slug = re.sub(r"\s+", "-", value.strip().lower())
        return _normalize_id(slug, field_name="matching_strategies.name")

    @field_validator("strategy_version")
    @classmethod
    def validate_strategy_version(cls, value: str) -> str:
        return _validate_semver(value, field_name="matching_strategies.strategy_version")

    @field_validator("amount_tolerance", "confidence_weight")
    @classmethod
    def validate_decimal_text(cls, value: str, info: ValidationInfo) -> str:
        return _validate_exact_non_negative_decimal(value, field_name=f"matching_strategies.{info.field_name}")

    @model_validator(mode="after")
    def validate_adapter_compatibility(self) -> MatchingStrategySpec:
        grouped = self.strategy_type in {"one_to_many", "many_to_one", "many_to_many"}
        effective_id = self.strategy_id or ("bounded-grouped-subset-sum" if grouped else "indexed-composite-one-to-one")
        expected_mode = self.strategy_type.replace("_", "-") if grouped else "one-to-one"
        if self.mode != expected_mode:
            raise ValueError("Matching strategy type and mode are incompatible.")
        if grouped and effective_id != "bounded-grouped-subset-sum":
            raise ValueError("Grouped matching modes require bounded-grouped-subset-sum.")
        if not grouped and effective_id != "indexed-composite-one-to-one":
            raise ValueError("One-to-one matching modes require indexed-composite-one-to-one.")
        return self

    @property
    def effective_strategy_id(self) -> str:
        if self.strategy_id is not None:
            return self.strategy_id
        if self.strategy_type in {"one_to_many", "many_to_one", "many_to_many"}:
            return "bounded-grouped-subset-sum"
        return "indexed-composite-one-to-one"


class TolerancePolicy(_ContractModel):
    amount: str = "0"
    date_days: int = Field(default=0, ge=0, le=3_660)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        return _validate_exact_non_negative_decimal(value, field_name="tolerances.amount")


class CurrencyPolicy(_ContractModel):
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    strict: bool = True
    require_same_currency: bool = True
    target_currency: str = Field(default="", max_length=3)
    fx_source: str = Field(default="", max_length=200)

    @field_validator("base_currency", "target_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned and (len(cleaned) != 3 or not cleaned.isalpha()):
            raise ValueError("Currency codes must be three alphabetic characters.")
        return cleaned


class RiskPolicy(_ContractModel):
    high_risk_threshold: int = Field(default=70, ge=0, le=100)
    unresolved_ambiguity: Literal["exception", "reject"] = "exception"


class WorkflowPolicy(_ContractModel):
    requires_human_approval: bool = True
    autonomous_financial_approval: Literal[False] = False
    maker_checker: bool = True


class EvidenceRequirementSpec(_ContractModel):
    id: str = Field(min_length=1, max_length=100)
    node_types: list[str] = Field(min_length=1, max_length=100)
    minimum_count: int = Field(default=1, ge=1, le=100_000)
    required_for_status: Literal["matched", "ambiguous", "unmatched", "all"] = "all"

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _normalize_id(value, field_name="evidence_requirements.id")


class ExpectedResult(_ContractModel):
    matched_count: int = Field(ge=0)
    unmatched_left_count: int = Field(ge=0)
    unmatched_right_count: int = Field(ge=0)
    ambiguous_count: int = Field(default=0, ge=0)
    decision_digest: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")


class ReconciliationTestCase(_ContractModel):
    id: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1_000)
    strategy: str = Field(min_length=1, max_length=100)
    left_records: list[dict[str, RecordValue]] = Field(default_factory=list, max_length=10_000)
    right_records: list[dict[str, RecordValue]] = Field(default_factory=list, max_length=10_000)
    expected_result: str = Field(min_length=1, max_length=100)

    @field_validator("id", "strategy", "expected_result")
    @classmethod
    def validate_reference_ids(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_id(value, field_name=f"test_cases.{info.field_name}")


class ReconciliationAsCodeSpec(_ContractModel):
    """Root versioned reconciliation definition and embedded synthetic tests."""

    schema_version: str = RECONCILIATION_AS_CODE_SCHEMA_VERSION
    reconciliation_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5_000)
    sources: list[SourceDefinition] = Field(default_factory=list, max_length=100)
    canonical_mapping: dict[str, str] = Field(default_factory=dict, max_length=5_000)
    validation_rules: list[DeclarativeRuleStep] = Field(default_factory=list, max_length=1_000)
    normalization: list[DeclarativeRuleStep] = Field(
        default_factory=list,
        validation_alias=AliasChoices("normalization", "normalization_rules"),
    )
    blocking: list[DeclarativeRuleStep] = Field(default_factory=list, max_length=1_000)
    matching_strategies: list[MatchingStrategySpec] = Field(default_factory=list, max_length=100)
    tolerances: TolerancePolicy = Field(default_factory=TolerancePolicy)
    currency_policy: CurrencyPolicy = Field(default_factory=CurrencyPolicy)
    risk_policy: RiskPolicy = Field(default_factory=RiskPolicy)
    workflow: WorkflowPolicy = Field(default_factory=WorkflowPolicy)
    evidence_requirements: list[EvidenceRequirementSpec] = Field(default_factory=list, max_length=1_000)
    test_cases: list[ReconciliationTestCase] = Field(default_factory=list, max_length=1_000)
    expected_results: dict[str, ExpectedResult] = Field(default_factory=dict, max_length=1_000)

    @model_validator(mode="before")
    @classmethod
    def reject_executable_hooks(cls, value: object) -> object:
        _scan_for_executable_hooks(value)
        return value

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        cleaned = _validate_semver(value, field_name="schema_version")
        if cleaned.split(".", maxsplit=1)[0] != "1":
            raise ValueError("Only Reconciliation-as-Code schema major version 1 is supported.")
        return cleaned

    @field_validator("reconciliation_id")
    @classmethod
    def validate_rec_id(cls, value: str) -> str:
        return _normalize_id(value, field_name="reconciliation_id")

    @field_validator("canonical_mapping")
    @classmethod
    def validate_canonical_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned = {source.strip(): target.strip() for source, target in value.items()}
        if any(not source or not target for source, target in cleaned.items()):
            raise ValueError("canonical_mapping keys and values cannot be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_cross_references(self) -> ReconciliationAsCodeSpec:
        self._require_unique((source.name for source in self.sources), "source names")
        self._require_unique((strategy.name for strategy in self.matching_strategies), "matching strategy names")
        self._require_unique((rule.id for rule in self.validation_rules), "validation rule IDs")
        self._require_unique((rule.id for rule in self.normalization), "normalization rule IDs")
        self._require_unique((rule.id for rule in self.blocking), "blocking rule IDs")
        self._require_unique((requirement.id for requirement in self.evidence_requirements), "evidence requirement IDs")
        self._require_unique((case.id for case in self.test_cases), "test case IDs")

        strategy_names = {strategy.name for strategy in self.matching_strategies}
        expected_result_ids = {
            _normalize_id(result_id, field_name="expected_results key") for result_id in self.expected_results
        }
        if expected_result_ids != set(self.expected_results):
            raise ValueError("expected_results keys must already be canonical lowercase IDs.")
        for case in self.test_cases:
            if case.strategy not in strategy_names:
                raise ValueError(f"Test case '{case.id}' references an unknown matching strategy.")
            if case.expected_result not in expected_result_ids:
                raise ValueError(f"Test case '{case.id}' references an unknown expected result.")
        return self

    @staticmethod
    def _require_unique(values: Iterable[str], label: str) -> None:
        materialized = list(values)
        if len(materialized) != len(set(materialized)):
            raise ValueError(f"Reconciliation-as-Code {label} must be unique.")

    @property
    def normalization_rules(self) -> list[DeclarativeRuleStep]:
        """Backward-compatible reader for the pre-v1 field name."""

        return self.normalization

    @classmethod
    def from_yaml(cls, yaml_content: str) -> ReconciliationAsCodeSpec:
        """Parse one bounded safe YAML specification."""

        parsed = parse_yaml_document(
            yaml_content,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        if not isinstance(parsed, dict):
            raise ReconciliationAsCodeError("Invalid Reconciliation-as-Code YAML: root must be a mapping object.")
        return cls.model_validate(parsed)

    @classmethod
    def from_json(cls, json_content: str) -> ReconciliationAsCodeSpec:
        """Parse bounded JSON while preserving exact fractional lexemes."""

        parsed = parse_json_document(json_content, preserve_float_lexemes=True)
        if not isinstance(parsed, dict):
            raise ReconciliationAsCodeError("Invalid Reconciliation-as-Code JSON: root must be a mapping object.")
        return cls.model_validate(parsed)

    @classmethod
    def from_file(cls, path: Path | str) -> ReconciliationAsCodeSpec:
        """Load one regular bounded YAML or JSON file using safe ingress policy."""

        source = Path(path)
        suffix = source.suffix.casefold()
        if suffix in {".yaml", ".yml"}:
            parsed = read_yaml_document(source, financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY)
        elif suffix == ".json":
            parsed = read_json_document(source, preserve_float_lexemes=True)
        else:
            raise ReconciliationAsCodeError("Reconciliation-as-Code input must be YAML or JSON.")
        if not isinstance(parsed, dict):
            raise ReconciliationAsCodeError("Reconciliation-as-Code root must be a mapping object.")
        return cls.model_validate(parsed)

    def canonical_document(self) -> dict[str, object]:
        """Return the stable JSON-ready representation used by manifests and diffs."""

        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        canonical = canonical_payload(payload)
        if not isinstance(canonical, dict):
            raise ReconciliationAsCodeError("Canonical Reconciliation-as-Code document is invalid.")
        return canonical

    def content_digest(self) -> str:
        """Return SHA-256 over canonical UTF-8 JSON, independent of YAML formatting."""

        encoded = json.dumps(
            self.canonical_document(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def manifest(self) -> dict[str, object]:
        """Return a deterministic, non-signature manifest for review and replay."""

        return {
            "policy": RECONCILIATION_AS_CODE_POLICY,
            "schema_version": self.schema_version,
            "reconciliation_id": self.reconciliation_id,
            "content_sha256": self.content_digest(),
            "source_count": len(self.sources),
            "matching_strategy_count": len(self.matching_strategies),
            "test_case_count": len(self.test_cases),
            "requires_human_approval": self.workflow.requires_human_approval,
        }

    def lint(self) -> list[dict[str, str]]:
        """Return stable, evidence-friendly lint findings without executing rules."""

        findings: list[dict[str, str]] = []

        def add(severity: Literal["error", "warning", "info"], code: str, path: str, message: str) -> None:
            findings.append({"severity": severity, "code": code, "path": path, "message": message})

        if len(self.sources) < 2:
            add("error", "insufficient_sources", "$.sources", "A reconciliation requires at least two sources.")
        if not self.canonical_mapping:
            add("error", "canonical_mapping_missing", "$.canonical_mapping", "Canonical mapping cannot be empty.")
        if not self.matching_strategies:
            add("error", "matching_strategy_missing", "$.matching_strategies", "At least one strategy is required.")
        for index, source in enumerate(self.sources):
            if source.required_columns and source.identifier_column not in source.required_columns:
                add(
                    "warning",
                    "identifier_not_required",
                    f"$.sources[{index}].identifier_column",
                    "The identifier column is not listed in required_columns.",
                )
        for index, strategy in enumerate(self.matching_strategies):
            if strategy.strategy_type == "fuzzy_ref":
                add(
                    "error",
                    "suggestion_only_strategy",
                    f"$.matching_strategies[{index}].strategy_type",
                    "fuzzy_ref is suggestion-only and has no autonomous financial decision adapter.",
                )
        if not self.test_cases:
            add("warning", "test_cases_missing", "$.test_cases", "No embedded synthetic golden test cases are defined.")
        used_results = {case.expected_result for case in self.test_cases}
        for result_id in sorted(set(self.expected_results) - used_results):
            add(
                "warning",
                "unused_expected_result",
                f"$.expected_results.{result_id}",
                "Expected result is not referenced by a test case.",
            )
        if not self.evidence_requirements:
            add(
                "warning",
                "evidence_requirements_missing",
                "$.evidence_requirements",
                "No explicit evidence requirements are defined.",
            )
        return sorted(findings, key=lambda finding: (finding["severity"], finding["code"], finding["path"]))

    def simulation_plan(self) -> dict[str, object]:
        """Build a deterministic no-side-effect execution plan for operator review."""

        return {
            "policy": RECONCILIATION_AS_CODE_POLICY,
            "mode": "dry-run",
            "reconciliation_id": self.reconciliation_id,
            "content_sha256": self.content_digest(),
            "sources": [source.name for source in self.sources],
            "steps": {
                "validation": [rule.id for rule in self.validation_rules],
                "normalization": [rule.id for rule in self.normalization],
                "blocking": [rule.id for rule in self.blocking],
                "matching": [
                    {
                        "name": strategy.name,
                        "strategy_id": strategy.effective_strategy_id,
                        "strategy_version": strategy.strategy_version,
                        "mode": strategy.mode,
                    }
                    for strategy in self.matching_strategies
                ],
            },
            "test_cases": [case.id for case in self.test_cases],
            "requires_human_approval": self.workflow.requires_human_approval,
            "side_effects": "none",
        }

    def run_embedded_tests(self) -> dict[str, object]:
        """Execute embedded synthetic fixtures through registered matching adapters.

        This bounded runner validates the matching stage only. Validation and
        normalization steps are linted declarative contracts until their safe
        runtime adapters are explicitly registered in a later schema version.
        """

        strategy_by_name = {strategy.name: strategy for strategy in self.matching_strategies}
        results: list[dict[str, object]] = []
        for case in self.test_cases:
            strategy = strategy_by_name[case.strategy]
            actual = self._execute_matching_case(case, strategy)
            expected = self.expected_results[case.expected_result].model_dump(mode="json")
            mismatches: list[dict[str, object]] = []
            for field in (
                "matched_count",
                "unmatched_left_count",
                "unmatched_right_count",
                "ambiguous_count",
            ):
                if actual[field] != expected[field]:
                    mismatches.append(
                        {
                            "field": field,
                            "expected": expected[field],
                            "actual": actual[field],
                        }
                    )
            expected_digest = str(expected["decision_digest"])
            if expected_digest and actual["decision_digest"] != expected_digest:
                mismatches.append(
                    {
                        "field": "decision_digest",
                        "expected": expected_digest,
                        "actual": actual["decision_digest"],
                    }
                )
            results.append(
                {
                    "test_case_id": case.id,
                    "strategy": strategy.name,
                    "strategy_id": strategy.effective_strategy_id,
                    "passed": not mismatches,
                    "expected_result": case.expected_result,
                    "actual": actual,
                    "mismatches": mismatches,
                }
            )
        return {
            "policy": RECONCILIATION_AS_CODE_POLICY,
            "execution_scope": "matching-adapter-only-v1",
            "reconciliation_id": self.reconciliation_id,
            "content_sha256": self.content_digest(),
            "test_count": len(results),
            "passed_count": sum(1 for result in results if result["passed"]),
            "failed_count": sum(1 for result in results if not result["passed"]),
            "all_passed": bool(results) and all(bool(result["passed"]) for result in results),
            "results": results,
        }

    @staticmethod
    def _execute_matching_case(
        case: ReconciliationTestCase,
        strategy: MatchingStrategySpec,
    ) -> dict[str, object]:
        from reconforge.application.matching_strategies import MatchingStrategyRequest

        request = MatchingStrategyRequest(
            left_records=tuple(dict(record) for record in case.left_records),
            right_records=tuple(dict(record) for record in case.right_records),
            exact_fields=",".join(strategy.exact_fields),
            amount_tolerance=strategy.amount_tolerance,
            date_window_days=strategy.date_tolerance_days,
            mode=strategy.mode,
            reference_field=strategy.reference_field,
            partition_field=strategy.partition_field,
            netting_mode=strategy.netting_mode,
        )
        if strategy.effective_strategy_id == "bounded-grouped-subset-sum":
            from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy

            output = GroupedSubsetSumStrategy().execute(request)
        else:
            from tempfile import TemporaryDirectory

            from reconforge.db import connect, run_migrations
            from reconforge.infrastructure.indexed_matching_strategy import IndexedOneToOneStrategy
            from reconforge.platform.matching import MatchingService

            with TemporaryDirectory(prefix="reconforge-rac-") as temp_dir:
                db_path = Path(temp_dir) / "simulation.db"
                run_migrations(db_path)
                connection = connect(db_path, require_exists=True)
                try:
                    output = IndexedOneToOneStrategy(MatchingService(connection)).execute(request)
                finally:
                    connection.close()

        payloads = [dict(result) for result in output.results]
        if strategy.effective_strategy_id == "bounded-grouped-subset-sum":
            decision = payloads[0] if payloads else {}
            status = str(decision.get("status", ""))
            raw_left_ids = decision.get("left_record_ids", ())
            raw_right_ids = decision.get("right_record_ids", ())
            selected_left = (
                {str(value) for value in raw_left_ids}
                if status == "matched" and isinstance(raw_left_ids, list | tuple)
                else set()
            )
            selected_right = (
                {str(value) for value in raw_right_ids}
                if status == "matched" and isinstance(raw_right_ids, list | tuple)
                else set()
            )
            ambiguous_count = 1 if status == "ambiguous" else 0
            unmatched_left_count = 0 if ambiguous_count else len(case.left_records) - len(selected_left)
            unmatched_right_count = 0 if ambiguous_count else len(case.right_records) - len(selected_right)
            matched_count = 1 if status == "matched" else 0
        else:
            matched_count = sum(1 for item in payloads if str(item.get("status", "")).casefold() == "matched")
            ambiguous_count = sum(1 for item in payloads if str(item.get("status", "")).casefold() == "ambiguous")
            unmatched_left_count = sum(
                1 for item in payloads if str(item.get("status", "")).casefold() == "unmatched" and "left_id" in item
            )
            unmatched_right_count = sum(
                1
                for item in payloads
                if str(item.get("status", "")).casefold() == "unmatched"
                and "right_id" in item
                and "left_id" not in item
            )
        return {
            "matched_count": matched_count,
            "unmatched_left_count": unmatched_left_count,
            "unmatched_right_count": unmatched_right_count,
            "ambiguous_count": ambiguous_count,
            "manifest_digest": output.manifest_digest,
            "input_digest": output.input_digest,
            "decision_digest": output.decision_digest,
            "explanation_schema": output.explanation_schema,
        }

    def diff(self, other: ReconciliationAsCodeSpec) -> list[dict[str, object]]:
        """Return a deterministic structural diff between two validated specifications."""

        changes: list[dict[str, object]] = []

        def walk(left: object, right: object, path: str) -> None:
            if isinstance(left, dict) and isinstance(right, dict):
                for key in sorted(set(left) | set(right)):
                    child_path = f"{path}.{key}"
                    if key not in left:
                        changes.append({"operation": "add", "path": child_path, "after": right[key]})
                    elif key not in right:
                        changes.append({"operation": "remove", "path": child_path, "before": left[key]})
                    else:
                        walk(left[key], right[key], child_path)
                return
            if isinstance(left, list) and isinstance(right, list):
                for index in range(max(len(left), len(right))):
                    child_path = f"{path}[{index}]"
                    if index >= len(left):
                        changes.append({"operation": "add", "path": child_path, "after": right[index]})
                    elif index >= len(right):
                        changes.append({"operation": "remove", "path": child_path, "before": left[index]})
                    else:
                        walk(left[index], right[index], child_path)
                return
            if left != right:
                changes.append({"operation": "replace", "path": path, "before": left, "after": right})

        walk(self.canonical_document(), other.canonical_document(), "$")
        return changes

    def to_yaml(self) -> str:
        """Serialize to stable, safe YAML using the canonical v1 field names."""

        return yaml.safe_dump(
            self.canonical_document(),
            allow_unicode=True,
            sort_keys=False,
        )

    def to_json(self) -> str:
        """Serialize to stable UTF-8 JSON text."""

        return json.dumps(self.canonical_document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def write_file(self, path: Path | str, *, overwrite: bool = False) -> Path:
        """Atomically publish one validated canonical YAML or JSON document."""

        target = Path(path)
        if target.suffix.casefold() not in {".yaml", ".yml", ".json"}:
            raise ReconciliationAsCodeError("Reconciliation-as-Code output must be YAML or JSON.")
        if target.parent.is_symlink():
            raise ReconciliationAsCodeError("Reconciliation-as-Code output parent cannot be a symlink.")
        parent = target.parent.resolve()
        if not parent.exists() or not parent.is_dir():
            raise ReconciliationAsCodeError("Reconciliation-as-Code output parent must be a regular directory.")
        if target.exists() and (target.is_symlink() or not target.is_file()):
            raise ReconciliationAsCodeError("Reconciliation-as-Code output must be a regular file.")
        if target.exists() and not overwrite:
            raise ReconciliationAsCodeError("Reconciliation-as-Code output already exists; use explicit overwrite.")

        content = self.to_json() if target.suffix.casefold() == ".json" else self.to_yaml()
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=parent,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ReconciliationAsCodeError("Unable to publish Reconciliation-as-Code output atomically.") from exc
        return target


__all__ = [
    "CurrencyPolicy",
    "DeclarativeRuleStep",
    "EvidenceRequirementSpec",
    "ExpectedResult",
    "MatchingStrategySpec",
    "RECONCILIATION_AS_CODE_POLICY",
    "RECONCILIATION_AS_CODE_SCHEMA_VERSION",
    "ReconciliationAsCodeError",
    "ReconciliationAsCodeSpec",
    "ReconciliationTestCase",
    "RiskPolicy",
    "SourceDefinition",
    "TolerancePolicy",
    "WorkflowPolicy",
]
