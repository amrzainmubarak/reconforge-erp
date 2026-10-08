"""Classified financial statements over the existing verified posting balance port."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, NoReturn

from reconforge.domain.finance_balances import business_date, verify_posted_balances
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text

REPORTING_CONTRACT = "financial-reporting-v1"
MAX_REPORT_ACCOUNTS = 1000
MAX_OPENING_LINES = 64
MAX_MINOR = 9_000_000_000_000_000_000
SECTIONS = {
    "CurrentAsset": "Asset",
    "NonCurrentAsset": "Asset",
    "CurrentLiability": "Liability",
    "NonCurrentLiability": "Liability",
    "Equity": "Equity",
    "Income": "Income",
    "Expense": "Expense",
}


def fail(message: str, code: str = "financial_reporting_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


def exact_minor(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_MINOR:
        fail("Financial reporting requires bounded integer minor units.")
    return value


@dataclass(frozen=True)
class ReportingScope:
    workspace_id: str
    organization_id: str
    legal_entity_id: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        if any(text(value, key) != value for key, value in result.items()):
            fail("Reporting scope requires canonical identifiers.")
        return result


@dataclass(frozen=True)
class AccountClassification:
    account_code: str
    section: str
    is_cash: bool = False

    def payload(self) -> dict[str, Any]:
        if text(self.account_code, "account_code", maximum=64) != self.account_code or self.section not in SECTIONS:
            fail("Each account requires an explicit supported statement section.")
        if type(self.is_cash) is not bool or (self.is_cash and self.section != "CurrentAsset"):
            fail("Cash must be explicitly designated within current assets.")
        return asdict(self)


@dataclass(frozen=True)
class OpeningLine:
    account_code: str
    debit_minor: int
    credit_minor: int

    def payload(self) -> dict[str, Any]:
        if text(self.account_code, "account_code", maximum=64) != self.account_code:
            fail("Opening accounts require canonical codes.")
        debit, credit = exact_minor(self.debit_minor), exact_minor(self.credit_minor)
        if (debit == 0) == (credit == 0):
            fail("Each opening line requires exactly one positive debit or credit.")
        return asdict(self)


@dataclass(frozen=True)
class OpeningPreparation:
    scope: ReportingScope
    map_id: str
    organization_code: str
    entity_code: str
    period_id: str
    journal_code: str
    posting_date: str
    reason: str
    lines: tuple[OpeningLine, ...]

    def payload(self) -> dict[str, Any]:
        values = {
            key: getattr(self, key)
            for key in (
                "map_id",
                "organization_code",
                "entity_code",
                "period_id",
                "journal_code",
                "posting_date",
                "reason",
            )
        }
        for key, value in values.items():
            if text(value, key, maximum=500 if key == "reason" else 160) != value:
                fail("Opening arguments require canonical text.")
        business_date(self.posting_date)
        lines = [line.payload() for line in self.lines]
        if not 2 <= len(lines) <= MAX_OPENING_LINES or len({line["account_code"] for line in lines}) != len(lines):
            fail("Opening requires two to sixty-four distinct accounts.")
        debit, credit = (sum(line[key] for line in lines) for key in ("debit_minor", "credit_minor"))
        if debit != credit or not 0 < debit <= MAX_MINOR:
            fail("Opening balances must balance exactly within the money limit.")
        return {**self.scope.payload(), **values, "lines": sorted(lines, key=lambda line: line["account_code"])}


def validate_mapping_accounts(accounts: Sequence[Mapping[str, Any]]) -> None:
    if not 1 <= len(accounts) <= MAX_REPORT_ACCOUNTS:
        fail("A reporting map requires a bounded explicit account set.")
    seen: set[str] = set()
    for account in accounts:
        fields = {"account_id", "account_code", "account_name", "account_type", "normal_balance", "section", "is_cash"}
        if set(account) != fields or account["account_id"] in seen:
            fail("Reporting accounts must be unique and use the closed mapping contract.")
        seen.add(text(account["account_id"], "account_id"))
        AccountClassification(account["account_code"], account["section"], account["is_cash"]).payload()
        if account["account_type"] != SECTIONS[account["section"]] or account["normal_balance"] not in {
            "Debit",
            "Credit",
        }:
            fail("Statement sections must agree with captured native account semantics.")
        text(account["account_name"], "account_name", maximum=240)


def build_financial_report(balances: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Retain every posted contribution; never add drafts or infer missing accounts."""
    verify_posted_balances(balances)
    validate_mapping_accounts(mapping["accounts"])
    for key in ("workspace_id", "organization_id", "legal_entity_id"):
        if balances[key] != mapping[key]:
            fail("Reporting map and posted balances belong to different scope.", "financial_reporting_scope_denied")
    classified = {row["account_id"]: row for row in mapping["accounts"]}
    sections = {key: {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0} for key in SECTIONS}
    cash: dict[str, Any] = {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0}
    movements: dict[str, dict[str, Any]] = {}
    trial: list[dict[str, Any]] = []
    for account in balances["accounts"]:
        if account["account_id"] not in classified:
            fail(
                "Every contributing posted account must have an explicit reviewed classification.",
                "financial_reporting_unmapped",
            )
        master = classified[account["account_id"]]
        sign = 1 if master["account_type"] in {"Asset", "Expense"} else -1
        for phase in ("opening", "activity", "closing"):
            sections[master["section"]][phase + "_minor"] += sign * account[phase]["balance_minor"]
            if master["is_cash"]:
                cash[phase + "_minor"] += account[phase]["balance_minor"]
        trial.append({**master, **account})
        for line in account["postings"]:
            if line["phase"] != "activity":
                continue
            movement = movements.setdefault(
                line["effect_id"],
                {
                    "effect_id": line["effect_id"],
                    "entry_id": line["entry_id"],
                    "posting_date": line["posting_date"],
                    "cash_delta_minor": 0,
                    "cash_lines": [],
                    "counterpart_lines": [],
                },
            )
            retained = {"account_id": account["account_id"], "account_code": master["account_code"], **line}
            if master["is_cash"]:
                movement["cash_delta_minor"] += line["debit_minor"] - line["credit_minor"]
                movement["cash_lines"].append(retained)
            else:
                movement["counterpart_lines"].append(retained)
    income = sections["Income"]["activity_minor"]
    expense = sections["Expense"]["activity_minor"]
    cumulative_result = sections["Income"]["closing_minor"] - sections["Expense"]["closing_minor"]
    assets = sections["CurrentAsset"]["closing_minor"] + sections["NonCurrentAsset"]["closing_minor"]
    liabilities = sections["CurrentLiability"]["closing_minor"] + sections["NonCurrentLiability"]["closing_minor"]
    equity = sections["Equity"]["closing_minor"]
    cash_rows = []
    for row in sorted(movements.values(), key=lambda row: (row["posting_date"], row["effect_id"])):
        if not row["cash_lines"]:
            continue
        row["movement_kind"] = (
            "InternalTransfer"
            if not row["counterpart_lines"]
            else "Inflow"
            if row["cash_delta_minor"] > 0
            else "Outflow"
            if row["cash_delta_minor"] < 0
            else "ZeroNet"
        )
        row["cash_lines"].sort(key=lambda line: line["line_number"])
        row["counterpart_lines"].sort(key=lambda line: line["line_number"])
        cash_rows.append(row)
    cash.update(
        {
            "inflow_minor": sum(max(row["cash_delta_minor"], 0) for row in cash_rows),
            "outflow_minor": sum(max(-row["cash_delta_minor"], 0) for row in cash_rows),
            "movements": cash_rows,
        }
    )
    if (
        assets != liabilities + equity + cumulative_result
        or sum(row["cash_delta_minor"] for row in cash_rows) != cash["activity_minor"]
    ):
        fail(
            "Financial statement equations disagree with verified posting evidence.",
            "financial_reporting_integrity_invalid",
        )
    payload = {
        "contract_version": REPORTING_CONTRACT,
        "balance_scope": balances["balance_scope"],
        **{
            key: balances[key]
            for key in (
                "workspace_id",
                "organization_id",
                "legal_entity_id",
                "organization_code",
                "entity_code",
                "period_id",
                "period_start",
                "period_end",
                "as_of_date",
            )
        },
        "map_id": mapping["id"],
        "map_digest": mapping["map_digest"],
        "balances_digest": balances["report_digest"],
        "currency_policy": balances["currency_policy"],
        "effect_count": balances["totals"]["closing"]["effect_count"],
        "trial_balance": {"accounts": trial, "totals": balances["totals"]},
        "sections": sections,
        "balance_sheet": {
            "assets_minor": assets,
            "liabilities_minor": liabilities,
            "equity_minor": equity,
            "accumulated_unclosed_result_minor": cumulative_result,
            "balanced": True,
        },
        "income_statement": {"income_minor": income, "expense_minor": expense, "result_minor": income - expense},
        "cash_movements": cash,
    }
    return {**payload, "report_digest": digest_payload(payload)}
