"""Pure aging aggregation that preserves each currency's minor-unit meaning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

AGING_BUCKETS = ("Current", "1-30", "31-60", "61-90", "90+")


class AgingCurrencyError(ValueError):
    """Aging cannot safely aggregate the supplied open items."""


def build_aging_report(
    as_of_date: str, items: Sequence[Mapping[str, object]], *, grouped: bool = False,
) -> dict[str, Any]:
    """Aggregate already-authorized items without selecting a base currency."""

    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        currency = item.get("currency_code")
        bucket = item.get("bucket")
        amount = item.get("outstanding_minor")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or not currency.isupper():
            raise AgingCurrencyError("Aging item currency is invalid.")
        if not isinstance(bucket, str) or bucket not in AGING_BUCKETS:
            raise AgingCurrencyError("Aging item bucket is invalid.")
        if type(amount) is not int or amount <= 0:
            raise AgingCurrencyError("Aging item outstanding amount must be positive integer minor units.")
        group = groups.setdefault(currency, {
            "currency_code": currency, "items": [],
            "bucket_totals_minor": dict.fromkeys(AGING_BUCKETS, 0), "total_outstanding_minor": 0,
        })
        group["items"].append(dict(item))
        group["bucket_totals_minor"][bucket] += amount
        group["total_outstanding_minor"] += amount
    ordered = [groups[currency] for currency in sorted(groups)]
    if grouped:
        return {"schema_version": 1, "as_of_date": as_of_date, "currency_groups": ordered}
    if len(ordered) > 1:
        raise AgingCurrencyError("Aging totals require a single currency; use the report grouped by currency.")
    group = ordered[0] if ordered else {
        "currency_code": None, "items": [],
        "bucket_totals_minor": dict.fromkeys(AGING_BUCKETS, 0), "total_outstanding_minor": 0,
    }
    return {"as_of_date": as_of_date, **group}
