"""Column masking functions."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

import pandas as pd

from reconforge.anonymizer.mapping import (
    PREFIX_BY_FIELD,
    AnonymizationMap,
    LegacyAmountNoiseInput,
)
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
)

AMOUNT_COLUMNS = {
    "amount",
    "debit",
    "credit",
    "total_cost",
    "unit_cost",
    "estimated_cost",
    "actual_cost",
    "unit_price",
    "total_price",
    "standard_cost",
    "invoice_amount",
}

DATE_COLUMNS = {"date", "opened_date", "closed_date", "po_date", "return_date", "invoice_date"}


def mask_frame(
    frame: pd.DataFrame,
    mapping: AnonymizationMap,
    *,
    mask_amounts: bool = False,
    amount_noise_percent: LegacyAmountNoiseInput = Decimal("15"),
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    preserve_dates: bool = False,
    date_shift_days: int = 0,
) -> pd.DataFrame:
    """Mask sensitive fields while preserving cross-file references."""

    masked = frame.copy()
    for column in masked.columns:
        if column in PREFIX_BY_FIELD:
            masked[column] = masked[column].apply(lambda value, field=column: mapping.mask(field, value))
        elif mask_amounts and column in AMOUNT_COLUMNS:
            factor = mapping.amount_factor(
                amount_noise_percent,
                scope="all-amount-columns",
                financial_input_policy=financial_input_policy,
            )
            masked[column] = [
                _mask_amount(
                    column_value,
                    factor=factor,
                    financial_input_policy=financial_input_policy,
                )
                for column_value in masked[column].tolist()
            ]
        elif column in DATE_COLUMNS and not preserve_dates and date_shift_days:
            parsed = pd.to_datetime(masked[column], errors="coerce")
            masked[column] = (parsed + timedelta(days=date_shift_days)).dt.strftime("%Y-%m-%d").fillna("")
    return masked


def _mask_amount(
    value: object,
    *,
    factor: Decimal,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> object:
    """Mask a financial value exactly while retaining its explicit source scale."""

    try:
        parsed = parse_amount(value, input_policy=financial_input_policy)
        with localcontext() as context:
            context.prec = max(28, len(parsed.as_tuple().digits) + len(factor.as_tuple().digits) + 2)
            masked = parsed * factor
        source_exponent = int(parsed.as_tuple().exponent)
        quantum = Decimal("1").scaleb(source_exponent)
        integer_digits = max(1, masked.adjusted() + 1) if masked else 1
        with localcontext() as context:
            context.prec = max(28, len(masked.as_tuple().digits) + 2, integer_digits - source_exponent + 2)
            return masked.quantize(quantum, rounding=ROUND_HALF_UP)
    except (InvalidAmountError, InvalidOperation, TypeError, ValueError):
        return value
