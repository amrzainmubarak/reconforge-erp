"""United Kingdom statutory pack: HMRC Making Tax Digital (MTD) VAT returns and rates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from reconforge.packs.tax.models import TaxCategory, TaxRate

GB_VAT_STANDARD_BPS: Final[int] = 2000  # 20.00%
GB_VAT_REDUCED_BPS: Final[int] = 500  # 5.00%
GB_VAT_ZERO_RATED_BPS: Final[int] = 0
GB_HMRC_MTD_EFFECTIVE: Final[str] = "2022-04-01"


def get_gb_vat_rate(category: TaxCategory = TaxCategory.STANDARD) -> TaxRate:
    """Return statutory rate for United Kingdom HMRC VAT."""
    if category == TaxCategory.STANDARD:
        return TaxRate(
            tax_id="GB-VAT-STD-20",
            name="UK Standard VAT 20%",
            country_code="GB",
            category=TaxCategory.STANDARD,
            rate_basis_points=GB_VAT_STANDARD_BPS,
            account_code="2200_VAT_OUTPUT_UK",
        )
    if category == TaxCategory.REDUCED:
        return TaxRate(
            tax_id="GB-VAT-RED-5",
            name="UK Reduced VAT 5%",
            country_code="GB",
            category=TaxCategory.REDUCED,
            rate_basis_points=GB_VAT_REDUCED_BPS,
            account_code="2200_VAT_OUTPUT_UK",
        )
    if category in {TaxCategory.ZERO_RATED, TaxCategory.EXEMPT}:
        return TaxRate(
            tax_id=f"GB-VAT-{category.value.upper()}",
            name=f"UK VAT {category.value.capitalize()}",
            country_code="GB",
            category=category,
            rate_basis_points=GB_VAT_ZERO_RATED_BPS,
            account_code="2200_VAT_OUTPUT_UK",
        )
    raise ValueError(f"Unsupported UK tax category: {category}")


@dataclass(frozen=True)
class HMRC9BoxVATReturn:
    """HMRC MTD 9-Box VAT Return in exact integer minor units (pence)."""

    box1_vat_due_sales_minor: int  # VAT due on sales and other outputs
    box2_vat_due_acquisitions_minor: int  # VAT due on EC acquisitions
    box4_vat_reclaimed_minor: int  # VAT reclaimed on purchases and other inputs
    box6_total_sales_ex_vat_minor: int  # Total value of sales and other outputs excl. VAT
    box7_total_purchases_ex_vat_minor: int  # Total value of purchases excl. VAT
    box8_total_supplies_ex_vat_minor: int  # Total value of goods to EC members
    box9_total_acquisitions_ex_vat_minor: int  # Total value of goods from EC members

    @property
    def box3_total_vat_due_minor(self) -> int:
        """Box 3 = Box 1 + Box 2."""
        return self.box1_vat_due_sales_minor + self.box2_vat_due_acquisitions_minor

    @property
    def box5_net_vat_due_minor(self) -> int:
        """Box 5 = Box 3 - Box 4 (positive = payable to HMRC, negative = reclaimable from HMRC)."""
        return self.box3_total_vat_due_minor - self.box4_vat_reclaimed_minor

    def __post_init__(self) -> None:
        for field_name in (
            "box1_vat_due_sales_minor",
            "box2_vat_due_acquisitions_minor",
            "box4_vat_reclaimed_minor",
            "box6_total_sales_ex_vat_minor",
            "box7_total_purchases_ex_vat_minor",
            "box8_total_supplies_ex_vat_minor",
            "box9_total_acquisitions_ex_vat_minor",
        ):
            val = getattr(self, field_name)
            if type(val) is not int or val < 0:
                raise TypeError(f"{field_name} must be a non-negative integer minor units (float forbidden).")
