"""Synthetic paired EUR/GBP functional books and explicit USD adjustment."""

from typing import Any

from reconforge.domain.finance_posting import digest_payload
from reconforge.domain.intercompany_fx import (
    GroupAccounts,
    GroupBook,
    IntercompanyFxPreparation,
    PartyAccounts,
    PartyBook,
    recognition_equation,
)
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.utils.money import CurrencyRegistryContext

ACCOUNTS = (
    ("IC2_AR", "Asset", "CurrentAsset"), ("IC2_AP", "Liability", "CurrentLiability"),
    ("IC2_REV", "Income", "Income"), ("IC2_EXP", "Expense", "Expense"),
    ("IC2_CASH", "Asset", "CurrentAsset"), ("IC2_RGAIN", "Income", "Income"),
    ("IC2_RLOSS", "Expense", "Expense"), ("IC2_UGAIN", "Income", "Income"),
    ("IC2_ULOSS", "Expense", "Expense"), ("IC2_CTA", "Equity", "Equity"),
)


def rate(value: str, day: str, label: str = "synthetic-reviewed-rate-v2") -> HistoricalRate:
    return HistoricalRate(value, label, day + "T12:00:00Z")


def preparation(reference: str = "ICFX-TRADE-1", amount: int = 10001) -> IntercompanyFxPreparation:
    seller = PartyAccounts("IC2_AR", "IC2_REV", "IC2_CASH", "IC2_RGAIN", "IC2_RLOSS", "IC2_UGAIN", "IC2_ULOSS")
    buyer = PartyAccounts("IC2_AP", "IC2_EXP", "IC2_CASH", "IC2_RGAIN", "IC2_RLOSS", "IC2_UGAIN", "IC2_ULOSS")
    group = GroupAccounts("IC2_AR", "IC2_AP", "IC2_REV", "IC2_EXP", "IC2_CASH", "IC2_RGAIN", "IC2_RLOSS", "IC2_UGAIN", "IC2_ULOSS", "IC2_CTA")
    return IntercompanyFxPreparation("work", "org", "ORG", reference, "USD", amount, "2026-10-03",
        PartyBook("entity", "ENTITY", "EUR", "IC2_EUR", "period", seller),
        PartyBook("buyer", "BUYER", "GBP", "IC2_GBP", "period", buyer),
        GroupBook("group", "GROUP", "USD", "IC2_USD", "period", group),
        rate("1.25", "2026-10-03"), rate("0.8", "2026-10-03"), "Explicit two-party foreign service trade")


def source_fixture() -> tuple[dict[str, Any], CurrencyRegistryContext]:
    context = CurrencyRegistryContext.from_installed()
    request = preparation().payload()
    source = {"schema_version": "intercompany-fx-source-v2", "id": "IC2S-" + "a" * 32,
        "request": request, "policies": recognition_equation(request, context)["policies"], "preparer_actor_id": "maker"}
    source["source_digest"] = digest_payload(source)
    return source, context
