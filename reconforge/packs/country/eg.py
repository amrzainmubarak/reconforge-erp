"""Egypt statutory pack: Egyptian Tax Authority (ETA) e-invoicing and VAT rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from reconforge.packs.tax.models import TaxCategory, TaxRate

EG_VAT_STANDARD_BPS: Final[int] = 1400  # 14.00%
EG_VAT_MACHINERY_BPS: Final[int] = 500  # 5.00% for capital equipment
EG_VAT_ZERO_RATED_BPS: Final[int] = 0
EG_ETA_PHASE1_EFFECTIVE: Final[str] = "2020-11-15"


def validate_eg_tax_id(tax_id: str) -> bool:
    """Validate Egyptian 9-digit Tax Registration Number."""
    clean = tax_id.strip().replace("-", "")
    return len(clean) == 9 and clean.isdigit()


def get_eg_vat_rate(category: TaxCategory = TaxCategory.STANDARD) -> TaxRate:
    """Return statutory rate for Egyptian Tax Authority VAT."""
    if category == TaxCategory.STANDARD:
        return TaxRate(
            tax_id="EG-VAT-STD-14",
            name="Egypt Standard VAT 14%",
            country_code="EG",
            category=TaxCategory.STANDARD,
            rate_basis_points=EG_VAT_STANDARD_BPS,
            account_code="2200_VAT_OUTPUT_EG",
        )
    if category == TaxCategory.REDUCED:
        return TaxRate(
            tax_id="EG-VAT-MACH-5",
            name="Egypt Capital Machinery VAT 5%",
            country_code="EG",
            category=TaxCategory.REDUCED,
            rate_basis_points=EG_VAT_MACHINERY_BPS,
            account_code="2200_VAT_OUTPUT_EG",
        )
    if category in {TaxCategory.ZERO_RATED, TaxCategory.EXEMPT}:
        return TaxRate(
            tax_id=f"EG-VAT-{category.value.upper()}",
            name=f"Egypt VAT {category.value.capitalize()}",
            country_code="EG",
            category=category,
            rate_basis_points=EG_VAT_ZERO_RATED_BPS,
            account_code="2200_VAT_OUTPUT_EG",
        )
    raise ValueError(f"Unsupported Egyptian tax category: {category}")


@dataclass(frozen=True)
class ETADocumentHeader:
    """Egyptian Tax Authority (ETA) e-invoicing standard document header."""

    issuer_id: str
    issuer_name: str
    receiver_id: str
    receiver_name: str
    document_type: str  # "I" for Invoice, "C" for Credit Note, "D" for Debit Note
    document_type_version: str  # e.g., "1.0" or "0.9"
    date_time_issued: str
    taxpayer_activity_code: str
    internal_id: str

    def __post_init__(self) -> None:
        if not validate_eg_tax_id(self.issuer_id):
            raise ValueError(f"Invalid Egyptian issuer tax ID: {self.issuer_id}")
        if self.document_type not in {"I", "C", "D"}:
            raise ValueError(f"ETA document_type must be 'I', 'C', or 'D' (got '{self.document_type}').")
