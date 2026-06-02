"""Column masking functions."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from reconforge.anonymizer.mapping import PREFIX_BY_FIELD, AnonymizationMap

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
    amount_noise_percent: float = 15.0,
    preserve_dates: bool = False,
    date_shift_days: int = 0,
) -> pd.DataFrame:
    """Mask sensitive fields while preserving cross-file references."""

    masked = frame.copy()
    for column in masked.columns:
        if column in PREFIX_BY_FIELD:
            masked[column] = masked[column].apply(lambda value, field=column: mapping.mask(field, value))
        elif mask_amounts and column in AMOUNT_COLUMNS:
            factor = mapping.amount_factor(amount_noise_percent)
            masked[column] = pd.to_numeric(masked[column], errors="coerce").fillna(0).mul(factor).round(2)
        elif column in DATE_COLUMNS and not preserve_dates and date_shift_days:
            parsed = pd.to_datetime(masked[column], errors="coerce")
            masked[column] = (parsed + timedelta(days=date_shift_days)).dt.strftime("%Y-%m-%d").fillna("")
    return masked
