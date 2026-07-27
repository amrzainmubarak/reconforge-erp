"""Synthetic reconciliation scenario definitions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from random import Random
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class IndustryProfile:
    """Industry-specific labels for synthetic data."""

    name: str
    workshops: list[str]
    service_types: list[str]
    categories: list[str]


PROFILES = {
    "workshop": IndustryProfile(
        name="workshop",
        workshops=["Main Workshop", "Electrical Bay", "Transmission Bay"],
        service_types=["Preventive maintenance", "Repair", "Inspection"],
        categories=["Brakes", "Filters", "Electrical", "Engine", "Transmission"],
    ),
    "manufacturing": IndustryProfile(
        name="manufacturing",
        workshops=["Assembly Line", "Machine Shop", "Maintenance Cell"],
        service_types=["Production order", "Rework", "Preventive maintenance"],
        categories=["Raw Material", "Consumables", "Electrical", "Hydraulics", "WIP"],
    ),
    "fleet": IndustryProfile(
        name="fleet",
        workshops=["Fleet Workshop", "Field Service", "Tire Bay"],
        service_types=["Scheduled service", "Breakdown repair", "Inspection"],
        categories=["Brakes", "Filters", "Tires", "Electrical", "Engine"],
    ),
    "dealership": IndustryProfile(
        name="dealership",
        workshops=["Quick Service", "Warranty Bay", "Body Shop"],
        service_types=["Customer pay", "Warranty", "Recall", "Internal rework"],
        categories=["Brakes", "Filters", "Body", "Electrical", "Engine"],
    ),
    "service": IndustryProfile(
        name="service",
        workshops=["Field Service", "Service Center", "Contract Desk"],
        service_types=["Contract service", "Emergency repair", "Installation", "Inspection"],
        categories=["Consumables", "Electrical", "Hydraulics", "Service Kit", "Engine"],
    ),
}


SCENARIOS = [
    "exact_match",
    "fuzzy_match",
    "missing_gl",
    "missing_stock",
    "value_mismatch",
    "date_mismatch",
    "direct_fit",
    "missing_old_part",
]


def _choice(random: Random, values: list[T]) -> T:
    # Deterministic synthetic data only; not used for secrets or cryptography.
    return random.choice(values)  # nosec B311


def _random_unit_decimal(random: Random) -> Decimal:
    # Deterministic synthetic data only; not used for secrets or cryptography.
    step = random.randrange(1_000_000)  # nosec B311
    digits = tuple(int(character) for character in str(step)) if step else (0,)
    return Decimal((0, digits, -6))


def pick_profile(industry: str) -> IndustryProfile:
    """Return an industry profile."""

    try:
        return PROFILES[industry]
    except KeyError as exc:
        raise ValueError(f"Unknown synthetic industry profile: {industry}") from exc


def pick_scenario(random: Random, exception_rate: Decimal, critical_rate: Decimal) -> str:
    """Pick a synthetic reconciliation scenario."""

    roll = _random_unit_decimal(random)
    if roll > exception_rate:
        return "fuzzy_match" if _random_unit_decimal(random) < Decimal("0.15") else "exact_match"
    if _random_unit_decimal(random) < critical_rate:
        return _choice(random, ["missing_gl", "direct_fit", "missing_old_part"])
    return _choice(random, ["missing_stock", "value_mismatch", "date_mismatch"])
