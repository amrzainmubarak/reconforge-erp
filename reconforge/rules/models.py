"""Pydantic models for control packs and rules."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["info", "low", "medium", "high", "critical"]


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
    threshold: float | None = None
    bucket_days: int | None = None
    tolerance: float | None = None
    days: int | None = None
    conditions: list[Condition] = Field(default_factory=list)


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
