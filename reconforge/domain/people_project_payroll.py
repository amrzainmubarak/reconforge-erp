"""Nonstatutory time earnings and source-owned wage accounting invariants."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from fractions import Fraction
from typing import Any, NoReturn

from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text

CONTRACT_VERSION = "people-project-payroll-v1"
MAX_MINOR = 9_000_000_000_000_000_000
MAX_TIME_ENTRIES = 1000
MAX_EMPLOYEES = 100


def fail(message: str, code: str = "people_payroll_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


def integer(value: object, label: str, *, minimum: int = 0, maximum: int = MAX_MINOR) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        fail(f"{label} requires a bounded exact integer.")
    return value


def minor_text(value: object, *, positive: bool = False) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
        fail("Money requires a canonical integer minor-unit string.")
    return integer(int(value), "Money", minimum=1 if positive else 0)


def business_date(value: object) -> str:
    if not isinstance(value, str):
        fail("Business date requires YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FinancePostingError("people_payroll_invalid", "Business date requires YYYY-MM-DD.") from exc
    if parsed.isoformat() != value:
        fail("Business date must be canonical.")
    return value


@dataclass(frozen=True)
class PeopleScope:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str

    def __post_init__(self) -> None:
        for field, value in asdict(self).items():
            if text(value, field) != value:
                fail("Scope text must be canonical.")


@dataclass(frozen=True)
class EmployeeRegistration:
    scope: PeopleScope
    employee_code: str
    display_name: str
    linked_user_id: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,63}", self.employee_code):
            fail("Employee code must be canonical uppercase text.")
        text(self.display_name, "Private employee name", maximum=160)
        if self.linked_user_id is not None:
            text(self.linked_user_id, "Linked existing user")


@dataclass(frozen=True)
class EmploymentAgreement:
    employee_id: str
    valid_from: str
    valid_through: str
    hourly_rate_minor: int
    currency_code: str
    reason: str

    def __post_init__(self) -> None:
        text(self.employee_id, "Employee")
        if business_date(self.valid_from) > business_date(self.valid_through):
            fail("Employment validity dates are reversed.")
        integer(self.hourly_rate_minor, "Hourly rate", minimum=1)
        if not re.fullmatch(r"[A-Z]{3}", self.currency_code):
            fail("Employment requires an explicit currency code.")
        text(self.reason, "Reason", maximum=500)


@dataclass(frozen=True)
class TimeLine:
    project_id: str
    start_minute: int
    end_minute: int

    def __post_init__(self) -> None:
        text(self.project_id, "Project")
        integer(self.start_minute, "UTC start minute", maximum=1439)
        integer(self.end_minute, "UTC end minute", minimum=1, maximum=1440)
        if self.start_minute >= self.end_minute:
            fail("Time interval must have positive exact minutes.")

    @property
    def minutes(self) -> int:
        return self.end_minute - self.start_minute


@dataclass(frozen=True)
class TimeSubmission:
    employee_id: str
    business_date: str
    lines: tuple[TimeLine, ...]
    reason: str

    def __post_init__(self) -> None:
        text(self.employee_id, "Employee")
        business_date(self.business_date)
        text(self.reason, "Reason", maximum=500)
        if not 1 <= len(self.lines) <= 128:
            fail("A day requires 1 to 128 bounded project intervals.")
        ordered = sorted(self.lines, key=lambda line: (line.start_minute, line.end_minute, line.project_id))
        if any(left.end_minute > right.start_minute for left, right in zip(ordered, ordered[1:], strict=False)):
            fail("Employee project intervals must not overlap.")


def half_even(value: Fraction) -> int:
    """Positive rational rounding without Decimal context or binary floats."""
    if type(value) is not Fraction:
        fail("Wage rounding requires an exact rational value.")
    if value < 0:
        fail("Wage entitlement cannot be negative.")
    whole, remainder = divmod(value.numerator, value.denominator)
    return whole + int(2 * remainder > value.denominator or 2 * remainder == value.denominator and whole % 2 == 1)


def earnings(approved: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Round employee totals HALF_EVEN; allocate cumulative project residuals."""
    if not 1 <= len(approved) <= MAX_TIME_ENTRIES:
        fail("Select 1 to 1000 whole approved time entries.")
    seen: set[str] = set()
    amounts: dict[str, dict[str, Fraction]] = {}
    time_ids: dict[str, list[str]] = {}
    for source in approved:
        identifier = text(source["id"], "Approved time entry")
        if identifier in seen:
            fail("Approved time entry cannot be selected twice.", "people_time_claim_conflict")
        seen.add(identifier)
        employee = text(source["employee_id"], "Employee")
        if source.get("status") != "Approved" or not source.get("approver_id") or not source.get("employment_id"):
            fail("Time requires retained independent approval and effective employment.")
        rate = integer(source["hourly_rate_minor"], "Captured hourly rate", minimum=1)
        lines = source["lines"]
        if not isinstance(lines, list) or not 1 <= len(lines) <= 128:
            fail("Approved project intervals are malformed.")
        intervals = tuple(TimeLine(line["project_id"], line["start_minute"], line["end_minute"]) for line in lines)
        TimeSubmission(employee, source["business_date"], intervals, "Captured approved time")
        per_project = amounts.setdefault(employee, {})
        time_ids.setdefault(employee, []).append(identifier)
        for line in intervals:
            per_project[line.project_id] = per_project.get(line.project_id, Fraction()) + Fraction(rate * line.minutes, 60)
    if len(amounts) > MAX_EMPLOYEES:
        fail("A payrun supports at most 100 employees.")
    employees: list[dict[str, Any]] = []
    aggregate: dict[str, int] = {}
    for employee in sorted(amounts):
        cumulative = Fraction()
        previous = 0
        projects: dict[str, int] = {}
        for project, amount in sorted(amounts[employee].items()):
            cumulative += amount
            rounded = half_even(cumulative)
            projects[project] = rounded - previous
            previous = rounded
            aggregate[project] = aggregate.get(project, 0) + projects[project]
        integer(previous, "Employee gross")
        employees.append({"employee_id": employee, "time_entry_ids": sorted(time_ids[employee]),
                          "gross_minor": previous, "project_minor": projects})
    total = integer(sum(item["gross_minor"] for item in employees), "Payrun gross", minimum=1)
    if total != sum(aggregate.values()):
        fail("Project cost does not conserve employee gross.")
    return {"contract_version": CONTRACT_VERSION, "earnings_rounding": "HALF_EVEN", "allocation": "canonical-project-cumulative-v1",
            "time_entry_ids": sorted(seen), "employees": employees, "project_minor": dict(sorted(aggregate.items())),
            "gross_minor": total}


def settlement(earned: Mapping[str, Any], paid: Mapping[str, int], requested: Mapping[str, int]) -> dict[str, Any]:
    if not isinstance(requested, Mapping) or not 1 <= len(requested) <= MAX_EMPLOYEES:
        fail("A settlement requires bounded employee allocations.")
    balances = {item["employee_id"]: integer(item["gross_minor"], "Original employee gross") for item in earned["employees"]}
    for employee, amount in paid.items():
        if employee not in balances or integer(amount, "Previously settled amount") > balances[employee]:
            fail("Retained employee settlement exceeds original accrual.")
        balances[employee] -= amount
    result: dict[str, int] = {}
    for employee, amount in sorted(requested.items()):
        amount = integer(amount, "Settlement allocation", minimum=1)
        if employee not in balances or amount > balances[employee]:
            fail("Settlement exceeds current employee payable.", "people_payment_conflict")
        result[employee] = amount
    return {"employees_minor": result, "amount_minor": integer(sum(result.values()), "Payment total", minimum=1)}


def source_digest(value: Mapping[str, Any]) -> str:
    return digest_payload(dict(value))
