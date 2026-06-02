"""WIP aging report generation."""

from __future__ import annotations

from datetime import date

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.risk import assess_risk
from reconforge.utils.dates import aging_days


def bucket_for_age(days: int, config: ReconForgeConfig) -> str:
    """Return the configured aging bucket label for an age."""

    for bucket in config.aging_buckets:
        if days >= bucket.min_days and (bucket.max_days is None or days <= bucket.max_days):
            return bucket.label
    return f"{days}+"


def generate_wip_aging(work_orders: pd.DataFrame, config: ReconForgeConfig, as_of: date | None = None) -> pd.DataFrame:
    """Generate WIP aging grouped by work order and operational owner."""

    report_date = as_of or date.today()
    open_statuses = {"open", "in progress", "waiting parts", "pending invoice"}
    frame = work_orders.copy()
    frame["status_clean"] = frame["status"].astype(str).str.strip().str.lower()
    wip = frame[frame["status_clean"].isin(open_statuses)].copy()
    wip["aging_days"] = wip["opened_date"].apply(lambda value: aging_days(value, report_date))
    wip["aging_bucket"] = wip["aging_days"].apply(lambda value: bucket_for_age(int(value), config))
    scores: list[int] = []
    levels: list[str] = []
    for _, row in wip.iterrows():
        exception_type = "wip_over_90_days" if int(row["aging_days"]) > 90 else "wip_open"
        assessment = assess_risk(
            exception_type,
            config,
            amount=float(row.get("actual_cost", 0.0) or 0.0),
            aging_days=int(row["aging_days"]),
        )
        scores.append(assessment.score)
        levels.append(assessment.level)
    wip["risk_score"] = scores
    wip["risk_level"] = levels
    columns = [
        "work_order",
        "customer_code",
        "customer_name",
        "equipment_serial",
        "responsible_engineer",
        "workshop",
        "status",
        "opened_date",
        "actual_cost",
        "aging_days",
        "aging_bucket",
        "risk_score",
        "risk_level",
    ]
    return wip[columns].sort_values(["aging_days", "actual_cost"], ascending=[False, False]).reset_index(drop=True)


def aging_summary(wip_aging: pd.DataFrame) -> pd.DataFrame:
    """Summarize WIP count and value by aging bucket."""

    if wip_aging.empty:
        return pd.DataFrame(columns=["aging_bucket", "work_order_count", "wip_value"])
    return (
        wip_aging.groupby("aging_bucket", as_index=False)
        .agg(work_order_count=("work_order", "count"), wip_value=("actual_cost", "sum"))
        .sort_values("aging_bucket")
    )
