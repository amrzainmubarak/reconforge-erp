"""Synthetic reconciliation scenario definitions."""

from __future__ import annotations

from dataclasses import dataclass
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


def _random_float(random: Random) -> float:
    # Deterministic synthetic data only; not used for secrets or cryptography.
    return random.random()  # nosec B311


def pick_profile(industry: str) -> IndustryProfile:
    """Return an industry profile."""

    return PROFILES.get(industry, PROFILES["workshop"])


def pick_scenario(random: Random, exception_rate: float, critical_rate: float) -> str:
    """Pick a synthetic reconciliation scenario."""

    roll = _random_float(random)
    if roll > exception_rate:
        return "fuzzy_match" if _random_float(random) < 0.15 else "exact_match"
    if _random_float(random) < critical_rate:
        return _choice(random, ["missing_gl", "direct_fit", "missing_old_part"])
    return _choice(random, ["missing_stock", "value_mismatch", "date_mismatch"])
