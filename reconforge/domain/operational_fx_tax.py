"""Historical foreign receivables composed over canonical Money and ExchangeRate."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, NoReturn

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.utils.money import CurrencyRegistryContext, ExchangeRate, Money

MAX_MINOR = 9_000_000_000_000_000_000
MAX_SETTLEMENTS = 200
MAX_TAX_COMPONENTS = 8


def fail(message: str, code: str = "fx_request_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


def exact_minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        fail(f"{field} requires bounded exact integer minor units.")
    return value


def canonical_day(value: object, field: str) -> str:
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("noncanonical date")
    except (TypeError, ValueError) as exc:
        raise FinancePostingError("fx_date_invalid", f"{field} requires an exact ISO business date.") from exc
    return value


def exact_rate(value: object, *, tax: bool = False) -> Decimal:
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?", value) is None:
        fail("Rates require bounded positive decimal text, without exponents or binary floating point.")
    parsed = Decimal(value)
    if not (Decimal("0") <= parsed <= Decimal("1") if tax else parsed > 0):
        fail("Tax fractions must be between zero and one; exchange rates must be positive.")
    return parsed


@dataclass(frozen=True)
class HistoricalRate:
    rate: str
    source: str
    effective_at: str

    def payload(self, day: str) -> dict[str, str]:
        exact_rate(self.rate)
        if text(self.source, "rate source", maximum=200) != self.source:
            fail("Rate source must be canonical provenance text.")
        try:
            moment = datetime.fromisoformat(self.effective_at.replace("Z", "+00:00"))
            if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", self.effective_at)
                    or moment.tzinfo != UTC or moment.date().isoformat() != canonical_day(day, "rate date")):
                raise ValueError("Rate must be an explicit UTC spot observation on the transaction date")
        except (AttributeError, TypeError, ValueError) as exc:
            raise FinancePostingError("fx_date_invalid", "Retain an explicit UTC spot timestamp on the posting date.") from exc
        return asdict(self)

    def resolve(self, foreign: str, functional: str, context: CurrencyRegistryContext, day: str) -> ExchangeRate:
        self.payload(day)
        if foreign == functional:
            fail("This source requires distinct foreign and functional currencies.")
        return ExchangeRate(foreign, functional, exact_rate(self.rate), self.source, self.effective_at,
                            registry_context=context)


@dataclass(frozen=True)
class TaxComponent:
    policy_id: str
    country_code: str
    transaction_class: str
    effective_from: str
    effective_to: str
    rate: str
    account_code: str
    source: str
    version: str = "1"

    def payload(self, *, day: str, country: str, transaction_class: str) -> dict[str, str]:
        for key, value in asdict(self).items():
            if text(value, key, maximum=200) != value:
                fail("Tax policy fields require canonical provenance text.")
        exact_rate(self.rate, tax=True)
        start, end = canonical_day(self.effective_from, "tax effective_from"), canonical_day(self.effective_to, "tax effective_to")
        if (self.country_code != country or self.transaction_class != transaction_class
                or not start <= canonical_day(day, "tax date") <= end):
            fail("Tax policy country, transaction class and effective period must match the original invoice.", "fx_tax_policy_invalid")
        values = asdict(self)
        return {**values, "policy_digest": digest_payload(values)}


@dataclass(frozen=True)
class ForeignInvoicePreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    customer_code: str
    invoice_number: str
    posting_date: str
    due_date: str
    period_id: str
    journal_code: str
    foreign_currency_code: str
    net_minor: int
    original_rate: HistoricalRate
    country_code: str
    transaction_class: str
    taxes: tuple[TaxComponent, ...]
    receivable_account_code: str
    revenue_account_code: str
    cash_account_code: str
    gain_account_code: str
    loss_account_code: str
    reason: str

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in data.items():
            if key not in {"net_minor", "original_rate", "taxes"} and text(value, key, maximum=500 if key == "reason" else 160) != value:
                fail("Invoice fields must be canonical printable text.")
        exact_minor(self.net_minor, "net_minor")
        day = canonical_day(self.posting_date, "posting_date")
        if canonical_day(self.due_date, "due_date") < day:
            fail("Invoice due date cannot precede its recognition date.", "fx_date_invalid")
        if re.fullmatch(r"[A-Z]{2}", self.country_code) is None or re.fullmatch(r"[A-Z]{3}", self.foreign_currency_code) is None:
            fail("Country and currency require explicit uppercase ISO-style codes.")
        if type(self.taxes) is not tuple or len(self.taxes) > MAX_TAX_COMPONENTS:
            fail("Use at most eight ordered net-exclusive tax components.")
        data["original_rate"] = self.original_rate.payload(day)
        data["taxes"] = [component.payload(day=day, country=self.country_code, transaction_class=self.transaction_class) for component in self.taxes]
        if len({component.policy_id for component in self.taxes}) != len(self.taxes):
            fail("Retained tax component policy identities must be distinct.")
        for key in ("organization_code", "entity_code", "customer_code", "invoice_number", "journal_code",
                    "receivable_account_code", "revenue_account_code", "cash_account_code", "gain_account_code", "loss_account_code"):
            value = data[key]
            if len(value) > (60 if key == "invoice_number" else 64) or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*", value) is None:
                fail("Native document and account codes require bounded uppercase canonical identifiers.")
        if any(re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", component.account_code) is None for component in self.taxes):
            fail("Tax liability account codes require bounded uppercase canonical identifiers.")
        accounts = [data[key] for key in data if key.endswith("_account_code")]
        if len(set(accounts)) != len(accounts) or any(t.account_code in accounts for t in self.taxes):
            fail("AR, revenue, cash, gain, loss and tax liability account roles must be distinct.", "fx_account_invalid")
        return data


def policy(context: CurrencyRegistryContext, currency: str) -> dict[str, Any]:
    value = FinanceCurrencyPolicy.capture(currency, context)
    return {"currency_code": currency, **value.metadata()}


def convert_minor(amount: int, exchange: ExchangeRate, context: CurrencyRegistryContext) -> int:
    exact_minor(amount, "conversion source", zero=True)
    converted = exchange.convert(Money.from_minor_units(amount, exchange.base_currency, registry_context=context)).to_minor_units()
    return exact_minor(converted, "functional conversion", zero=True)


def invoice_equation(request: ForeignInvoicePreparation, functional: str, context: CurrencyRegistryContext) -> dict[str, Any]:
    args = request.payload()
    exchange = request.original_rate.resolve(request.foreign_currency_code, functional, context, request.posting_date)
    net = Money.from_minor_units(request.net_minor, request.foreign_currency_code, registry_context=context)
    functional_net = convert_minor(request.net_minor, exchange, context)
    exact_minor(functional_net, "functional net")
    components = []
    foreign_prefix, functional_prefix = request.net_minor, functional_net
    for component in request.taxes:
        foreign_tax = net.multiply_exact(exact_rate(component.rate, tax=True)).to_minor_units()
        foreign_prefix = exact_minor(foreign_prefix + foreign_tax, "foreign gross")
        converted_prefix = convert_minor(foreign_prefix, exchange, context)
        components.append({**component.payload(day=request.posting_date, country=request.country_code, transaction_class=request.transaction_class),
                           "foreign_tax_minor": foreign_tax, "functional_tax_minor": converted_prefix - functional_prefix})
        functional_prefix = converted_prefix
    exact_minor(functional_prefix, "functional gross")
    lines = [{"account_code": request.receivable_account_code, "debit_minor": functional_prefix, "credit_minor": 0},
             {"account_code": request.revenue_account_code, "debit_minor": 0, "credit_minor": functional_net}]
    lines.extend({"account_code": component["account_code"], "debit_minor": 0, "credit_minor": component["functional_tax_minor"]}
                 for component in components if component["functional_tax_minor"])
    return {"request": args, "foreign_policy": policy(context, request.foreign_currency_code),
            "functional_policy": policy(context, functional), "foreign_net_minor": request.net_minor,
            "foreign_tax_minor": foreign_prefix - request.net_minor, "foreign_gross_minor": foreign_prefix,
            "functional_net_minor": functional_net, "functional_gross_minor": functional_prefix,
            "tax_components": components, "functional_allocation_policy": "converted-cumulative-prefix-v1", "lines": lines}


def settlement_equation(source: dict[str, Any], *, foreign_minor: int, foreign_before_minor: int,
                        historical_before_minor: int, settlement_rate: HistoricalRate,
                        posting_date: str, context: CurrencyRegistryContext) -> dict[str, Any]:
    amount = exact_minor(foreign_minor, "foreign settlement")
    before = exact_minor(foreign_before_minor, "foreign paid before", zero=True)
    historical = exact_minor(historical_before_minor, "historical release before", zero=True)
    request = source["request"]
    foreign, functional = source["foreign_policy"]["currency_code"], source["functional_policy"]["currency_code"]
    original = HistoricalRate(**request["original_rate"]).resolve(foreign, functional, context, request["posting_date"])
    current = settlement_rate.resolve(foreign, functional, context, posting_date)
    if posting_date < request["posting_date"] or before + amount > source["foreign_gross_minor"]:
        fail("Settlement cannot precede recognition or exceed its exact foreign residual.", "fx_state_invalid")
    if convert_minor(before, original, context) != historical:
        fail("Retained historical release does not match the original cumulative rate.", "fx_state_invalid")
    released = convert_minor(before + amount, original, context) - historical
    cash = exact_minor(convert_minor(amount, current, context), "functional cash")
    difference = cash - released
    lines = [{"account_code": request["cash_account_code"], "debit_minor": cash, "credit_minor": 0}]
    if released:
        lines.append({"account_code": request["receivable_account_code"], "debit_minor": 0, "credit_minor": released})
    if difference:
        lines.append({"account_code": request["gain_account_code"] if difference > 0 else request["loss_account_code"],
                      "debit_minor": max(-difference, 0), "credit_minor": max(difference, 0)})
    turnover = sum(line["debit_minor"] for line in lines)
    exact_minor(turnover, "settlement turnover")
    return {"foreign_minor": amount, "foreign_before_minor": before, "foreign_after_minor": before + amount,
            "historical_before_minor": historical, "historical_release_minor": released,
            "historical_after_minor": historical + released, "functional_cash_minor": cash,
            "realized_fx_minor": difference, "settlement_rate": settlement_rate.payload(posting_date),
            "amount_minor": turnover, "lines": lines}
