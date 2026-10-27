"""United Arab Emirates statutory pack: FTA VAT rules and Designated Zones governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

from reconforge.packs.tax.models import TaxCategory, TaxRate

AE_VAT_STANDARD_BPS: Final[int] = 500  # 5.00%
AE_VAT_ZERO_RATED_BPS: Final[int] = 0
AE_VAT_EFFECTIVE: Final[str] = "2018-01-01"

# Official FTA Designated Zones under Cabinet Decision No. 59 of 2017
OFFICIAL_DESIGNATED_ZONES: Final[frozenset[str]] = frozenset({
    "DAFZA",  # Dubai Airport Freezone
    "JAFZA",  # Jebel Ali Free Zone
    "HFZA",  # Hamriyah Free Zone
    "SAIF",  # Sharjah Airport International Free Zone
    "KIZAD",  # Khalifa Industrial Zone Abu Dhabi
    "ADAFZ",  # Abu Dhabi Airport Freezone
    "RAKFTZ",  # Ras Al Khaimah Free Trade Zone
})


def validate_ae_trn(trn: str) -> bool:
    """Validate UAE Tax Registration Number (15 digits starting with 100)."""
    clean = trn.strip()
    return len(clean) == 15 and clean.isdigit() and clean.startswith("100")


def get_ae_vat_rate(category: TaxCategory = TaxCategory.STANDARD) -> TaxRate:
    """Return standard or zero-rated statutory rate for UAE FTA."""
    if category == TaxCategory.STANDARD:
        return TaxRate(
            tax_id="AE-VAT-STD",
            name="UAE Standard VAT 5%",
            country_code="AE",
            category=TaxCategory.STANDARD,
            rate_basis_points=AE_VAT_STANDARD_BPS,
            account_code="2210_VAT_OUTPUT_AE",
        )
    if category in {TaxCategory.ZERO_RATED, TaxCategory.EXEMPT}:
        return TaxRate(
            tax_id=f"AE-VAT-{category.value.upper()}",
            name=f"UAE VAT {category.value.capitalize()}",
            country_code="AE",
            category=category,
            rate_basis_points=AE_VAT_ZERO_RATED_BPS,
            account_code="2210_VAT_OUTPUT_AE",
        )
    raise ValueError(f"Unsupported UAE tax category: {category}")


def is_designated_zone_supply(source_zone: str, destination_zone: str) -> bool:
    """Determine whether goods movement is between FTA Designated Zones (out-of-scope for VAT)."""
    return source_zone.upper() in OFFICIAL_DESIGNATED_ZONES and destination_zone.upper() in OFFICIAL_DESIGNATED_ZONES


@dataclass(frozen=True)
class AETaxInvoiceSummary:
    trn_supplier: str
    trn_customer: str | None
    supply_date: str
    gross_minor: int
    net_minor: int
    vat_minor: int
    currency: str = "AED"

    def __post_init__(self) -> None:
        if not validate_ae_trn(self.trn_supplier):
            raise ValueError(f"Invalid UAE supplier TRN: {self.trn_supplier}")
        if date.fromisoformat(self.supply_date) < date.fromisoformat(AE_VAT_EFFECTIVE):
            raise ValueError(f"Supply date {self.supply_date} precedes UAE VAT enactment.")
        if self.net_minor + self.vat_minor != self.gross_minor:
            raise ValueError("Invariant violated: net_minor + vat_minor != gross_minor")
