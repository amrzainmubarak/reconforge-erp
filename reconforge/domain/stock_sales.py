"""Exact commercial orders and frozen FIFO issues for governed product sales."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.domain.inventory_costing import allocate_fifo_value
from reconforge.domain.sales_revenue import SalesLine

STOCK_STAGES = (
    "Draft", "Submitted", "Approved", "Reserved", "IssuePrepared", "IssueReviewed", "Delivered",
    "InvoicePrepared", "InvoiceReviewed", "Invoiced", "CollectionPrepared", "CollectionReviewed", "Paid",
)
STOCK_OPERATIONS = (
    "submit", "approve", "reserve", "prepare-issue", "review-issue", "deliver", "prepare-invoice",
    "review-invoice", "invoice", "prepare-collection", "review-collection", "collect",
)


def stock_code(value: object, label: str) -> str:
    result = text(value, label, maximum=64).upper()
    if len(result) > 64 or not result.isascii() or not result[0].isalnum() or any(not (c.isalnum() or c in "-_.") for c in result):
        raise FinancePostingError("stock_sales_code_invalid", f"{label} requires at most64 ASCII letters, digits, hyphen, underscore or dot.")
    return result


@dataclass(frozen=True)
class StockOrder:
    number: str
    customer_code: str
    customer_reference: str
    item_code: str
    warehouse_code: str
    location_code: str
    quantity: str
    unit_price_minor: int
    currency_code: str
    order_date: str
    description: str
    discount_basis_points: int = 0

    def payload(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("number", "customer_code", "item_code", "warehouse_code", "location_code"):
            result[key] = stock_code(result[key], key)
        result["customer_reference"] = text(self.customer_reference, "customer reference", maximum=160)
        priced = SalesLine(self.description, self.quantity, self.unit_price_minor, self.discount_basis_points).priced()
        result["quantity"] = priced["quantity"]
        result["description"] = priced["description"]
        if not isinstance(self.currency_code, str) or len(self.currency_code) != 3 or not self.currency_code.isascii() or not self.currency_code.isalpha():
            raise FinancePostingError("stock_sales_currency_invalid", "Currency requires a three-letter ISO code.")
        result["currency_code"] = self.currency_code.upper()
        try:
            if date.fromisoformat(self.order_date).isoformat() != self.order_date:
                raise ValueError("date")
        except (ValueError, TypeError) as exc:
            raise FinancePostingError("stock_sales_date_invalid", "Order date requires an ISO business date.") from exc
        return {"schema_version": "stock-sales-order-v1", **result, "net_unit_price_minor": priced["unit_price_minor"],
                "total_minor": priced["line_total_minor"], "tax_minor": 0,
                "discount_policy": "per-unit-minor-half-up-v1"}


@dataclass(frozen=True)
class StockIssuePreparation:
    posting_date: str
    period_id: str
    policy_code: str
    reason: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        result["period_id"] = text(self.period_id, "period", maximum=160)
        result["policy_code"] = stock_code(self.policy_code, "FIFO policy")
        result["reason"] = text(self.reason, "reason", maximum=500)
        try:
            if date.fromisoformat(self.posting_date).isoformat() != self.posting_date:
                raise ValueError("date")
        except (ValueError, TypeError) as exc:
            raise FinancePostingError("stock_sales_date_invalid", "Delivery date requires an ISO business date.") from exc
        return result


def freeze_fifo(layers: Sequence[Mapping[str, Any]], quantity_scaled: int) -> tuple[list[dict[str, Any]], int]:
    """Use the existing exact FIFO allocator; retain every selected residual."""
    if type(quantity_scaled) is not int or quantity_scaled <= 0:
        raise FinancePostingError("stock_sales_quantity_invalid", "Positive scaled quantity is required.")
    remaining, total = quantity_scaled, 0
    allocations: list[dict[str, Any]] = []
    for layer in layers:
        if not remaining:
            break
        available, value = layer["remaining_quantity_scaled"], layer["remaining_value_minor"]
        if type(available) is not int or type(value) is not int or available <= 0 or value <= 0:
            raise FinancePostingError("stock_sales_fifo_invalid", "FIFO residuals must be exact positive integers.")
        selected = min(available, remaining)
        cost = allocate_fifo_value(value, available, selected)
        if cost <= 0:
            raise FinancePostingError("stock_sales_fifo_invalid", "Issue quantity would consume a zero-value FIFO fraction.")
        allocations.append({"cost_layer_id": layer["id"], "row_version": layer["row_version"],
            "remaining_quantity_scaled": available, "remaining_value_minor": value,
            "quantity_scaled": selected, "value_minor": cost})
        total += cost
        remaining -= selected
    if remaining:
        raise FinancePostingError("stock_sales_fifo_shortfall", "Complete valued FIFO stock is required before issue preparation.")
    if total > 9_000_000_000_000_000_000:
        raise FinancePostingError("stock_sales_amount_invalid", "FIFO cost exceeds supported minor units.")
    return allocations, total


def stock_digest(payload: Mapping[str, Any]) -> str:
    return digest_payload(dict(payload))
