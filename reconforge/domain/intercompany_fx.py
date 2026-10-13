"""Versioned paired trade equations over captured canonical currency policies.

The two functional books and the reporting adjustment are native GL sources.
Translation is an explained management view of their exact effect membership.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, NoReturn

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.domain.operational_fx_tax import HistoricalRate, canonical_day, convert_minor, exact_rate
from reconforge.platform.inventory_values import code
from reconforge.utils.money import CurrencyRegistryContext, ExchangeRate, Money

MAX_MINOR = 4_500_000_000_000_000_000
MAX_OPERATIONS = 64
MAX_SETTLEMENTS = 32
MAX_EFFECT_LINES = 512
Kind = Literal["recognize", "settle", "revalue", "reverse_revaluation", "eliminate"]
PARTIES = ("seller", "buyer")


def fail(message: str, error: str = "intercompany_fx_invalid") -> NoReturn:
    raise FinancePostingError(error, message)


def minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        fail(f"{field} requires bounded exact integer minor units.")
    return value


def signed(value: object, field: str) -> int:
    if type(value) is not int or abs(value) > 2 * MAX_MINOR:
        fail(f"{field} requires bounded signed exact integer minor units.")
    return value


@dataclass(frozen=True)
class PartyAccounts:
    party: str
    trade: str
    cash: str
    realized_gain: str
    realized_loss: str
    unrealized_gain: str
    unrealized_loss: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        if any(code(value, role) != value for role, value in result.items()) or len(set(result.values())) != 7:
            fail("Seven distinct canonical party account roles are required.")
        return result


@dataclass(frozen=True)
class PartyBook:
    legal_entity_id: str
    entity_code: str
    currency_code: str
    journal_code: str
    period_id: str
    accounts: PartyAccounts

    def payload(self) -> dict[str, Any]:
        result = {key: value for key, value in asdict(self).items() if key != "accounts"}
        for key, value in result.items():
            canonical = code(value, key) if key.endswith("_code") else text(value, key, maximum=160)
            if canonical != value:
                fail("Party identities, periods and journals must be canonical.")
        return {**result, "accounts": self.accounts.payload()}


@dataclass(frozen=True)
class GroupAccounts:
    receivable: str
    payable: str
    revenue: str
    expense: str
    cash: str
    realized_gain: str
    realized_loss: str
    unrealized_gain: str
    unrealized_loss: str
    cta: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        if any(code(value, role) != value for role, value in result.items()) or len(set(result.values())) != 10:
            fail("Ten distinct canonical reporting account roles, including CTA, are required.")
        return result


@dataclass(frozen=True)
class GroupBook:
    legal_entity_id: str
    entity_code: str
    currency_code: str
    journal_code: str
    period_id: str
    accounts: GroupAccounts

    def payload(self) -> dict[str, Any]:
        result = {key: value for key, value in asdict(self).items() if key != "accounts"}
        for key, value in result.items():
            canonical = code(value, key) if key.endswith("_code") else text(value, key, maximum=160)
            if canonical != value:
                fail("An explicit native reporting adjustment scope is required.")
        return {**result, "accounts": self.accounts.payload()}


@dataclass(frozen=True)
class IntercompanyFxPreparation:
    workspace_id: str
    organization_id: str
    organization_code: str
    reference: str
    transaction_currency_code: str
    transaction_minor: int
    posting_date: str
    seller: PartyBook
    buyer: PartyBook
    adjustment: GroupBook
    seller_original_rate: HistoricalRate
    buyer_original_rate: HistoricalRate
    reason: str

    def payload(self) -> dict[str, Any]:
        result = {key: value for key, value in asdict(self).items()
                  if key not in {"seller", "buyer", "adjustment", "seller_original_rate", "buyer_original_rate"}}
        for key, value in result.items():
            canonical: object
            if key == "transaction_minor":
                canonical = minor(value, key)
            elif key == "posting_date":
                canonical = canonical_day(value, key)
            elif key.endswith("_code"):
                canonical = code(value, key)
            else:
                canonical = text(value, key, maximum=500 if key == "reason" else 160)
            if canonical != value:
                fail("Original paired trade inputs require exact canonical values.")
        for book in (*PARTIES, "adjustment"):
            result[book] = getattr(self, book).payload()
        if (len({result[book]["legal_entity_id"] for book in (*PARTIES, "adjustment")}) != 3
                or len({result[book]["entity_code"] for book in (*PARTIES, "adjustment")}) != 3
                or self.seller.currency_code == self.buyer.currency_code):
            fail("Two distinct functional currencies and a third distinct native adjustment entity are required.")
        for book in PARTIES:
            result[book + "_original_rate"] = getattr(self, book + "_original_rate").payload(self.posting_date)
        return result


def policy(context: CurrencyRegistryContext, currency: str) -> dict[str, Any]:
    value = FinanceCurrencyPolicy.capture(currency, context)
    if value.rounding_policy != "ROUND_HALF_UP":
        fail("ICFX2 currently supports the existing captured ROUND_HALF_UP policy.", "intercompany_fx_policy_unsupported")
    return {"currency_code": currency, **value.metadata()}


def exchange(rate: Mapping[str, str], base: str, quote: str, context: CurrencyRegistryContext, day: str) -> ExchangeRate:
    retained = HistoricalRate(**dict(rate))
    retained.payload(day)
    return ExchangeRate(base, quote, exact_rate(retained.rate), retained.source, retained.effective_at,
                        registry_context=context)


def converted(amount: int, rate: Mapping[str, str], base: str, quote: str,
              context: CurrencyRegistryContext, day: str, *, inverse: bool = False) -> int:
    minor(amount, "conversion source", zero=True)
    resolved = exchange(rate, base, quote, context, day)
    result = (resolved.convert_inverse(Money.from_minor_units(amount, quote, registry_context=context)).to_minor_units()
              if inverse else convert_minor(amount, resolved, context))
    return minor(result, "captured conversion", zero=True)


def line(account: str, debit: int, credit: int) -> dict[str, Any]:
    minor(debit, "line debit", zero=True)
    minor(credit, "line credit", zero=True)
    if bool(debit) == bool(credit):
        fail("A native line must carry exactly one nonzero side.")
    return {"account_code": account, "debit_minor": debit, "credit_minor": credit}


def balanced(rows: Sequence[Mapping[str, Any]]) -> int:
    debit = sum(row["debit_minor"] for row in rows)
    if not rows or len(rows) > 10 or debit != sum(row["credit_minor"] for row in rows) or not 0 < debit <= 2 * MAX_MINOR:
        fail("Bounded native book lines must conserve their own currency.")
    return debit


def recognition_equation(request: Mapping[str, Any], context: CurrencyRegistryContext) -> dict[str, Any]:
    gross = minor(request["transaction_minor"], "original foreign trade")
    books, positions, policies = {}, {}, {"transaction": policy(context, request["transaction_currency_code"])}
    for book in (*PARTIES, "adjustment"):
        policies[book] = policy(context, request[book]["currency_code"])
    for book in PARTIES:
        cfg = request[book]
        amount = minor(converted(gross, request[book + "_original_rate"], request["transaction_currency_code"],
            cfg["currency_code"], context, request["posting_date"]), "original functional trade")
        accounts = cfg["accounts"]
        rows = ([line(accounts["party"], amount, 0), line(accounts["trade"], 0, amount)] if book == "seller"
                else [line(accounts["trade"], amount, 0), line(accounts["party"], 0, amount)])
        books[book] = rows
        positions[book] = {"original_functional_minor": amount, "amount_minor": balanced(rows)}
    return {"kind": "recognize", "transaction_minor": gross, "policies": policies, "books": books, "positions": positions}


def settlement_equation(source: Mapping[str, Any], *, transaction_before_minor: int, transaction_minor: int,
                        posting_date: str, rates: Mapping[str, Mapping[str, str]], context: CurrencyRegistryContext) -> dict[str, Any]:
    request = source["request"]
    before, paid = minor(transaction_before_minor, "transaction paid before", zero=True), minor(transaction_minor, "transaction settlement")
    if before + paid > request["transaction_minor"] or canonical_day(posting_date, "settlement day") < request["posting_date"]:
        fail("Settlement must retain its original date-ordered bounded foreign residual.")
    books, positions = {}, {}
    for book in PARTIES:
        cfg, original = request[book], request[book + "_original_rate"]
        old = converted(before, original, request["transaction_currency_code"], cfg["currency_code"], context, request["posting_date"])
        after = converted(before + paid, original, request["transaction_currency_code"], cfg["currency_code"], context, request["posting_date"])
        released = after - old
        cash = minor(converted(paid, rates[book], request["transaction_currency_code"], cfg["currency_code"], context, posting_date), "functional cash")
        gain = cash - released if book == "seller" else released - cash
        accounts = cfg["accounts"]
        rows = ([line(accounts["cash"], cash, 0)] if book == "seller" else [line(accounts["cash"], 0, cash)])
        if released:
            rows.append(line(accounts["party"], 0, released) if book == "seller" else line(accounts["party"], released, 0))
        if gain:
            rows.append(line(accounts["realized_gain"] if gain > 0 else accounts["realized_loss"], max(-gain, 0), max(gain, 0)))
        books[book] = rows
        positions[book] = {"historical_before_minor": old, "historical_release_minor": released,
            "historical_after_minor": after, "functional_cash_minor": cash, "realized_fx_minor": gain,
            "rate": dict(rates[book]), "amount_minor": balanced(rows)}
    return {"kind": "settle", "transaction_before_minor": before, "transaction_minor": paid,
            "transaction_after_minor": before + paid, "books": books, "positions": positions}


def revaluation_equation(source: Mapping[str, Any], *, transaction_before_minor: int, posting_date: str,
                         rates: Mapping[str, Mapping[str, str]], context: CurrencyRegistryContext) -> dict[str, Any]:
    request = source["request"]
    before = minor(transaction_before_minor, "transaction settled before closing", zero=True)
    residual = minor(request["transaction_minor"] - before, "closing foreign residual")
    if canonical_day(posting_date, "closing day") < request["posting_date"]:
        fail("Closing valuation cannot precede its original source.")
    books, positions = {}, {}
    for book in PARTIES:
        cfg, original = request[book], request[book + "_original_rate"]
        gross = converted(request["transaction_minor"], original, request["transaction_currency_code"], cfg["currency_code"], context, request["posting_date"])
        released = converted(before, original, request["transaction_currency_code"], cfg["currency_code"], context, request["posting_date"])
        carrying = gross - released
        valued = converted(residual, rates[book], request["transaction_currency_code"], cfg["currency_code"], context, posting_date)
        delta, accounts = valued - carrying, cfg["accounts"]
        gain = delta if book == "seller" else -delta
        rows = []
        if delta:
            rows = [line(accounts["party"], max(delta, 0), max(-delta, 0)) if book == "seller"
                    else line(accounts["party"], max(-delta, 0), max(delta, 0)),
                    line(accounts["unrealized_gain"] if gain > 0 else accounts["unrealized_loss"], max(-gain, 0), max(gain, 0))]
            books[book] = rows
        positions[book] = {"historical_outstanding_minor": carrying, "valued_outstanding_minor": valued,
            "unrealized_fx_minor": gain, "rate": dict(rates[book]), "amount_minor": balanced(rows) if rows else 0}
    if not books:
        fail("A zero-delta closing observation requires no native journal; retain it outside posting.")
    return {"kind": "revalue", "transaction_before_minor": before, "transaction_outstanding_minor": residual,
            "books": books, "positions": positions}


def reversal_equation(original: Mapping[str, Any]) -> dict[str, Any]:
    if original["kind"] != "revalue" or original["phase"] != 2 or not original["posting_effect_ids"]:
        fail("A reviewed inverse requires its exact original posted closing operation.")
    books = {book: [{**row, "debit_minor": row["credit_minor"], "credit_minor": row["debit_minor"]}
                    for row in rows] for book, rows in original["equation"]["books"].items()}
    return {"kind": "reverse_revaluation", "original_revaluation_id": original["id"],
        "original_plan_digest": original["plan_digest"], "original_posting_effect_ids": dict(original["posting_effect_ids"]),
        "books": books, "positions": {book: {"amount_minor": balanced(rows)} for book, rows in books.items()}}


def translate_book(source: Mapping[str, Any], book: str, contributions: Sequence[Mapping[str, Any]], *,
                   closing_rate: Mapping[str, str], as_of_date: str, context: CurrencyRegistryContext) -> dict[str, Any]:
    if book not in PARTIES or not contributions or len(contributions) > MAX_EFFECT_LINES:
        fail("Translation requires bounded original native party effect membership.")
    request, target = source["request"], source["request"]["adjustment"]["currency_code"]
    cfg, group = request[book], request["adjustment"]["accounts"]
    roles = {account: role for role, account in cfg["accounts"].items()}
    accounts: dict[str, dict[str, Any]] = {}
    for contribution in contributions:
        account = contribution["account_code"]
        if account not in roles or contribution["legal_entity_id"] != cfg["legal_entity_id"]:
            fail("Native translation membership contains an unowned account or party.")
        role = roles[account]
        group_role = ("receivable" if book == "seller" else "payable") if role == "party" else ("revenue" if book == "seller" else "expense") if role == "trade" else role
        debit = minor(contribution["debit_minor"], "native contribution debit", zero=True)
        credit = minor(contribution["credit_minor"], "native contribution credit", zero=True)
        balance = signed(debit - credit, "native contribution")
        row = accounts.setdefault(role, {"role": group_role, "native_account_code": account, "account_code": group[group_role],
            "native_balance_minor": 0, "balance_minor": 0, "contributions": []})
        row["native_balance_minor"] = signed(row["native_balance_minor"] + balance, "native account closing")
        row["contributions"].append(dict(contribution))
        if role not in {"party", "cash"}:
            rate = contribution["income_rate"]
            translated = converted(abs(balance), rate, target, cfg["currency_code"], context, contribution["posting_date"], inverse=True)
            row["balance_minor"] = signed(row["balance_minor"] + (translated if balance >= 0 else -translated), "translated income account")
            row["translation_method"] = "captured-event-historical-inverse-v2"
    for role, row in accounts.items():
        if role in {"party", "cash"}:
            balance = row["native_balance_minor"]
            translated = converted(abs(balance), closing_rate, target, cfg["currency_code"], context, as_of_date, inverse=True)
            row["balance_minor"] = translated if balance >= 0 else -translated
            row.update(translation_method="captured-monetary-closing-inverse-v2", closing_rate=dict(closing_rate))
    cta = -sum(row["balance_minor"] for row in accounts.values())
    accounts["cta"] = {"role": "cta", "account_code": group["cta"], "native_account_code": None,
        "native_balance_minor": None, "balance_minor": signed(cta, "CTA"), "contributions": [],
        "translation_method": "explained-translation-balance-v2", "derived_from_effect_ids": sorted({row["effect_id"] for row in contributions})}
    result = {"legal_entity_id": cfg["legal_entity_id"], "functional_policy": source["policies"][book],
        "reporting_policy": source["policies"]["adjustment"], "closing_rate": dict(closing_rate), "cta_minor": -cta,
        "accounts": [accounts[key] for key in sorted(accounts)], "effect_ids": sorted({row["effect_id"] for row in contributions})}
    return {**result, "translation_digest": digest_payload(result)}


def elimination_equation(source: Mapping[str, Any], translations: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    group = source["request"]["adjustment"]["accounts"]
    values = {book: {row["role"]: row["balance_minor"] for row in translations[book]["accounts"]} for book in PARTIES}
    income, expense = -values["seller"].get("revenue", 0), values["buyer"].get("expense", 0)
    ar, ap = values["seller"].get("receivable", 0), -values["buyer"].get("payable", 0)
    if income != expense or ar != ap or income <= 0 or min(ar, ap) < 0:
        fail("Native elimination requires equal reviewed translated original trade and residual party balances.", "intercompany_fx_elimination_ambiguity")
    rows = [line(group["revenue"], income, 0), line(group["expense"], 0, expense)]
    if ar:
        rows.extend([line(group["payable"], ap, 0), line(group["receivable"], 0, ar)])
    return {"kind": "eliminate", "translated_trade_minor": income, "translated_residual_minor": ar,
        "translation_digests": {book: translations[book]["translation_digest"] for book in PARTIES},
        "native_membership": {book: translations[book]["effect_ids"] for book in PARTIES},
        "books": {"adjustment": rows}, "positions": {"adjustment": {"amount_minor": balanced(rows)}}}


def group_report(source: Mapping[str, Any], translations: Mapping[str, Mapping[str, Any]],
                 adjustment_lines: Sequence[Mapping[str, Any]], *, plan_digest: str) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    for book in PARTIES:
        for item in translations[book]["accounts"]:
            row = accounts.setdefault(item["role"], {"account_code": item["account_code"], "balance_minor": 0,
                "translated_membership": [], "native_adjustment_membership": []})
            row["balance_minor"] = signed(row["balance_minor"] + signed(item["balance_minor"], "translated account"), "group account")
            row["translated_membership"].append({"book": book, **dict(item)})
    roles = {account: role for role, account in source["request"]["adjustment"]["accounts"].items()}
    for item in adjustment_lines:
        role = roles[item["account_code"]]
        row = accounts.setdefault(role, {"account_code": item["account_code"], "balance_minor": 0,
            "translated_membership": [], "native_adjustment_membership": []})
        debit = minor(item["debit_minor"], "native adjustment debit", zero=True)
        credit = minor(item["credit_minor"], "native adjustment credit", zero=True)
        row["balance_minor"] = signed(row["balance_minor"] + debit - credit, "native adjusted group account")
        row["native_adjustment_membership"].append(dict(item))
    if sum(row["balance_minor"] for row in accounts.values()) != 0:
        fail("Translated trial balance and actual native adjustment do not balance.")
    def value(role: str) -> int:
        return signed(accounts.get(role, {}).get("balance_minor", 0), "group statement role")
    income = -sum(value(role) for role in ("revenue", "realized_gain", "unrealized_gain"))
    expense = sum(value(role) for role in ("expense", "realized_loss", "unrealized_loss"))
    assets, liabilities, equity = value("receivable") + value("cash"), -value("payable"), -value("cta")
    if assets != liabilities + equity + income - expense:
        fail("Translated balance sheet must retain its actual CTA and income effects.")
    result = {"schema_version": "intercompany-fx-management-report-v2", "reporting_scope": "explicit-paired-trade-native-management",
        "source_id": source["id"], "source_digest": source["source_digest"], "adjustment_plan_digest": plan_digest,
        "currency_policy": source["policies"]["adjustment"], "entity_translations": dict(translations),
        "trial_balance": [{"role": role, **accounts[role]} for role in sorted(accounts)],
        "balance_sheet": {"assets_minor": assets, "liabilities_minor": liabilities, "equity_minor": equity,
            "accumulated_unclosed_result_minor": income - expense, "balanced": True},
        "income_statement": {"income_minor": income, "expense_minor": expense, "result_minor": income - expense},
        "cash_net_movement_minor": value("cash"), "cta_minor": equity,
        "limitations": ["Explicit source-owned management scope and independently captured reporting-currency rates",
            "No ownership/NCI, investment, profit-in-stock, hyperinflation, statutory or country-tax assertion"]}
    return {**result, "report_digest": digest_payload(result)}
