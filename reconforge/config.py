"""Configuration loading for ReconForge ERP."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from reconforge.io.structured import StructuredDocumentError, read_yaml_document
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    validate_financial_input_policy,
)


class AgingBucket(BaseModel):
    """A named WIP aging bucket."""

    label: str
    min_days: int = Field(ge=0)
    max_days: int | None = Field(default=None, ge=0)

    @field_validator("max_days")
    @classmethod
    def validate_range(cls, value: int | None, info: Any) -> int | None:
        min_days = info.data.get("min_days")
        if value is not None and min_days is not None and value < min_days:
            raise ValueError("max_days must be greater than or equal to min_days")
        return value


class RiskScoringWeights(BaseModel):
    """Weights used by the risk scoring engine."""

    amount_mismatch: int = 25
    missing_gl_entry: int = 45
    missing_stock_movement: int = 45
    wip_over_90_days: int = 55
    direct_purchase_fit: int = 65
    missing_old_part_return: int = 55
    duplicate_reference: int = 35
    closed_work_order_without_invoice: int = 50
    cancelled_po_linked_to_movement: int = 60
    invalid_master_reference: int = 35
    invalid_financial_value: int = 60


class ReconForgeConfig(BaseModel):
    """Runtime configuration for reconciliation and reporting."""

    amount_tolerance: Decimal = Field(default=Decimal("2"))
    matching_ambiguity_policy: Literal[
        "stable-tie-break-v1",
        "unresolved-equal-cost-v1",
    ] = "stable-tie-break-v1"

    @field_validator("amount_tolerance", mode="before")
    @classmethod
    def _coerce_amount_tolerance(cls, value: object, info: ValidationInfo) -> Decimal:
        """Parse tolerance under the selected versioned input policy.

        Direct model construction retains the historical legacy-v1 policy.
        ``load_config`` supplies strict-v2 context for current application
        paths after preserving decimal-looking YAML scalars as source text.
        """
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
            raise ValueError(f"amount_tolerance must be a non-negative number: {exc}") from exc
        if parsed < Decimal("0"):
            raise ValueError("amount_tolerance must be non-negative")
        return parsed

    date_tolerance_days: int = Field(default=3, ge=0)
    aging_buckets: list[AgingBucket] = Field(
        default_factory=lambda: [
            AgingBucket(label="0-30", min_days=0, max_days=30),
            AgingBucket(label="31-60", min_days=31, max_days=60),
            AgingBucket(label="61-90", min_days=61, max_days=90),
            AgingBucket(label="90+", min_days=91, max_days=None),
        ],
    )
    required_old_part_categories: list[str] = Field(
        default_factory=lambda: ["Batteries", "Brakes", "Electrical", "Engine", "Transmission"],
    )
    account_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "stock_account": "1400",
            "spare_parts_expense": "5100",
            "work_in_progress": "1500",
            "inventory_variance": "5200",
        },
    )
    movement_type_mapping: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "issue": ["ISSUE", "CONSUME", "STOCK_ISSUE"],
            "receipt": ["RECEIPT", "GRN", "STOCK_RECEIPT"],
            "direct_fit": ["DIRECT_FIT", "PURCHASE_FIT"],
            "return": ["RETURN", "OLD_PART_RETURN"],
        },
    )
    risk_scoring_weights: RiskScoringWeights = Field(default_factory=RiskScoringWeights)
    output_currency: str = "USD"
    company_name: str = "ReconForge Demo Company"
    report_title: str = "ERP Stock, GL, WIP, and Workshop Reconciliation"


def default_config_dict() -> dict[str, Any]:
    """Return the default config as a plain dictionary."""

    return ReconForgeConfig().model_dump(mode="json")


def load_config(
    path: Path | str | None = None,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> ReconForgeConfig:
    """Load safe YAML under a named policy, falling back to exact defaults."""

    try:
        input_policy = validate_financial_input_policy(financial_input_policy)
    except InvalidAmountError as exc:
        raise ValueError("Invalid ReconForge config financial-input policy") from exc

    validation_context = {"financial_input_policy": input_policy}

    if path is None:
        return ReconForgeConfig.model_validate({}, context=validation_context)

    config_path = Path(path)
    if not config_path.exists():
        return ReconForgeConfig.model_validate({}, context=validation_context)

    try:
        raw = (
            read_yaml_document(
                config_path,
                financial_input_policy=input_policy,
            )
            or {}
        )
    except StructuredDocumentError as exc:
        raise ValueError(f"Invalid ReconForge config YAML ({exc.code})") from exc

    try:
        return ReconForgeConfig.model_validate(raw, context=validation_context)
    except ValidationError as exc:
        raise ValueError("Invalid ReconForge config values") from exc


def write_default_config(path: Path | str) -> Path:
    """Write the default configuration file to disk."""

    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(default_config_dict(), handle, sort_keys=False)
    return config_path
