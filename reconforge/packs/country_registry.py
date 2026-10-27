"""Backward-compatible shim for Country Coverage Registry.

Canonical implementation lives in `reconforge.packs.country.registry`.
"""

from reconforge.packs.country.registry import (
    GLOBAL_COUNTRY_REGISTRY,
    ISO_COUNTRY_REGEX,
    CountryCoverageRegistry,
    CountryStatus,
    PackCategory,
    StatutoryPackDeclaration,
    UnsupportedCountryJurisdictionError,
)

__all__ = [
    "CountryStatus",
    "PackCategory",
    "ISO_COUNTRY_REGEX",
    "UnsupportedCountryJurisdictionError",
    "StatutoryPackDeclaration",
    "CountryCoverageRegistry",
    "GLOBAL_COUNTRY_REGISTRY",
]
