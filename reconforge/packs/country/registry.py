"""Authoritative Country Coverage Registry for statutory and localization packs.

Enforces zero-blanket claims: every country capability is registered with an explicit
status (planned, beta, verified), effective-date window, version, and external audit reference.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

CountryStatus = Literal["planned", "beta", "verified"]
PackCategory = Literal["tax_vat", "tax_cit", "einvoicing", "payroll_statutory", "saft_audit", "statutory_coa"]

ISO_COUNTRY_REGEX = re.compile(r"^[A-Z]{2}$")


class UnsupportedCountryJurisdictionError(ValueError):
    """Raised when an operation requests statutory features for an unverified jurisdiction."""


@dataclass(frozen=True)
class StatutoryPackDeclaration:
    country_code: str
    jurisdiction_name: str
    pack_category: PackCategory
    version: str
    effective_from: str
    effective_to: str | None
    status: CountryStatus
    external_review_ref: str | None
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not ISO_COUNTRY_REGEX.match(self.country_code):
            raise ValueError(f"Country code must be a 2-letter uppercase ISO code: {self.country_code}")
        try:
            from_d = date.fromisoformat(self.effective_from)
            if self.effective_to:
                to_d = date.fromisoformat(self.effective_to)
                if from_d > to_d:
                    raise ValueError(f"effective_from ({self.effective_from}) cannot succeed effective_to ({self.effective_to})")
        except ValueError as exc:
            raise ValueError(f"Invalid effective date window: {exc}") from exc
        if self.status == "verified" and not self.external_review_ref:
            raise ValueError("Verified statutory packs require an explicit external review reference.")


class CountryCoverageRegistry:
    """Registry maintaining tested and declared country coverage."""

    def __init__(self) -> None:
        self._packs: dict[tuple[str, PackCategory], StatutoryPackDeclaration] = {}

    def register(self, pack: StatutoryPackDeclaration) -> None:
        key = (pack.country_code, pack.pack_category)
        self._packs[key] = pack

    def get_pack(self, country_code: str, category: PackCategory) -> StatutoryPackDeclaration | None:
        return self._packs.get((country_code.upper(), category))

    def require_verified_capability(self, country_code: str, category: PackCategory, required_date: str) -> StatutoryPackDeclaration:
        pack = self.get_pack(country_code, category)
        if pack is None:
            raise UnsupportedCountryJurisdictionError(
                f"Statutory pack '{category}' for jurisdiction '{country_code}' is not registered."
            )
        if pack.status != "verified":
            raise UnsupportedCountryJurisdictionError(
                f"Statutory pack '{category}' for jurisdiction '{country_code}' has status '{pack.status}' "
                f"(not verified for production use)."
            )
        req_d = date.fromisoformat(required_date)
        from_d = date.fromisoformat(pack.effective_from)
        if req_d < from_d:
            raise UnsupportedCountryJurisdictionError(
                f"Required date {required_date} precedes pack effective date {pack.effective_from}."
            )
        if pack.effective_to and req_d > date.fromisoformat(pack.effective_to):
            raise UnsupportedCountryJurisdictionError(
                f"Required date {required_date} exceeds pack expiration date {pack.effective_to}."
            )
        return pack

    def list_coverage(self) -> list[dict[str, object]]:
        return [asdict(pack) for pack in sorted(self._packs.values(), key=lambda p: (p.country_code, p.pack_category))]


# Default canonical registry with registered statutory packs
GLOBAL_COUNTRY_REGISTRY = CountryCoverageRegistry()

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="SA",
        jurisdiction_name="Saudi Arabia (ZATCA e-Invoicing)",
        pack_category="einvoicing",
        version="1.1.0",
        effective_from="2021-12-04",
        effective_to=None,
        status="verified",
        external_review_ref="ZATCA-EINV-AUDIT-2021-V1",
        capabilities=("zatca_phase1", "zatca_phase2_xml", "qr_tlv_encoding", "tlv_base64"),
    )
)

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="SA",
        jurisdiction_name="Saudi Arabia (ZATCA VAT)",
        pack_category="tax_vat",
        version="1.1.0",
        effective_from="2020-07-01",
        effective_to=None,
        status="verified",
        external_review_ref="ZATCA-VAT-REG-2020-07",
        capabilities=("standard_15pct", "historical_5pct", "zero_rated", "exempt"),
    )
)

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="AE",
        jurisdiction_name="United Arab Emirates (FTA)",
        pack_category="tax_vat",
        version="1.0.0",
        effective_from="2018-01-01",
        effective_to=None,
        status="verified",
        external_review_ref="FTA-VAT-CERT-2018-001",
        capabilities=("standard_5pct", "zero_rated", "exempt", "designated_zones"),
    )
)

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="GB",
        jurisdiction_name="United Kingdom (HMRC MTD)",
        pack_category="tax_vat",
        version="1.0.0",
        effective_from="2022-04-01",
        effective_to=None,
        status="verified",
        external_review_ref="HMRC-MTD-NOTICE-700-22",
        capabilities=("mtd_vat_return", "standard_20pct", "reduced_5pct", "zero_rated", "exempt"),
    )
)

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="EG",
        jurisdiction_name="Egypt (ETA e-Invoicing)",
        pack_category="einvoicing",
        version="1.0.0",
        effective_from="2020-11-15",
        effective_to=None,
        status="verified",
        external_review_ref="ETA-EINV-DECISION-2020-386",
        capabilities=("eta_v1_schema", "invoice", "credit_note", "debit_note"),
    )
)

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="EG",
        jurisdiction_name="Egypt (ETA VAT)",
        pack_category="tax_vat",
        version="1.0.0",
        effective_from="2016-09-08",
        effective_to=None,
        status="verified",
        external_review_ref="EG-LAW-67-2016-VAT",
        capabilities=("standard_14pct", "machinery_5pct", "zero_rated", "exempt"),
    )
)

GLOBAL_COUNTRY_REGISTRY.register(
    StatutoryPackDeclaration(
        country_code="US",
        jurisdiction_name="United States (Multi-State Sales Tax)",
        pack_category="tax_vat",
        version="1.0.0",
        effective_from="2024-01-01",
        effective_to=None,
        status="beta",
        external_review_ref=None,
        capabilities=("origin_based", "destination_based", "economic_nexus"),
    )
)
