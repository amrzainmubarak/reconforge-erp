"""Reconciliation-as-Code Declarative Specification Schema & Validator.

Enables versioned, deterministic YAML/JSON definitions for reconciliation pipelines,
data quality rules, matching tolerances, risk policies, and evidence requirements.
"""

from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from reconforge.io.structured import parse_yaml_document
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY


class SourceDefinition(BaseModel):
    """Definition for a single source dataset."""

    name: str
    format: Literal["csv", "xlsx", "json", "parquet"] = "csv"
    required_columns: list[str] = Field(default_factory=list)
    identifier_column: str


class MatchingStrategySpec(BaseModel):
    """Declarative specification for a matching strategy stage."""

    name: str
    strategy_type: Literal["exact_1to1", "normalized_ref", "fuzzy_ref", "amount_date_proximity", "value_difference"]
    amount_tolerance: str = "0.0"
    date_tolerance_days: int = 0
    confidence_weight: str = "1.0"


class ReconciliationAsCodeSpec(BaseModel):
    """Root Reconciliation-as-Code specification model."""

    schema_version: str = "1.0.0"
    reconciliation_id: str
    title: str
    description: str = ""
    sources: list[SourceDefinition] = Field(default_factory=list)
    canonical_mapping: dict[str, str] = Field(default_factory=dict)
    validation_rules: list[dict[str, Any]] = Field(default_factory=list)
    normalization_rules: list[dict[str, Any]] = Field(default_factory=list)
    matching_strategies: list[MatchingStrategySpec] = Field(default_factory=list)
    currency_policy: dict[str, Any] = Field(default_factory=lambda: {"base_currency": "USD", "strict": True})
    risk_policy: dict[str, Any] = Field(default_factory=lambda: {"high_risk_threshold": 70})

    @field_validator("reconciliation_id")
    @classmethod
    def validate_rec_id(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("reconciliation_id cannot be blank.")
        return cleaned

    @classmethod
    def from_yaml(cls, yaml_content: str) -> ReconciliationAsCodeSpec:
        """Parse and validate one bounded safe YAML specification."""

        parsed = parse_yaml_document(
            yaml_content,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        if not isinstance(parsed, dict):
            raise ValueError("Invalid Reconciliation-as-Code YAML: root must be a mapping object.")
        return cls.model_validate(parsed)

    def to_yaml(self) -> str:
        """Serialize specification to clean YAML string."""

        raw_dict = self.model_dump(mode="json")
        return yaml.safe_dump(raw_dict, sort_keys=False)
