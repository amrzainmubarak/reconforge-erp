"""Stable anonymization maps."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, localcontext
from random import Random

from reconforge.io.writers import canonical_decimal_text
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
)

AmountNoiseInput = Decimal | str | int
LegacyAmountNoiseInput = AmountNoiseInput | float
AMOUNT_NOISE_ALGORITHM_VERSION = "exact-global-decimal-noise-v1"
AMOUNT_FACTOR_SCALE = 4
_FACTOR_SCALE_UNITS = 10**AMOUNT_FACTOR_SCALE

PREFIX_BY_FIELD = {
    "customer_code": "CUST-ANON",
    "customer_name": "Customer",
    "supplier_code": "SUP-ANON",
    "supplier_name": "Supplier",
    "created_by": "USER",
    "received_by": "USER",
    "responsible_engineer": "Engineer",
    "equipment_serial": "EQ-ANON",
    "invoice_number": "INV-ANON",
    "work_order": "WO-ANON",
    "linked_work_order": "WO-ANON",
    "source_document": "DOC-ANON",
    "reference": "DOC-ANON",
    "journal": "JRN-ANON",
    "po_number": "PO-ANON",
    "return_id": "RET-ANON",
}

GROUP_BY_FIELD = {
    "linked_work_order": "work_order",
    "work_order": "work_order",
    "source_document": "document",
    "reference": "document",
    "journal": "journal",
    "po_number": "document",
    "invoice_number": "invoice",
    "return_id": "return",
    "customer_code": "customer_code",
    "customer_name": "customer_name",
    "supplier_code": "supplier_code",
    "supplier_name": "supplier_name",
    "created_by": "user",
    "received_by": "user",
    "responsible_engineer": "engineer",
    "equipment_serial": "equipment",
}


def parse_amount_noise_percent(
    value: LegacyAmountNoiseInput,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> Decimal:
    """Parse a bounded exact percentage used only for deterministic masking."""

    try:
        parsed = parse_amount(value, input_policy=input_policy)
    except (InvalidAmountError, TypeError) as exc:
        raise ValueError(f"amount_noise_percent must be a finite plain-decimal value: {exc}") from exc
    if parsed < 0 or parsed > 100:
        raise ValueError("amount_noise_percent must be between 0 and 100")
    return parsed


def _maximum_factor_delta_steps(percent: Decimal) -> int:
    with localcontext() as context:
        context.prec = max(28, len(percent.as_tuple().digits) + 4)
        scaled = percent * Decimal("100")
    return int(scaled.to_integral_value(rounding=ROUND_FLOOR))


def _factor_from_scaled_integer(value: int) -> Decimal:
    digits = tuple(int(character) for character in str(value)) if value else (0,)
    return Decimal((0, digits, -AMOUNT_FACTOR_SCALE))


@dataclass
class AnonymizationMap:
    """Deterministic mapping store preserving referential integrity."""

    seed: int = 42
    counters: dict[str, int] = field(default_factory=dict)
    values: dict[tuple[str, str], str] = field(default_factory=dict)
    amount_factors: dict[tuple[str, str, str], Decimal] = field(default_factory=dict)
    _random: Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Deterministic masking noise only; not used for secrets or cryptography.
        self._random = Random(self.seed)  # nosec B311

    def mask(self, field: str, value: object) -> str:
        text = str(value).strip()
        if text == "" or text.lower() in {"nan", "nat", "none"}:
            return ""
        group = GROUP_BY_FIELD.get(field, field)
        key = (group, text)
        if key in self.values:
            return self.values[key]
        self.counters[group] = self.counters.get(group, 0) + 1
        prefix = PREFIX_BY_FIELD.get(field, group.upper())
        if prefix in {"Customer", "Supplier", "Engineer"}:
            masked = f"{prefix} {self.counters[group]:04d}"
        else:
            masked = f"{prefix}-{self.counters[group]:04d}"
        self.values[key] = masked
        return masked

    def amount_factor(
        self,
        amount_noise_percent: LegacyAmountNoiseInput = Decimal("15"),
        *,
        scope: str = "all-amount-columns",
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    ) -> Decimal:
        """Return one exact, deterministic factor for a named masking scope."""

        percent = parse_amount_noise_percent(
            amount_noise_percent,
            input_policy=financial_input_policy,
        )
        clean_scope = str(scope).strip()
        if not clean_scope:
            raise ValueError("amount masking factor scope cannot be empty")
        policy_key = canonical_decimal_text(percent)
        key = (clean_scope, policy_key, financial_input_policy)
        existing = self.amount_factors.get(key)
        if existing is not None:
            return existing
        maximum_delta = _maximum_factor_delta_steps(percent)
        delta = self._random.randint(-maximum_delta, maximum_delta) if maximum_delta else 0  # nosec B311
        factor = _factor_from_scaled_integer(_FACTOR_SCALE_UNITS + delta)
        self.amount_factors[key] = factor
        return factor
