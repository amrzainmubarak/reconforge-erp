"""Domain models for deterministic, zero-float statutory tax calculations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaxCategory(str, Enum):
    """Statutory tax categorization under VAT/GST frameworks."""

    STANDARD = "standard"
    REDUCED = "reduced"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"
    REVERSE_CHARGE = "reverse_charge"


@dataclass(frozen=True)
class TaxRate:
    """Configured statutory tax rate expressed in exact basis points (1 bp = 0.01%)."""

    tax_id: str
    name: str
    country_code: str
    category: TaxCategory
    rate_basis_points: int
    is_recoverable: bool = True
    account_code: str = ""

    def __post_init__(self) -> None:
        if type(self.rate_basis_points) is not int or not 0 <= self.rate_basis_points <= 100_000:
            raise ValueError("rate_basis_points must be an integer between 0 and 100000 (0% to 1000%).")
        if not self.country_code or len(self.country_code) != 2:
            raise ValueError("country_code must be a 2-letter uppercase ISO code.")


@dataclass(frozen=True)
class TaxLine:
    """Exact computed tax breakdown for a specific rate or line item in integer minor units."""

    tax_id: str
    name: str
    category: TaxCategory
    rate_basis_points: int
    net_minor: int
    tax_minor: int
    gross_minor: int
    account_code: str = ""

    def __post_init__(self) -> None:
        if type(self.net_minor) is not int or type(self.tax_minor) is not int or type(self.gross_minor) is not int:
            raise TypeError("All monetary amounts in TaxLine must be exact integers (minor units). Float is forbidden.")
        if self.net_minor + self.tax_minor != self.gross_minor:
            raise ValueError(
                f"TaxLine mathematical invariant violated: net ({self.net_minor}) + tax ({self.tax_minor}) != gross ({self.gross_minor})."
            )


@dataclass(frozen=True)
class TaxCalculationResult:
    """Immutable, zero-float result of a tax calculation with complete line auditability."""

    currency: str
    net_total_minor: int
    tax_total_minor: int
    gross_total_minor: int
    tax_lines: tuple[TaxLine, ...]
    calculation_type: str = "exclusive"

    def __post_init__(self) -> None:
        if (
            type(self.net_total_minor) is not int
            or type(self.tax_total_minor) is not int
            or type(self.gross_total_minor) is not int
        ):
            raise TypeError("Tax totals must be exact integers in minor units. Float is strictly forbidden.")
        if self.net_total_minor + self.tax_total_minor != self.gross_total_minor:
            raise ValueError(
                f"Tax calculation invariant violated: net ({self.net_total_minor}) + tax ({self.tax_total_minor}) != gross ({self.gross_total_minor})."
            )
        sum_net = sum(line.net_minor for line in self.tax_lines)
        sum_tax = sum(line.tax_minor for line in self.tax_lines)
        sum_gross = sum(line.gross_minor for line in self.tax_lines)
        if sum_net != self.net_total_minor or sum_tax != self.tax_total_minor or sum_gross != self.gross_total_minor:
            raise ValueError("Sum of tax lines does not exactly equal the declared tax totals.")
