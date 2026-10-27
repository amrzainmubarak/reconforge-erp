"""Deterministic, zero-float statutory tax calculation engine using integer minor units."""

from __future__ import annotations

from reconforge.packs.tax.models import TaxCalculationResult, TaxCategory, TaxLine, TaxRate


def calculate_tax_exclusive(
    net_minor: int,
    rate_basis_points: int,
    *,
    tax_id: str = "TAX",
    name: str = "Standard Tax",
    category: TaxCategory = TaxCategory.STANDARD,
    currency: str = "SAR",
    account_code: str = "",
) -> TaxCalculationResult:
    """Calculate tax for a tax-exclusive net amount using exact half-up integer rounding.

    Formula:
        tax_minor = (net_minor * rate_basis_points + 5000) // 10000
        gross_minor = net_minor + tax_minor
    """
    if type(net_minor) is not int or net_minor < 0:
        raise TypeError("net_minor must be a non-negative integer in minor units (float is forbidden).")
    if type(rate_basis_points) is not int or rate_basis_points < 0:
        raise TypeError("rate_basis_points must be a non-negative integer in basis points.")

    tax_minor = (net_minor * rate_basis_points + 5000) // 10000
    gross_minor = net_minor + tax_minor

    line = TaxLine(
        tax_id=tax_id,
        name=name,
        category=category,
        rate_basis_points=rate_basis_points,
        net_minor=net_minor,
        tax_minor=tax_minor,
        gross_minor=gross_minor,
        account_code=account_code,
    )
    return TaxCalculationResult(
        currency=currency,
        net_total_minor=net_minor,
        tax_total_minor=tax_minor,
        gross_total_minor=gross_minor,
        tax_lines=(line,),
        calculation_type="exclusive",
    )


def calculate_tax_inclusive(
    gross_minor: int,
    rate_basis_points: int,
    *,
    tax_id: str = "TAX",
    name: str = "Standard Tax",
    category: TaxCategory = TaxCategory.STANDARD,
    currency: str = "SAR",
    account_code: str = "",
) -> TaxCalculationResult:
    """Extract net and tax from a tax-inclusive gross amount using exact half-up integer rounding.

    Formula:
        denominator = 10000 + rate_basis_points
        net_minor = (gross_minor * 10000 + denominator // 2) // denominator
        tax_minor = gross_minor - net_minor

    Invariant:
        net_minor + tax_minor == gross_minor (zero integer leakage guaranteed).
    """
    if type(gross_minor) is not int or gross_minor < 0:
        raise TypeError("gross_minor must be a non-negative integer in minor units (float is forbidden).")
    if type(rate_basis_points) is not int or rate_basis_points < 0:
        raise TypeError("rate_basis_points must be a non-negative integer in basis points.")

    denominator = 10000 + rate_basis_points
    net_minor = (gross_minor * 10000 + denominator // 2) // denominator
    tax_minor = gross_minor - net_minor

    line = TaxLine(
        tax_id=tax_id,
        name=name,
        category=category,
        rate_basis_points=rate_basis_points,
        net_minor=net_minor,
        tax_minor=tax_minor,
        gross_minor=gross_minor,
        account_code=account_code,
    )
    return TaxCalculationResult(
        currency=currency,
        net_total_minor=net_minor,
        tax_total_minor=tax_minor,
        gross_total_minor=gross_minor,
        tax_lines=(line,),
        calculation_type="inclusive",
    )


def calculate_multi_rate_tax(
    items: list[tuple[int, TaxRate]],
    *,
    currency: str = "SAR",
    inclusive: bool = False,
) -> TaxCalculationResult:
    """Calculate multi-line taxes across multiple items and tax rates."""
    tax_lines: list[TaxLine] = []
    total_net = 0
    total_tax = 0
    total_gross = 0

    for amount_minor, rate in items:
        if inclusive:
            res = calculate_tax_inclusive(
                amount_minor,
                rate.rate_basis_points,
                tax_id=rate.tax_id,
                name=rate.name,
                category=rate.category,
                currency=currency,
                account_code=rate.account_code,
            )
        else:
            res = calculate_tax_exclusive(
                amount_minor,
                rate.rate_basis_points,
                tax_id=rate.tax_id,
                name=rate.name,
                category=rate.category,
                currency=currency,
                account_code=rate.account_code,
            )
        tax_lines.extend(res.tax_lines)
        total_net += res.net_total_minor
        total_tax += res.tax_total_minor
        total_gross += res.gross_total_minor

    return TaxCalculationResult(
        currency=currency,
        net_total_minor=total_net,
        tax_total_minor=total_tax,
        gross_total_minor=total_gross,
        tax_lines=tuple(tax_lines),
        calculation_type="inclusive" if inclusive else "exclusive",
    )
