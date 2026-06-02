"""Date utilities."""

from __future__ import annotations

from datetime import date

import pandas as pd


def parse_date_series(values: pd.Series) -> pd.Series:
    """Parse a pandas series into timezone-naive dates."""

    parsed = pd.to_datetime(values, errors="coerce")
    return parsed.dt.date


def days_between(start: date | pd.Timestamp | None, end: date | pd.Timestamp | None) -> int | None:
    """Return the absolute number of days between two dates."""

    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    start_date = start.date() if isinstance(start, pd.Timestamp) else start
    end_date = end.date() if isinstance(end, pd.Timestamp) else end
    return abs((end_date - start_date).days)


def aging_days(opened: date | pd.Timestamp | None, as_of: date) -> int:
    """Return non-negative age in days."""

    if opened is None or pd.isna(opened):
        return 0
    opened_date = opened.date() if isinstance(opened, pd.Timestamp) else opened
    return max((as_of - opened_date).days, 0)
