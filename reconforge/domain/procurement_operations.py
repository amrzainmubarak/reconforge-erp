"""Exact stock procurement commands composed over existing governed engines."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.payables_quantities import exact_product
from reconforge.platform.inventory_values import code, document_number
from reconforge.utils.money import InvalidAmountError, parse_exact_amount

READ = frozenset({"payables.read", "inventory.read", "finance_core.read"})
MANAGE = frozenset({"payables.manage"})
APPROVE = frozenset({"payables.approve"})
STAGES = ("Draft", "Submitted", "Approved", "ReceiptPrepared", "ReceiptReviewed", "Received",
          "InvoiceMatched", "InvoiceApproved", "AccrualPrepared", "AccrualReviewed", "Accrued",
          "PaymentPrepared", "PaymentReviewed", "Paid")


class ProcurementError(FinancePostingError):
    """Safe business or command conflict."""


@dataclass(frozen=True, kw_only=True)
class ProcurementPreparation:
    number: str
    supplier_code: str
    item_code: str
    quantity: str
    unit_price_minor: int
    currency_code: str
    posting_date: str
    period_id: str
    location_code: str
    policy_code: str
    journal_code: str
    ap_account_code: str
    cash_account_code: str
    organization_code: str
    entity_code: str
    workspace: str = "default"


def line_total(quantity: str, price: int) -> tuple[str, int]:
    """Reject fractional minor-unit products instead of silently rounding costs."""
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        raise ProcurementError("procurement_amount_invalid", "Unit price must be positive integer minor units.")
    try:
        parsed = parse_exact_amount(quantity)
    except InvalidAmountError as exc:
        raise ProcurementError("procurement_quantity_invalid", "Quantity must be finite exact decimal text.") from exc
    if parsed <= 0:
        raise ProcurementError("procurement_quantity_invalid", "Quantity must be positive.")
    value = exact_product(parsed, Decimal(price))
    total = int(value)
    if value != total or not 0 < total <= 9_000_000_000_000_000_000:
        raise ProcurementError("procurement_amount_invalid", "Quantity times price must be exact supported minor units.")
    return format(parsed, "f"), total


def normalize(request: ProcurementPreparation) -> ProcurementPreparation:
    from dataclasses import replace

    from reconforge.domain.inventory_receipt_posting import exact_date, exact_text
    quantity, _ = line_total(request.quantity, request.unit_price_minor)
    if len(request.number) > 60:
        raise ProcurementError("procurement_number_invalid", "Procurement number supports at most 60 characters.")
    return replace(request, number=document_number(request.number, "Procurement number"),
        supplier_code=code(request.supplier_code, "Supplier"), item_code=code(request.item_code, "Item"),
        currency_code=code(request.currency_code, "Currency"), quantity=quantity,
        posting_date=exact_date(request.posting_date), period_id=exact_text(request.period_id),
        location_code=exact_text(request.location_code), policy_code=code(request.policy_code, "Policy"),
        journal_code=code(request.journal_code, "Journal"), ap_account_code=code(request.ap_account_code, "AP account"),
        cash_account_code=code(request.cash_account_code, "Cash account"),
        organization_code=code(request.organization_code, "Organization"), entity_code=code(request.entity_code, "Entity"),
        workspace=exact_text(request.workspace))
