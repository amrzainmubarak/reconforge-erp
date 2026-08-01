"""Pydantic models for control packs and rules."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    validate_financial_input_policy,
)

Severity = Literal["info", "low", "medium", "high", "critical"]
_NUMERIC_VALUE_OPERATORS = {
    "amount_within_tolerance",
    "greater_or_equal",
    "greater_than",
    "less_or_equal",
    "less_than",
}


class Condition(BaseModel):
    """A declarative row-level rule condition."""

    operator: str
    field: str | None = None
    value: Any | None = None
    other_field: str | None = None
    target_file: str | None = None
    target_field: str | None = None
    source_key: str | None = None
    target_key: str | None = None
    aggregate_field: str | None = None
    threshold: Decimal | None = None
    bucket_days: int | None = None
    tolerance: Decimal | None = None
    days: int | None = None
    conditions: list[Condition] = Field(default_factory=list)

    @field_validator("threshold", "tolerance", mode="before")
    @classmethod
    def parse_financial_boundary(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> Decimal | None:
        """Parse explicit financial limits under the selected pack policy."""

        if value is None:
            return None
        context = info.context if isinstance(info.context, Mapping) else {}
        input_policy = context.get(
            "financial_input_policy",
            STRICT_FINANCIAL_INPUT_POLICY,
        )
        try:
            parsed = parse_amount(
                value,
                input_policy=validate_financial_input_policy(input_policy),
            )
        except (InvalidAmountError, TypeError) as exc:
            raise ValueError(f"condition {info.field_name} must be a finite non-negative decimal") from exc
        if parsed < 0:
            raise ValueError(f"condition {info.field_name} must be a finite non-negative decimal")
        return parsed

    @model_validator(mode="after")
    def parse_numeric_comparison_value(self, info: ValidationInfo) -> Condition:
        """Validate a literal numeric comparison under the selected policy."""

        operator = self.operator.lower()
        should_parse = (
            (operator in _NUMERIC_VALUE_OPERATORS and self.other_field is None)
            or (operator == "sum_matches" and self.field is None)
            or (operator == "variance_above" and self.threshold is None)
        )
        if not should_parse:
            return self
        if self.value is None:
            raise ValueError("numeric rule condition requires a value or other_field")
        context = info.context if isinstance(info.context, Mapping) else {}
        input_policy = context.get(
            "financial_input_policy",
            STRICT_FINANCIAL_INPUT_POLICY,
        )
        try:
            parse_amount(
                self.value,
                input_policy=validate_financial_input_policy(input_policy),
            )
        except (InvalidAmountError, TypeError) as exc:
            raise ValueError("numeric rule condition value must be a finite decimal") from exc
        return self


class RuleDefinition(BaseModel):
    """A single rule inside a control pack."""

    rule_id: str
    rule_name: str
    severity: Severity
    entity_type: str
    source_file: str
    condition: Condition
    message: str
    recommended_action: str
    risk_impact: int = Field(ge=0, le=100)
    business_impact: str | None = None
    confidence: float = Field(default=0.9, ge=0, le=1)
    evidence_fields: list[str] = Field(default_factory=list)

    @field_validator("source_file")
    @classmethod
    def ensure_csv_source(cls, value: str) -> str:
        if not value.endswith(".csv"):
            raise ValueError("source_file must be a CSV filename")
        return value


class PackMetadata(BaseModel):
    """Control pack metadata."""

    pack_id: str
    name: str
    version: str
    description: str
    owner: str = "ReconForge ERP Maintainers"
    tags: list[str] = Field(default_factory=list)


class ControlPack(BaseModel):
    """Loaded control pack with metadata and rules."""

    root_path: str
    metadata: PackMetadata
    rules: list[RuleDefinition]
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY
    rule_pack_digest: str = ""
