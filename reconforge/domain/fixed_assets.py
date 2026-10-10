"""Exact, cumulative straight-line asset accounting; no independent ledger."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import TypedDict

from reconforge.domain.finance_posting import FinancePostingError, text

MAX_MINOR = 9_000_000_000_000_000_000


class AccountingLine(TypedDict):
    account_code: str
    debit_minor: int
    credit_minor: int


def exact_minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        raise FinancePostingError("asset_request_invalid", f"{field} requires bounded exact integer minor units.")
    return value


def cumulative_depreciation(cost: int, salvage: int, life: int, months: int) -> int:
    """Round the cumulative entitlement once, avoiding monthly rounding drift."""
    exact_minor(cost, "cost")
    exact_minor(salvage, "salvage", zero=True)
    if salvage >= cost or type(life) is not int or not 1 <= life <= 1200:
        raise FinancePostingError("asset_request_invalid", "Salvage must be below cost and life between 1 and 1200 months.")
    if type(months) is not int or not 0 <= months <= life:
        raise FinancePostingError("asset_request_invalid", "Depreciation months exceed the retained useful life.")
    return (2 * (cost - salvage) * months + life) // (2 * life)


def eligible_months(in_service_date: str, through_month: str, posting_date: str, life: int) -> int:
    try:
        start, posted = date.fromisoformat(in_service_date), date.fromisoformat(posting_date)
        through = date.fromisoformat(through_month + "-01")
        following = date(through.year + (through.month == 12), through.month % 12 + 1, 1)
    except (TypeError, ValueError) as exc:
        raise FinancePostingError("asset_date_invalid", "Use ISO dates and a YYYY-MM depreciation month.") from exc
    if posted < following:
        raise FinancePostingError("asset_date_invalid", "Depreciation posts after the completed service month.")
    months = (through.year - start.year) * 12 + through.month - start.month + 1
    if months <= 0:
        raise FinancePostingError("asset_date_invalid", "Depreciation cannot precede the service month.")
    return min(months, life)


@dataclass(frozen=True)
class AssetAcquisition:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    asset_number: str
    name: str
    journal_code: str
    period_id: str
    posting_date: str
    in_service_date: str
    cost_minor: int
    salvage_minor: int
    useful_life_months: int
    asset_account_code: str
    accumulated_account_code: str
    expense_account_code: str
    cash_account_code: str
    gain_account_code: str
    loss_account_code: str
    reason: str

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        for key, item in value.items():
            if key not in {"cost_minor", "salvage_minor", "useful_life_months"}:
                value[key] = text(item, key, maximum=500 if key == "reason" else 160)
        cumulative_depreciation(self.cost_minor, self.salvage_minor, self.useful_life_months, 0)
        try:
            if date.fromisoformat(self.in_service_date) < date.fromisoformat(self.posting_date):
                raise ValueError("service precedes acquisition")
        except ValueError as exc:
            raise FinancePostingError("asset_date_invalid", "Service date cannot precede acquisition.") from exc
        accounts = [value[key] for key in value if key.endswith("_account_code")]
        if len(accounts) != len(set(accounts)):
            raise FinancePostingError("asset_account_invalid", "Six distinct accounts are required for auditable asset accounting.")
        return value


def accounting_lines(asset: dict[str, object], kind: str, *, accumulated: int = 0,
                     depreciation: int = 0, proceeds: int = 0) -> list[AccountingLine]:
    cost = exact_minor(asset["cost_minor"], "cost")
    exact_minor(accumulated, "accumulated", zero=True)
    if accumulated > cost:
        raise FinancePostingError("asset_state_invalid", "Accumulated depreciation exceeds historical cost.")
    lines: list[AccountingLine] = []

    def add(account: str, debit: int = 0, credit: int = 0) -> None:
        if debit or credit:
            lines.append({"account_code": text(asset[account + "_account_code"], "account_code"), "debit_minor": debit, "credit_minor": credit})

    if kind == "acquire":
        add("asset", debit=cost)
        add("cash", credit=cost)
    elif kind == "depreciate":
        exact_minor(depreciation, "depreciation")
        if accumulated + depreciation > cost - exact_minor(asset["salvage_minor"], "salvage", zero=True):
            raise FinancePostingError("asset_state_invalid", "Depreciation exceeds the retained depreciable basis.")
        add("expense", debit=depreciation)
        add("accumulated", credit=depreciation)
    elif kind == "dispose":
        exact_minor(proceeds, "proceeds", zero=True)
        carrying = cost - accumulated
        add("cash", debit=proceeds)
        add("accumulated", debit=accumulated)
        add("loss", debit=max(carrying - proceeds, 0))
        add("asset", credit=cost)
        add("gain", credit=max(proceeds - carrying, 0))
    else:
        raise FinancePostingError("asset_request_invalid", "Unsupported asset accounting operation.")
    if sum(row["debit_minor"] for row in lines) > MAX_MINOR:
        raise FinancePostingError("asset_request_invalid", "Disposal turnover exceeds supported native GL bounds.")
    return lines
