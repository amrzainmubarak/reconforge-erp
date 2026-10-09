"""Conserved multi-line commercial orders using the existing stock-sale owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.stock_sales import StockOrder, stock_code


@dataclass(frozen=True)
class CommercialLine:
    item_code: str
    warehouse_code: str
    location_code: str
    quantity: str
    unit_price_minor: int
    description: str
    discount_basis_points: int = 0


@dataclass(frozen=True)
class CommercialOrder:
    number: str
    customer_code: str
    customer_reference: str
    currency_code: str
    order_date: str
    lines: tuple[CommercialLine, ...]

    def payload(self) -> dict[str, Any]:
        if not 1 <= len(self.lines) <= 1000:
            raise FinancePostingError("commerce_lines_invalid", "A commercial order requires 1 to 1000 explicit lines.")
        number = stock_code(self.number, "commercial order")
        reference = text(self.customer_reference, "customer reference", maximum=160)
        lines = [StockOrder(number, self.customer_code, reference, line.item_code, line.warehouse_code,
            line.location_code, line.quantity, line.unit_price_minor, self.currency_code,
            self.order_date, line.description, line.discount_basis_points).payload() for line in self.lines]
        total = sum(line["total_minor"] for line in lines)
        if total > 9_000_000_000_000_000_000:
            raise FinancePostingError("commerce_amount_invalid", "Aggregate commercial value exceeds exact minor units.")
        return {"header": {"schema_version": "stock-commerce-v1", "number": number,
            "customer_code": lines[0]["customer_code"], "customer_reference": reference,
            "currency_code": lines[0]["currency_code"], "order_date": self.order_date,
            "line_count": len(lines), "total_minor": total}, "lines": lines}
