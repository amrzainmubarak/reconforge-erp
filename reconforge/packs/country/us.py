"""United States statutory pack: Multi-state sales tax, sourcing rules, and economic nexus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from reconforge.packs.tax.models import TaxCategory, TaxRate

SourcingRule = Literal["origin", "destination"]

# Standard South Dakota v. Wayfair benchmark thresholds
DEFAULT_ECONOMIC_NEXUS_REVENUE_THRESHOLD_MINOR: Final[int] = 10_000_000  # $100,000.00
DEFAULT_ECONOMIC_NEXUS_TRANSACTION_COUNT: Final[int] = 200


@dataclass(frozen=True)
class USStateTaxRule:
    """State-level sales tax rule with statutory sourcing and rate basis points."""

    state_code: str
    state_name: str
    state_rate_bps: int
    sourcing_rule: SourcingRule
    has_economic_nexus: bool = True
    revenue_threshold_minor: int = DEFAULT_ECONOMIC_NEXUS_REVENUE_THRESHOLD_MINOR
    transaction_threshold_count: int = DEFAULT_ECONOMIC_NEXUS_TRANSACTION_COUNT

    def to_tax_rate(self) -> TaxRate:
        return TaxRate(
            tax_id=f"US-{self.state_code}-SALES",
            name=f"{self.state_name} Sales Tax",
            country_code="US",
            category=TaxCategory.STANDARD,
            rate_basis_points=self.state_rate_bps,
            account_code=f"2200_SALES_TAX_{self.state_code}",
        )


US_STATE_RULES: Final[dict[str, USStateTaxRule]] = {
    "CA": USStateTaxRule(state_code="CA", state_name="California", state_rate_bps=725, sourcing_rule="origin"),
    "TX": USStateTaxRule(state_code="TX", state_name="Texas", state_rate_bps=625, sourcing_rule="origin"),
    "NY": USStateTaxRule(state_code="NY", state_name="New York", state_rate_bps=400, sourcing_rule="destination"),
    "WA": USStateTaxRule(state_code="WA", state_name="Washington", state_rate_bps=650, sourcing_rule="destination"),
    "IL": USStateTaxRule(state_code="IL", state_name="Illinois", state_rate_bps=625, sourcing_rule="origin"),
    "FL": USStateTaxRule(state_code="FL", state_name="Florida", state_rate_bps=600, sourcing_rule="destination"),
}


def evaluate_economic_nexus(
    state_code: str,
    annual_sales_minor: int,
    annual_transactions: int,
) -> bool:
    """Evaluate whether an out-of-state remote seller has established economic nexus."""
    rule = US_STATE_RULES.get(state_code.upper())
    if not rule or not rule.has_economic_nexus:
        return False
    return (
        annual_sales_minor >= rule.revenue_threshold_minor
        or annual_transactions >= rule.transaction_threshold_count
    )


def determine_applicable_rate_bps(
    origin_state: str,
    destination_state: str,
    *,
    has_nexus_in_destination: bool = True,
) -> int:
    """Determine applicable sales tax rate basis points based on origin/destination sourcing rules."""
    dest_rule = US_STATE_RULES.get(destination_state.upper())
    orig_rule = US_STATE_RULES.get(origin_state.upper())

    if dest_rule and dest_rule.sourcing_rule == "destination" and has_nexus_in_destination:
        return dest_rule.state_rate_bps
    if orig_rule and orig_rule.sourcing_rule == "origin":
        return orig_rule.state_rate_bps
    if dest_rule and has_nexus_in_destination:
        return dest_rule.state_rate_bps
    return 0
