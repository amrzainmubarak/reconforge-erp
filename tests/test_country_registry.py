"""Tests for Country Coverage Registry and jurisdiction qualification contracts."""

import pytest

from reconforge.packs.country_registry import (
    GLOBAL_COUNTRY_REGISTRY,
    CountryCoverageRegistry,
    StatutoryPackDeclaration,
    UnsupportedCountryJurisdictionError,
)


def test_statutory_pack_validation_rules() -> None:
    # Invalid country code
    with pytest.raises(ValueError, match="2-letter uppercase ISO"):
        StatutoryPackDeclaration(
            country_code="USA",
            jurisdiction_name="United States",
            pack_category="tax_vat",
            version="1.0.0",
            effective_from="2024-01-01",
            effective_to=None,
            status="planned",
            external_review_ref=None,
            capabilities=(),
        )

    # Inverted date window
    with pytest.raises(ValueError, match="cannot succeed effective_to"):
        StatutoryPackDeclaration(
            country_code="US",
            jurisdiction_name="United States",
            pack_category="tax_vat",
            version="1.0.0",
            effective_from="2025-01-01",
            effective_to="2024-12-31",
            status="planned",
            external_review_ref=None,
            capabilities=(),
        )

    # Verified without external review
    with pytest.raises(ValueError, match="require an explicit external review reference"):
        StatutoryPackDeclaration(
            country_code="US",
            jurisdiction_name="United States",
            pack_category="tax_vat",
            version="1.0.0",
            effective_from="2024-01-01",
            effective_to=None,
            status="verified",
            external_review_ref=None,
            capabilities=("nexus",),
        )


def test_country_registry_unverified_pack_refusal() -> None:
    registry = CountryCoverageRegistry()
    pack = StatutoryPackDeclaration(
        country_code="SA",
        jurisdiction_name="Saudi Arabia",
        pack_category="tax_vat",
        version="1.0.0",
        effective_from="2020-07-01",
        effective_to=None,
        status="beta",
        external_review_ref=None,
        capabilities=("standard_15pct",),
    )
    registry.register(pack)

    # Querying unverified pack must refuse when requiring verified capability
    with pytest.raises(UnsupportedCountryJurisdictionError, match="has status 'beta'"):
        registry.require_verified_capability("SA", "tax_vat", "2024-01-01")

    # Unregistered jurisdiction refusal
    with pytest.raises(UnsupportedCountryJurisdictionError, match="is not registered"):
        registry.require_verified_capability("FR", "tax_vat", "2024-01-01")


def test_verified_pack_date_window_enforcement() -> None:
    registry = CountryCoverageRegistry()
    pack = StatutoryPackDeclaration(
        country_code="DE",
        jurisdiction_name="Germany (USt)",
        pack_category="tax_vat",
        version="2.1.0",
        effective_from="2021-01-01",
        effective_to="2025-12-31",
        status="verified",
        external_review_ref="DE-TAX-AUDIT-2021-CERT-009",
        capabilities=("standard_19pct", "reduced_7pct"),
    )
    registry.register(pack)

    # Valid in-window query
    verified = registry.require_verified_capability("DE", "tax_vat", "2023-06-15")
    assert verified.country_code == "DE"
    assert "standard_19pct" in verified.capabilities

    # Date preceding effective window
    with pytest.raises(UnsupportedCountryJurisdictionError, match="precedes pack effective date"):
        registry.require_verified_capability("DE", "tax_vat", "2020-12-31")

    # Date succeeding expiration
    with pytest.raises(UnsupportedCountryJurisdictionError, match="exceeds pack expiration date"):
        registry.require_verified_capability("DE", "tax_vat", "2026-01-01")


def test_global_registry_inventory_integrity() -> None:
    coverage = GLOBAL_COUNTRY_REGISTRY.list_coverage()
    assert len(coverage) >= 5
    country_codes = {entry["country_code"] for entry in coverage}
    assert {"SA", "AE", "US", "GB"}.issubset(country_codes)
