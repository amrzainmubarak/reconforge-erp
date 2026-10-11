"""Exact paired service charges and explicit native group adjustments.

This first contract uses one retained functional/reporting currency. Group
participation is explicitly configured; it is not inferred legal ownership.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, NoReturn

from reconforge.domain.finance_balances import business_date
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.platform.inventory_values import code

MAX_SETTLEMENTS = 32
MAX_MINOR = 4_500_000_000_000_000_000
Kind = Literal["recognize", "settle", "eliminate"]


def fail(message: str, error: str = "intercompany_request_invalid") -> NoReturn:
    raise FinancePostingError(error, message)


def minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        fail(f"{field} requires bounded exact integer minor units.")
    return value


@dataclass(frozen=True)
class IntercompanyPreparation:
    workspace_id: str
    organization_id: str
    organization_code: str
    seller_entity_id: str
    seller_entity_code: str
    buyer_entity_id: str
    buyer_entity_code: str
    adjustment_entity_id: str
    adjustment_entity_code: str
    reference: str
    amount_minor: int
    period_id: str
    posting_date: str
    journal_code: str
    receivable_account_code: str
    payable_account_code: str
    revenue_account_code: str
    expense_account_code: str
    cash_account_code: str
    reason: str

    def payload(self) -> dict[str, Any]:
        result = asdict(self)
        for field, value in result.items():
            if field == "amount_minor":
                result[field] = minor(value, field)
            elif field == "posting_date":
                result[field] = business_date(value)
            elif field.endswith("_code"):
                result[field] = code(value, field)
            else:
                result[field] = text(value, field, maximum=500 if field == "reason" else 160)
            if result[field] != value:
                fail("Intercompany input must retain canonical values.")
        if len({self.seller_entity_id, self.buyer_entity_id, self.adjustment_entity_id}) != 3:
            fail("Two trading entities and a distinct explicit group-adjustment scope are required.")
        if len({self.seller_entity_code, self.buyer_entity_code, self.adjustment_entity_code}) != 3:
            fail("Three distinct entity codes are required.")
        accounts = [result[key] for key in result if key.endswith("_account_code")]
        if len(set(accounts)) != 5:
            fail("Cash, receivable, payable, revenue and expense accounts must be distinct.")
        return result


def equation(request: Mapping[str, Any], kind: Kind, *, settled_before_minor: int = 0,
             settlement_minor: int = 0) -> dict[str, Any]:
    """Pure integer equations, independently repeated by the SQL owner guard."""
    gross = minor(request["amount_minor"], "original service charge")
    before = minor(settled_before_minor, "settled amount", zero=True)
    if before > gross:
        fail("Settlements cannot exceed the original paired charge.")
    ar, ap, revenue, expense, cash = (request[key + "_account_code"]
        for key in ("receivable", "payable", "revenue", "expense", "cash"))

    def line(account: str, debit: int, credit: int) -> dict[str, Any]:
        return {"account_code": account, "debit_minor": debit, "credit_minor": credit}

    if kind == "recognize":
        if before or settlement_minor:
            fail("Original recognition cannot include prior settlements.")
        books = {"seller": [line(ar, gross, 0), line(revenue, 0, gross)],
                 "buyer": [line(expense, gross, 0), line(ap, 0, gross)]}
    elif kind == "settle":
        paid = minor(settlement_minor, "cash settlement")
        if before + paid > gross:
            fail("Partial cash settlement exceeds the exact remaining paired balance.")
        books = {"seller": [line(cash, paid, 0), line(ar, 0, paid)],
                 "buyer": [line(ap, paid, 0), line(cash, 0, paid)]}
    elif kind == "eliminate":
        if settlement_minor:
            fail("Group elimination does not transfer cash.")
        lines = [line(revenue, gross, 0), line(expense, 0, gross)]
        if gross > before:
            lines.extend([line(ap, gross - before, 0), line(ar, 0, gross - before)])
        books = {"adjustment": lines}
    else:
        fail("Intercompany operation kind is unsupported.")
    burden = max(sum(row["debit_minor"] for row in rows) for rows in books.values())
    if burden > 2 * MAX_MINOR:
        fail("Native group debit turnover exceeds the exact signed minor-unit ceiling.")
    return {"kind": kind, "original_minor": gross, "settled_before_minor": before,
            "settlement_minor": settlement_minor, "outstanding_before_minor": gross - before,
            "books": books, "amount_minor": burden}


def consolidate_reports(reports: Sequence[Mapping[str, Any]], *, source_digest: str,
                        adjustment_plan_digest: str) -> dict[str, Any]:
    """Fold existing verified native financial reports; create no parallel ledger."""
    if len(reports) != 3 or len({report["legal_entity_id"] for report in reports}) != 3:
        fail("Group report requires the exact three independently authorized entity reports.")
    first = reports[0]
    shared = ("workspace_id", "organization_id", "period_id", "period_start", "period_end", "as_of_date", "currency_policy")
    if any(any(report[field] != first[field] for field in shared) for report in reports):
        fail("Group report cannot mix scopes, dates or retained currency policies.", "intercompany_policy_mismatch")
    accounts: dict[str, dict[str, Any]] = {}
    for report in reports:
        if report["report_digest"] != digest_payload({key: value for key, value in report.items() if key != "report_digest"}):
            fail("Native entity report failed its retained content seal.", "intercompany_evidence_invalid")
        for row in report["trial_balance"]["accounts"]:
            account = accounts.setdefault(row["account_id"], {key: row[key] for key in
                ("account_id", "account_code", "account_name", "account_type", "section", "is_cash")})
            if any(account[key] != row[key] for key in ("account_code", "account_type", "section", "is_cash")):
                fail("Reviewed group account classifications conflict.")
            for phase in ("opening", "activity", "closing"):
                totals = account.setdefault(phase, {"debit_minor": 0, "credit_minor": 0, "balance_minor": 0})
                for field in totals:
                    if type(row[phase][field]) is not int:
                        fail("Group balances require exact native integer minor units.")
                    totals[field] += row[phase][field]
            account.setdefault("postings", []).extend({"legal_entity_id": report["legal_entity_id"], **p}
                for p in row["postings"])
    for account in accounts.values():
        account["postings"].sort(key=lambda row: (row["effect_id"], row["line_number"]))
    sheet_keys = ("assets_minor", "liabilities_minor", "equity_minor", "accumulated_unclosed_result_minor")
    sheet = {key: sum(report["balance_sheet"][key] for report in reports) for key in sheet_keys}
    income = {key: sum(report["income_statement"][key] for report in reports)
              for key in ("income_minor", "expense_minor", "result_minor")}
    cash = {key: sum(report["cash_movements"][key] for report in reports)
            for key in ("opening_minor", "activity_minor", "closing_minor")}
    if (sheet["assets_minor"] != sheet["liabilities_minor"] + sheet["equity_minor"] + sheet["accumulated_unclosed_result_minor"]
            or sum(account["closing"]["balance_minor"] for account in accounts.values()) != 0):
        fail("Group financial equations disagree with native evidence.", "intercompany_evidence_invalid")
    result = {"schema_version": "intercompany-native-group-report-v1", "reporting_scope": "explicit-three-book-management",
              **{key: first[key] for key in shared}, "source_digest": source_digest,
              "adjustment_plan_digest": adjustment_plan_digest, "entity_reports": list(reports),
              "trial_balance": [accounts[key] for key in sorted(accounts)], "balance_sheet": {**sheet, "balanced": True},
              "income_statement": income, "cash_net_movements": cash,
              "effect_count": sum(report["effect_count"] for report in reports),
              "limitations": ["Explicit configured participation; no legal ownership or statutory assertion",
                               "One retained currency policy; no FX translation or tax treatment",
                               "Cash is net movement; no inferred statutory cash-flow classifications"]}
    return {**result, "report_digest": digest_payload(result)}
