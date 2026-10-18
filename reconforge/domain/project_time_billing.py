"""Whole approved project time priced without approximate fractional hours."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any, NoReturn

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.domain.people_project_payroll import PeopleScope, TimeLine, business_date, integer
from reconforge.utils.money import CurrencyRegistryContext, Money

CONTRACT_VERSION = "project-time-billing-v1"
MAX_TIME_ENTRIES = 1000
MAX_PROJECTS = 999
MAX_NATIVE_LINE_MINOR = 4_500_000_000_000_000_000


def fail(message: str, code: str = "project_billing_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


def code(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", value) is None:
        fail(label + " must be canonical uppercase text.")
    return value


@dataclass(frozen=True)
class ProjectPriceAgreement:
    scope: PeopleScope
    customer_code: str
    project_id: str
    valid_from: str
    valid_through: str
    currency_code: str
    hourly_price_minor: int
    reason: str

    def __post_init__(self) -> None:
        code(self.customer_code, "Customer")
        if text(self.project_id, "Project") != self.project_id:
            fail("Project ID must be canonical.")
        if business_date(self.valid_from) > business_date(self.valid_through):
            fail("Price validity is reversed.")
        if not isinstance(self.currency_code, str) or re.fullmatch(r"[A-Z]{3}", self.currency_code) is None:
            fail("Explicit functional currency is required.")
        integer(self.hourly_price_minor, "Hourly service price", minimum=1, maximum=MAX_NATIVE_LINE_MINOR)
        text(self.reason, "Reason", maximum=500)

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        return {**value.pop("scope"), **value}


def allocate_bill(
    scope: PeopleScope,
    *,
    tenant_id: str,
    customer_code: str,
    currency_code: str,
    registry_context: CurrencyRegistryContext,
    approved_time: Sequence[Mapping[str, Any]],
    approved_prices: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Use captured currency Money rounding once per original Project.

    A native AR line uses quantity1 and this exact aggregate as unit_price.
    Every original time interval and agreement retains its independent source
    identity. Payroll claim state and employee pay rates are not consumed here.
    """
    text(tenant_id, "Tenant")
    code(customer_code, "Customer")
    if not isinstance(currency_code, str) or re.fullmatch(r"[A-Z]{3}", currency_code) is None:
        fail("Explicit functional currency is required.")
    if not 1 <= len(approved_time) <= MAX_TIME_ENTRIES or not 1 <= len(approved_prices) <= MAX_PROJECTS:
        fail("Use a bounded nonempty whole-time/project population.")
    qualified = {
        "tenant_id": tenant_id,
        **{name: getattr(scope, name) for name in ("workspace_id", "organization_id", "legal_entity_id")},
    }
    monetary_policy = {
        "currency_code": currency_code,
        **FinanceCurrencyPolicy.capture(currency_code, registry_context).metadata(),
    }
    prices: dict[str, list[Mapping[str, Any]]] = {}
    price_ids: set[str] = set()
    for price in approved_prices:
        identifier = text(price["id"], "Price agreement")
        if (
            identifier in price_ids
            or any(price[name] != expected for name, expected in qualified.items())
            or price["customer_code"] != customer_code
            or price["currency_code"] != currency_code
        ):
            fail("Duplicate or foreign price agreement.")
        if price["monetary_policy"] != monetary_policy:
            fail("Approved project price does not retain the captured native monetary policy.")
        if not price["approver_id"] or price["approver_id"] == price["preparer_id"]:
            fail("Price agreement requires an independent approval.")
        immutable = price["source_json"]
        if (
            not isinstance(immutable, dict)
            or price["source_digest"] != digest_payload(immutable)
            or any(
                immutable.get(name) != price[name]
                for name in (
                    *qualified,
                    "id",
                    "customer_code",
                    "project_id",
                    "valid_from",
                    "valid_through",
                    "currency_code",
                    "hourly_price_minor",
                    "preparer_id",
                    "dimension_id",
                    "value_id",
                    "monetary_policy",
                )
            )
        ):
            fail("Original approved price source seal differs.")
        text(price["dimension_id"], "Original Project dimension")
        text(price["value_id"], "Original Project value")
        price_ids.add(identifier)
        integer(price["hourly_price_minor"], "Hourly service price", minimum=1, maximum=MAX_NATIVE_LINE_MINOR)
        if business_date(price["valid_from"]) > business_date(price["valid_through"]):
            fail("Price validity is reversed.")
        prices.setdefault(text(price["project_id"], "Project"), []).append(price)
    starts: dict[str, list[str]] = {}
    for project, versions in prices.items():
        versions.sort(key=lambda price: price["valid_from"])
        if any(
            right["valid_from"] <= left["valid_through"] for left, right in zip(versions, versions[1:], strict=False)
        ):
            fail("Effective project price versions overlap.")
        starts[project] = [price["valid_from"] for price in versions]
    time_ids: set[str] = set()
    employee_days: set[tuple[str, str]] = set()
    sources: list[dict[str, Any]] = []
    amounts: dict[str, Fraction] = {}
    minutes: dict[str, int] = {}
    used_prices: set[str] = set()
    for time in sorted(approved_time, key=lambda row: row["id"]):
        identifier = text(time["id"], "Approved time")
        if identifier in time_ids or any(time[name] != expected for name, expected in qualified.items()):
            fail("Duplicate or foreign approved time.")
        if not time["approver_id"] or time["approver_id"] == time["submitter_id"]:
            fail("Independent original time approval is required.")
        day = business_date(time["business_date"])
        employee_day = (text(time["employee_id"], "Employee source"), day)
        if employee_day in employee_days:
            fail("Whole-time documents cannot duplicate one employee business date.")
        employee_days.add(employee_day)
        if time["source_digest"] != digest_payload({**time["request_json"], "employment_id": time["employment_id"]}):
            fail("Original approved time digest differs.")
        if any(time[name] != time["request_json"].get(name) for name in ("employee_id", "business_date", "lines")):
            fail("Approved time projection differs from its original immutable request.")
        time_ids.add(identifier)
        lines = time["lines"]
        if not isinstance(lines, list) or not 1 <= len(lines) <= 128:
            fail("Whole-time interval population is invalid.")
        previous_end = -1
        for row in sorted(lines, key=lambda value: value["start_minute"]):
            line = TimeLine(row["project_id"], row["start_minute"], row["end_minute"])
            if line.start_minute < previous_end:
                fail("Original time intervals overlap.")
            previous_end = line.end_minute
            position = bisect_right(starts.get(line.project_id, []), day) - 1
            if position < 0 or day > prices[line.project_id][position]["valid_through"]:
                fail("Each interval needs one approved effective project price.")
            price = prices[line.project_id][position]
            used_prices.add(price["id"])
            amount = Fraction(price["hourly_price_minor"] * line.minutes, 60)
            amounts[line.project_id] = amounts.get(line.project_id, Fraction()) + amount
            minutes[line.project_id] = minutes.get(line.project_id, 0) + line.minutes
            sources.append(
                {
                    "time_id": identifier,
                    "time_digest": time["source_digest"],
                    "project_id": line.project_id,
                    "start_minute": line.start_minute,
                    "end_minute": line.end_minute,
                    "minutes": line.minutes,
                    "price_id": price["id"],
                    "price_digest": price["source_digest"],
                    "hourly_price_minor": price["hourly_price_minor"],
                }
            )
    if used_prices != price_ids:
        fail("Do not add an unused price version to the original invoice source.")
    project_minor = {
        project: integer(
            Money.from_minor_units(amount.numerator, currency_code, registry_context=registry_context)
            .divide_exact(amount.denominator)
            .to_minor_units(),
            "Project service amount",
            minimum=1,
            maximum=MAX_NATIVE_LINE_MINOR,
        )
        for project, amount in sorted(amounts.items())
    }
    total = integer(sum(project_minor.values()), "Native receivable amount", minimum=1, maximum=MAX_NATIVE_LINE_MINOR)
    return {
        "contract_version": CONTRACT_VERSION,
        "rounding": "captured-currency-per-project-v1",
        "currency_code": currency_code,
        "monetary_policy": monetary_policy,
        "time_ids": sorted(time_ids),
        "price_ids": sorted(used_prices),
        "sources": sources,
        "project_minutes": dict(sorted(minutes.items())),
        "project_minor": project_minor,
        "amount_minor": total,
        "ar_lines": [
            {
                "project_id": project,
                "quantity": "1",
                "unit_price_minor": amount,
                "line_total_minor": amount,
                "tax_minor": 0,
            }
            for project, amount in project_minor.items()
        ],
    }


def collection_amount(total: int, posted_before: int, requested: int) -> dict[str, int]:
    integer(total, "Original receivable", minimum=1, maximum=MAX_NATIVE_LINE_MINOR)
    integer(posted_before, "Original posted collections", maximum=total)
    integer(requested, "Exact collection", minimum=1, maximum=MAX_NATIVE_LINE_MINOR)
    if requested > total - posted_before:
        fail("Customer cash collection exceeds original native AR outstanding.", "project_billing_overcollection")
    return {
        "amount_minor": requested,
        "collected_after_minor": posted_before + requested,
        "outstanding_after_minor": total - posted_before - requested,
    }
