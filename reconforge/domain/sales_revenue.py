"""Exact quotations and explicit transitions for governed service revenue."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.domain.quantities import quantity_decimal_text, quantity_product_minor

MAX_MINOR = 9_223_372_036_854_775_807
SALES_PERMISSIONS = frozenset({"sales.read", "sales.manage", "sales.approve"})


@dataclass(frozen=True)
class SalesLine:
    """A fulfilled service line; stock items require a separate stock owner."""

    description: str
    quantity: str
    unit_price_minor: int
    discount_basis_points: int = 0

    def priced(self) -> dict[str, Any]:
        description = text(self.description, "description", maximum=500)
        if type(self.unit_price_minor) is not int or not 1 <= self.unit_price_minor <= MAX_MINOR:
            raise FinancePostingError("sales_amount_invalid", "Unit price requires positive exact minor units.")
        if type(self.discount_basis_points) is not int or not 0 <= self.discount_basis_points < 10000:
            raise FinancePostingError("sales_discount_invalid", "Discount must be integer basis points below 10000.")
        if not isinstance(self.quantity, str) or len(self.quantity) > 64 or "e" in self.quantity.lower():
            raise FinancePostingError("sales_quantity_invalid", "Service quantity requires bounded exact decimal text.")
        try:
            quantity = Decimal(self.quantity)
            canonical = quantity_decimal_text(quantity)
            if quantity <= 0:
                raise ValueError("nonpositive")
            # Explicit per-unit HALF_UP policy, reproducible without Decimal context.
            net_unit = (self.unit_price_minor * (10000 - self.discount_basis_points) + 5000) // 10000
            total = quantity_product_minor(quantity, net_unit)
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise FinancePostingError(
                "sales_quantity_invalid", "Service quantity is outside supported exact precision."
            ) from exc
        if not 0 < total <= MAX_MINOR or net_unit == 0:
            raise FinancePostingError("sales_amount_invalid", "Discounted line must have a positive bounded total.")
        return {
            "description": description,
            "quantity": canonical,
            "gross_unit_price_minor": self.unit_price_minor,
            "discount_basis_points": self.discount_basis_points,
            "unit_price_minor": net_unit,
            "line_total_minor": total,
            "tax_minor": 0,
        }


@dataclass(frozen=True)
class SalesQuotation:
    number: str
    customer_code: str
    business_date: str
    valid_until: str
    currency_code: str
    lines: tuple[SalesLine, ...]

    def snapshot(self) -> dict[str, Any]:
        number = text(self.number, "quotation number", maximum=64)
        customer = text(self.customer_code, "customer code", maximum=64).upper()
        try:
            day, expiry = date.fromisoformat(self.business_date), date.fromisoformat(self.valid_until)
        except (ValueError, TypeError) as exc:
            raise FinancePostingError("sales_date_invalid", "Dates require ISO business dates.") from exc
        if day.isoformat() != self.business_date or expiry.isoformat() != self.valid_until or expiry < day:
            raise FinancePostingError("sales_date_invalid", "Quotation validity cannot end before its date.")
        if (
            not isinstance(self.currency_code, str)
            or len(self.currency_code) != 3
            or not self.currency_code.isascii()
            or not self.currency_code.isalpha()
        ):
            raise FinancePostingError("sales_currency_invalid", "Currency requires an ISO three-letter code.")
        if not 1 <= len(self.lines) <= 16:
            raise FinancePostingError("sales_lines_invalid", "Quotation requires between one and 16 service lines.")
        lines = [line.priced() for line in self.lines]
        total = sum(line["line_total_minor"] for line in lines)
        if total > MAX_MINOR:
            raise FinancePostingError("sales_amount_invalid", "Quotation total exceeds supported minor units.")
        result = {
            "schema_version": "sales-service-revenue-v1",
            "fulfillment_kind": "Service",
            "discount_policy": "per-unit-minor-half-up-v1",
            "number": number,
            "customer_code": customer,
            "business_date": day.isoformat(),
            "valid_until": expiry.isoformat(),
            "currency_code": self.currency_code.upper(),
            "lines": lines,
            "total_minor": total,
            "tax_minor": 0,
        }
        return {**result, "digest": digest_payload(result)}


@dataclass(frozen=True)
class SalesInvoicePreparation:
    invoice_number: str
    invoice_date: str
    due_date: str
    journal_code: str
    period_id: str
    receivable_account_code: str
    revenue_account_code: str
    reason: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        for key, value in result.items():
            result[key] = text(value, key, maximum=500 if key == "reason" else 160)
        for key in ("invoice_date", "due_date"):
            try:
                if date.fromisoformat(result[key]).isoformat() != result[key]:
                    raise ValueError("date")
            except ValueError as exc:
                raise FinancePostingError("sales_date_invalid", "Invoice dates require ISO business dates.") from exc
        if result["due_date"] < result["invoice_date"]:
            raise FinancePostingError("sales_date_invalid", "Due date cannot precede invoice date.")
        return result
