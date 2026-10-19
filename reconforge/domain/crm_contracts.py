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


def suspend_contract(
    contract: CustomerContract,
    reason: str,
    actor_id: str,
) -> CustomerContract:
    """Suspends an active customer contract."""
    if contract.status != "active":
        raise FinancePostingError("crm_contract_not_active", f"Cannot suspend contract in status '{contract.status}'.")
    text(reason, "reason", maximum=500)
    text(actor_id, "actor_id")

    return CustomerContract(
        contract_id=contract.contract_id,
        quote_id=contract.quote_id,
        workspace_id=contract.workspace_id,
        organization_id=contract.organization_id,
        customer_id=contract.customer_id,
        currency=contract.currency,
        start_date=contract.start_date,
        end_date=contract.end_date,
        billing_frequency=contract.billing_frequency,
        total_contract_value_minor=contract.total_contract_value_minor,
        status="suspended",
    )


def resume_contract(
    contract: CustomerContract,
    actor_id: str,
) -> CustomerContract:
    """Resumes a suspended customer contract."""
    if contract.status != "suspended":
        raise FinancePostingError("crm_contract_not_suspended", f"Cannot resume contract in status '{contract.status}'.")
    text(actor_id, "actor_id")

    return CustomerContract(
        contract_id=contract.contract_id,
        quote_id=contract.quote_id,
        workspace_id=contract.workspace_id,
        organization_id=contract.organization_id,
        customer_id=contract.customer_id,
        currency=contract.currency,
        start_date=contract.start_date,
        end_date=contract.end_date,
        billing_frequency=contract.billing_frequency,
        total_contract_value_minor=contract.total_contract_value_minor,
        status="active",
    )


def terminate_contract(
    contract: CustomerContract,
    termination_date: str,
    early_termination_fee_minor: int,
    actor_id: str,
    approver_id: str,
) -> tuple[CustomerContract, int]:
    """Terminates a contract with maker-checker approval and early exit settlement fee."""
    if contract.status not in ("active", "suspended"):
        raise FinancePostingError("crm_contract_invalid_status", f"Cannot terminate contract in status '{contract.status}'.")

    # Strict Maker-Checker segregation
    clean_actor = text(actor_id, "actor_id")
    clean_approver = text(approver_id, "approver_id")
    if clean_actor == clean_approver:
        raise FinancePostingError("crm_sod_violation", "Contract termination requires independent maker-checker approval.")

    term_d = date.fromisoformat(termination_date)
    start_d = date.fromisoformat(contract.start_date)
    end_d = date.fromisoformat(contract.end_date)
    if term_d < start_d or term_d > end_d:
        raise FinancePostingError(
            "crm_contract_termination_date_invalid",
            f"Termination date {termination_date} must be within [{contract.start_date}, {contract.end_date}].",
        )

    fee = exact_minor(early_termination_fee_minor, "early_termination_fee_minor", zero=True)

    terminated = CustomerContract(
        contract_id=contract.contract_id,
        quote_id=contract.quote_id,
        workspace_id=contract.workspace_id,
        organization_id=contract.organization_id,
        customer_id=contract.customer_id,
        currency=contract.currency,
        start_date=contract.start_date,
        end_date=termination_date,
        billing_frequency=contract.billing_frequency,
        total_contract_value_minor=contract.total_contract_value_minor,
        status="terminated",
    )
    return terminated, fee


def renew_contract(
    contract: CustomerContract,
    new_end_date: str,
    price_adjustment_bps: int,
    approver_id: str,
) -> CustomerContract:
    """Renews a customer contract to a future end date with basis-point price adjustment."""
    if contract.status == "terminated":
        raise FinancePostingError("crm_contract_terminated", "Cannot renew a terminated contract.")

    text(approver_id, "approver_id")
    cur_end = date.fromisoformat(contract.end_date)
    new_end = date.fromisoformat(new_end_date)
    if new_end <= cur_end:
        raise FinancePostingError("crm_contract_date_invalid", f"New end date {new_end_date} must succeed current {contract.end_date}.")

    if not (-10_000 <= price_adjustment_bps <= 100_000):
        raise FinancePostingError("crm_bps_invalid", "Price adjustment bps must be between -10,000 and 100,000.")

    # Apply integer basis-point price adjustment with half-up rounding
    new_value = (contract.total_contract_value_minor * (BPS_DENOMINATOR + price_adjustment_bps) + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR

    return CustomerContract(
        contract_id=contract.contract_id,
        quote_id=contract.quote_id,
        workspace_id=contract.workspace_id,
        organization_id=contract.organization_id,
        customer_id=contract.customer_id,
        currency=contract.currency,
        start_date=contract.end_date,
        end_date=new_end_date,
        billing_frequency=contract.billing_frequency,
        total_contract_value_minor=new_value,
        status="active",
    )


SubscriptionStatus = Literal["active", "paused", "cancelled", "expired"]


@dataclass(frozen=True)
class SubscriptionPlan:
    """SaaS or service recurring subscription plan definition."""

    plan_id: str
    name: str
    currency: str
    billing_interval: BillingFrequency
    unit_price_minor: int

    def __post_init__(self) -> None:
        text(self.plan_id, "plan_id", maximum=64)
        text(self.name, "name", maximum=128)
        text(self.currency, "currency", maximum=3)
        exact_minor(self.unit_price_minor, "unit_price_minor", zero=True)


@dataclass(frozen=True)
class Subscription:
    """Active customer recurring subscription linked to a contract and plan."""

    subscription_id: str
    customer_id: str
    contract_id: str
    plan_id: str
    currency: str
    status: SubscriptionStatus
    current_period_start: str  # ISO date
    current_period_end: str    # ISO date
    auto_renew: bool = True

    def __post_init__(self) -> None:
        text(self.subscription_id, "subscription_id", maximum=64)
        text(self.customer_id, "customer_id", maximum=64)
        text(self.contract_id, "contract_id", maximum=64)
        text(self.plan_id, "plan_id", maximum=64)
        text(self.currency, "currency", maximum=3)
        sd = date.fromisoformat(self.current_period_start)
        ed = date.fromisoformat(self.current_period_end)
        if sd > ed:
            raise FinancePostingError("crm_subscription_date_invalid", "current_period_start cannot exceed current_period_end.")


def calculate_day_proration(amount_minor: int, total_period_days: int, active_days: int) -> int:
    """Calculate day-prorated minor amount with zero float and deterministic half-up rounding."""
    exact_minor(amount_minor, "amount_minor", zero=True)
    if total_period_days <= 0:
        raise FinancePostingError("crm_proration_invalid", "total_period_days must be positive.")
    if not (0 <= active_days <= total_period_days):
        raise FinancePostingError("crm_proration_invalid", f"active_days ({active_days}) must be between 0 and total_period_days ({total_period_days}).")
    if active_days == 0:
        return 0
    if active_days == total_period_days:
        return amount_minor
    return (amount_minor * active_days + (total_period_days // 2)) // total_period_days


def calculate_plan_change_proration(
    old_plan: SubscriptionPlan,
    new_plan: SubscriptionPlan,
    period_start: str,
    period_end: str,
    change_date: str,
) -> dict[str, int]:
    """Computes unearned credit of old plan, prorated charge of new plan, and net payable amount."""
    if old_plan.currency != new_plan.currency:
        raise FinancePostingError("crm_currency_mismatch", "Cannot prorate between plans with different currencies.")
    p_start = date.fromisoformat(period_start)
    p_end = date.fromisoformat(period_end)
    c_date = date.fromisoformat(change_date)
    if p_start > p_end:
        raise FinancePostingError("crm_date_invalid", "period_start cannot succeed period_end.")
    if not (p_start <= c_date <= p_end):
        raise FinancePostingError("crm_date_out_of_bounds", f"change_date {change_date} must be between {period_start} and {period_end}.")

    total_period_days = (p_end - p_start).days + 1
    # Remaining active days under the new plan (from change_date through period_end inclusive)
    remaining_days = (p_end - c_date).days + 1

    unearned_credit_minor = calculate_day_proration(old_plan.unit_price_minor, total_period_days, remaining_days)
    new_charge_minor = calculate_day_proration(new_plan.unit_price_minor, total_period_days, remaining_days)
    net_payable_minor = new_charge_minor - unearned_credit_minor

    return {
        "total_period_days": total_period_days,
        "remaining_days": remaining_days,
        "unearned_credit_minor": unearned_credit_minor,
        "new_charge_minor": new_charge_minor,
        "net_payable_minor": net_payable_minor,
    }


def cancel_subscription_with_refund(
    subscription: Subscription,
    plan: SubscriptionPlan,
    cancellation_date: str,
) -> tuple[Subscription, int]:
    """Cancels an active subscription and calculates unearned refundable credit with half-up rounding."""
    if subscription.status != "active":
        raise FinancePostingError("crm_subscription_not_active", f"Only active subscriptions can be cancelled; current: {subscription.status}")
    if subscription.plan_id != plan.plan_id:
        raise FinancePostingError("crm_plan_mismatch", "Subscription plan does not match provided plan.")

    p_start = date.fromisoformat(subscription.current_period_start)
    p_end = date.fromisoformat(subscription.current_period_end)
    c_date = date.fromisoformat(cancellation_date)
    if not (p_start <= c_date <= p_end):
        raise FinancePostingError("crm_date_out_of_bounds", f"cancellation_date {cancellation_date} must be within subscription period.")

    total_period_days = (p_end - p_start).days + 1
    # Remaining unused days from cancellation_date through period_end
    remaining_days = (p_end - c_date).days + 1
    refund_minor = calculate_day_proration(plan.unit_price_minor, total_period_days, remaining_days)

    cancelled_sub = Subscription(
        subscription_id=subscription.subscription_id,
        customer_id=subscription.customer_id,
        contract_id=subscription.contract_id,
        plan_id=subscription.plan_id,
        currency=subscription.currency,
        status="cancelled",
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        auto_renew=False,
    )
    return cancelled_sub, refund_minor

