"""Deterministic CRM Opportunity Pipeline, Tiered Quotation Approvals, and Customer Contract Lifecycle.

Enforces zero-float pricing, strict integer minor-unit arithmetic, basis-point discount calculations,
and maker-checker commercial governance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.fixed_assets import exact_minor

OpportunityStage = Literal["lead", "qualified", "proposal", "negotiation", "won", "lost"]
QuoteStatus = Literal["draft", "submitted", "approved", "rejected", "converted"]
BillingFrequency = Literal["monthly", "quarterly", "annual", "milestone", "one_off"]
ContractStatus = Literal["active", "suspended", "terminated", "expired"]

BPS_DENOMINATOR = 10_000

# Approval thresholds in basis points:
# <= 10% (1,000 bps): standard sales rep
# 10% - 20% (2,000 bps): sales manager required
# > 20%: commercial director / VP required
MANAGER_DISCOUNT_THRESHOLD_BPS = 1_000
DIRECTOR_DISCOUNT_THRESHOLD_BPS = 2_000


def scale_minor_by_bps(amount_minor: int, bps: int) -> int:
    """Scale integer minor amount by basis points with deterministic half-up rounding."""
    if not (0 <= bps <= 100_000):
        raise FinancePostingError("crm_bps_invalid", "Basis points must be between 0 and 100,000.")
    exact_minor(amount_minor, "amount_minor", zero=True)
    return (amount_minor * bps + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR


@dataclass(frozen=True)
class Opportunity:
    """Commercial sales opportunity in pipeline."""

    opportunity_id: str
    workspace_id: str
    organization_id: str
    customer_id: str
    title: str
    stage: OpportunityStage
    estimated_close_date: str  # ISO date
    currency: str
    projected_amount_minor: int
    win_probability_bps: int  # 0..10,000 bps

    def __post_init__(self) -> None:
        text(self.opportunity_id, "opportunity_id", maximum=64)
        text(self.workspace_id, "workspace_id", maximum=64)
        text(self.customer_id, "customer_id", maximum=64)
        text(self.title, "title", maximum=128)
        text(self.currency, "currency", maximum=3)
        date.fromisoformat(self.estimated_close_date)
        exact_minor(self.projected_amount_minor, "projected_amount_minor", zero=True)
        if not (0 <= self.win_probability_bps <= BPS_DENOMINATOR):
            raise FinancePostingError("crm_probability_invalid", "Win probability must be 0..10,000 bps.")

    @property
    def weighted_pipeline_value_minor(self) -> int:
        """Expected pipeline value weighted by win probability."""
        if self.stage == "won":
            return self.projected_amount_minor
        if self.stage == "lost":
            return 0
        return scale_minor_by_bps(self.projected_amount_minor, self.win_probability_bps)


@dataclass(frozen=True)
class QuotationLineItem:
    """Line item in a customer sales quotation."""

    line_number: int
    item_id: str
    description: str
    quantity: int
    unit_price_minor: int
    discount_bps: int = 0  # Discount in basis points (e.g. 1500 = 15.00%)

    def __post_init__(self) -> None:
        if self.line_number < 1:
            raise FinancePostingError("crm_line_invalid", "Line number must be >= 1.")
        text(self.item_id, "item_id", maximum=64)
        text(self.description, "description", maximum=128)
        if self.quantity < 1:
            raise FinancePostingError("crm_qty_invalid", "Quantity must be >= 1.")
        exact_minor(self.unit_price_minor, "unit_price_minor", zero=True)
        if not (0 <= self.discount_bps <= BPS_DENOMINATOR):
            raise FinancePostingError("crm_discount_invalid", "Discount bps must be 0..10,000.")

    @property
    def gross_amount_minor(self) -> int:
        return self.quantity * self.unit_price_minor

    @property
    def discount_amount_minor(self) -> int:
        return scale_minor_by_bps(self.gross_amount_minor, self.discount_bps)

    @property
    def net_amount_minor(self) -> int:
        return self.gross_amount_minor - self.discount_amount_minor


@dataclass(frozen=True)
class CustomerQuotation:
    """Binding or non-binding customer quotation with governance."""

    quote_id: str
    opportunity_id: str
    workspace_id: str
    customer_id: str
    currency: str
    valid_until: str  # ISO date
    submitter_user_id: str
    status: QuoteStatus
    lines: tuple[QuotationLineItem, ...]
    approved_by_user_id: str | None = None
    approval_role: str | None = None

    def __post_init__(self) -> None:
        text(self.quote_id, "quote_id", maximum=64)
        text(self.opportunity_id, "opportunity_id", maximum=64)
        text(self.workspace_id, "workspace_id", maximum=64)
        text(self.customer_id, "customer_id", maximum=64)
        text(self.currency, "currency", maximum=3)
        text(self.submitter_user_id, "submitter_user_id", maximum=64)
        date.fromisoformat(self.valid_until)
        if not self.lines:
            raise FinancePostingError("crm_quote_empty", "Quotation must contain at least one line.")

    @property
    def total_gross_minor(self) -> int:
        return sum(line.gross_amount_minor for line in self.lines)

    @property
    def total_discount_minor(self) -> int:
        return sum(line.discount_amount_minor for line in self.lines)

    @property
    def total_net_minor(self) -> int:
        return sum(line.net_amount_minor for line in self.lines)

    @property
    def effective_discount_bps(self) -> int:
        gross = self.total_gross_minor
        if gross == 0:
            return 0
        return (self.total_discount_minor * BPS_DENOMINATOR + (gross // 2)) // gross

    def approve(self, approver_user_id: str, approver_role: str) -> CustomerQuotation:
        """Approve a quote enforcing maker-checker and role thresholds."""
        if approver_user_id == self.submitter_user_id:
            raise FinancePostingError("crm_sod_violation", "Submitter cannot approve their own quotation.")

        eff_bps = self.effective_discount_bps

        if eff_bps > DIRECTOR_DISCOUNT_THRESHOLD_BPS:
            if approver_role not in ("commercial_director", "vp_sales", "cfo", "admin"):
                raise FinancePostingError(
                    "crm_authorization_insufficient",
                    f"Discounts over {DIRECTOR_DISCOUNT_THRESHOLD_BPS // 100}% require Commercial Director or CFO approval.",
                )
        elif eff_bps > MANAGER_DISCOUNT_THRESHOLD_BPS and approver_role not in (
            "sales_manager",
            "commercial_director",
            "vp_sales",
            "cfo",
            "admin",
        ):
            raise FinancePostingError(
                "crm_authorization_insufficient",
                f"Discounts over {MANAGER_DISCOUNT_THRESHOLD_BPS // 100}% require Sales Manager or higher approval.",
            )

        return CustomerQuotation(
            quote_id=self.quote_id,
            opportunity_id=self.opportunity_id,
            workspace_id=self.workspace_id,
            customer_id=self.customer_id,
            currency=self.currency,
            valid_until=self.valid_until,
            submitter_user_id=self.submitter_user_id,
            status="approved",
            lines=self.lines,
            approved_by_user_id=approver_user_id,
            approval_role=approver_role,
        )


@dataclass(frozen=True)
class CustomerContract:
    """Executed customer contract created from an approved quotation."""

    contract_id: str
    quote_id: str
    workspace_id: str
    organization_id: str
    customer_id: str
    currency: str
    start_date: str  # ISO date
    end_date: str  # ISO date
    billing_frequency: BillingFrequency
    total_contract_value_minor: int
    status: ContractStatus

    def __post_init__(self) -> None:
        text(self.contract_id, "contract_id", maximum=64)
        text(self.quote_id, "quote_id", maximum=64)
        text(self.customer_id, "customer_id", maximum=64)
        text(self.currency, "currency", maximum=3)
        sd = date.fromisoformat(self.start_date)
        ed = date.fromisoformat(self.end_date)
        if sd > ed:
            raise FinancePostingError("crm_contract_date_invalid", "start_date cannot exceed end_date.")
        exact_minor(self.total_contract_value_minor, "total_contract_value_minor")


def convert_quote_to_contract(
    quote: CustomerQuotation,
    contract_id: str,
    organization_id: str,
    start_date: str,
    end_date: str,
    billing_frequency: BillingFrequency,
    as_of_date: str,
) -> CustomerContract:
    """Convert an approved, non-expired quotation into a legal customer contract."""
    if quote.status != "approved":
        raise FinancePostingError("crm_quote_not_approved", "Only approved quotations can be converted to contracts.")

    req_d = date.fromisoformat(as_of_date)
    val_d = date.fromisoformat(quote.valid_until)
    if req_d > val_d:
        raise FinancePostingError("crm_quote_expired", f"Quotation expired on {quote.valid_until}.")

    return CustomerContract(
        contract_id=contract_id,
        quote_id=quote.quote_id,
        workspace_id=quote.workspace_id,
        organization_id=organization_id,
        customer_id=quote.customer_id,
        currency=quote.currency,
        start_date=start_date,
        end_date=end_date,
        billing_frequency=billing_frequency,
        total_contract_value_minor=quote.total_net_minor,
        status="active",
    )
