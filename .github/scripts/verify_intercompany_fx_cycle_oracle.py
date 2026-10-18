"""Stdlib-only independent HALF_UP oracle over exported original native effects.

This verifier imports no ReconForge code and performs no database work. It checks
the explicit paired-trade scope, never claims full statutory consolidation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

MAX = 4_500_000_000_000_000_000
BOOKS = ("seller", "buyer")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integer(value: Any, *, signed: bool = False) -> int:
    if type(value) is not int or not (-2 * MAX if signed else 0) <= value <= 2 * MAX:
        raise ValueError("Noncanonical exact bounded integer")
    return value


def rate(value: dict[str, str], day: str) -> Fraction:
    if set(value) != {"rate", "source", "effective_at"} or not re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?", value["rate"]):
        raise ValueError("Malformed captured rate")
    if not value["source"] or not value["effective_at"].startswith(day + "T") or not value["effective_at"].endswith("Z"):
        raise ValueError("Rate provenance does not bind its original date")
    result = Fraction(value["rate"])
    if result <= 0:
        raise ValueError("Nonpositive captured rate")
    return result


def half_up(value: Fraction) -> int:
    sign = -1 if value < 0 else 1
    absolute = abs(value)
    whole, remainder = divmod(absolute.numerator, absolute.denominator)
    return sign * (whole + (2 * remainder >= absolute.denominator))


def convert(amount: int, captured: dict[str, str], base_precision: int, quote_precision: int, day: str, *, inverse: bool = False) -> int:
    ratio = rate(captured, day)
    result = half_up(Fraction(integer(amount), 10 ** base_precision) * (1 / ratio if inverse else ratio) * 10 ** quote_precision)
    return integer(result)


def verify(proof: dict[str, Any]) -> dict[str, Any]:
    checks: list[str] = []

    def check(ok: bool, label: str) -> None:
        if not ok:
            raise ValueError("Original ICFX2 oracle refused: " + label)
        checks.append(label)

    check(proof["schema_version"] == "intercompany-fx-original-cycle-proof-v2" and proof["performance_measurement"] is False, "original-proof-scope")
    check(proof["native_role"] == {"rolsuper": False, "rolbypassrls": False}, "restricted-native-role")
    stages = proof["stages"]
    check(1 <= len(stages) <= 64, "bounded-history")
    source = stages[0]["source"]
    request = source["request"]
    check(source["source_digest"] == digest({k: v for k, v in source.items() if k != "source_digest"}), "source-digest")
    policies = source["policies"]
    check(all(policies[book]["currency_rounding_policy"] == "ROUND_HALF_UP" for book in ("transaction", *BOOKS, "adjustment")), "actual-canonical-HALF_UP")
    check(len({policies[book]["currency_registry_digest"] for book in policies}) == 1, "workspace-registry-snapshot")
    check(request["seller"]["currency_code"] != request["buyer"]["currency_code"] and len({request[book]["legal_entity_id"] for book in (*BOOKS, "adjustment")}) == 3, "distinct-functional-native-group-books")
    gross = integer(request["transaction_minor"])
    check(0 < gross <= MAX, "bounded-transaction")
    fp = policies["transaction"]["currency_precision"]
    gp = policies["adjustment"]["currency_precision"]
    paid = 0
    active: dict[str, Any] | None = None
    native: dict[str, list[dict[str, Any]]] = {book: [] for book in (*BOOKS, "adjustment")}
    effects: set[str] = set()
    translations: dict[str, Any] = {}
    for sequence, stage in enumerate(stages):
        plan = stage["plan"]
        check(stage["source"] == source and plan["source_digest"] == source["source_digest"], f"source-membership-{sequence}")
        check(plan["phase"] == 2 and plan["sequence"] == sequence, f"contiguous-posted-history-{sequence}")
        sealed = {k: v for k, v in plan.items() if k not in {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"}}
        check(plan["plan_digest"] == digest(sealed), f"plan-digest-{sequence}")
        check(len(stage["phases"]) == 3 and len({phase["actor_id"] for phase in stage["phases"]}) == 3 and all(phase["audit_event_id"] and phase["outbox_event_id"] for phase in stage["phases"]), f"three-human-phase-evidence-{sequence}")
        check(plan["kind"] == plan["equation"]["kind"], f"equation-kind-{sequence}")
        req, eq, day = plan["command_request"], plan["equation"], plan["posting_date"]
        expected: dict[str, list[tuple[str, int, int]]] = {}
        if plan["kind"] in {"recognize", "settle", "revalue"}:
            for book in BOOKS:
                cfg = request[book]
                accounts = cfg["accounts"]
                lp = policies[book]["currency_precision"]
                original = convert(gross, request[book + "_original_rate"], fp, lp, request["posting_date"])
                if plan["kind"] == "recognize":
                    check(sequence == 0 and req["original_request"] == request and original == source["original_positions"][book]["original_functional_minor"], "original-carry-" + book)
                    expected[book] = [(accounts["party"], original, 0), (accounts["trade"], 0, original)] if book == "seller" else [(accounts["trade"], original, 0), (accounts["party"], 0, original)]
                elif plan["kind"] == "settle":
                    amount = integer(req["transaction_minor"])
                    check(active is None and 0 < amount <= gross - paid, "exact-settlement-residual-" + book)
                    before = convert(paid, request[book + "_original_rate"], fp, lp, request["posting_date"])
                    after = convert(paid + amount, request[book + "_original_rate"], fp, lp, request["posting_date"])
                    cash = convert(amount, req["rates"][book], fp, lp, day)
                    release = after - before
                    gain = cash - release if book == "seller" else release - cash
                    rows = [(accounts["cash"], cash, 0)] if book == "seller" else [(accounts["cash"], 0, cash)]
                    if release:
                        rows.append((accounts["party"], 0, release) if book == "seller" else (accounts["party"], release, 0))
                    if gain:
                        rows.append((accounts["realized_gain" if gain > 0 else "realized_loss"], max(-gain, 0), max(gain, 0)))
                    expected[book] = rows
                    check(eq["positions"][book]["historical_release_minor"] == release and eq["positions"][book]["realized_fx_minor"] == gain, "realized-FX-cumulative-release-" + book)
                else:
                    check(active is None and gross > paid, "closing-residual-" + book)
                    carry = original - convert(paid, request[book + "_original_rate"], fp, lp, request["posting_date"])
                    valued = convert(gross - paid, req["rates"][book], fp, lp, day)
                    delta = valued - carry
                    gain = delta if book == "seller" else -delta
                    if delta:
                        rows = [(accounts["party"], max(delta, 0), max(-delta, 0)) if book == "seller" else (accounts["party"], max(-delta, 0), max(delta, 0)),
                                (accounts["unrealized_gain" if gain > 0 else "unrealized_loss"], max(-gain, 0), max(gain, 0))]
                        expected[book] = rows
                    check(eq["positions"][book]["historical_outstanding_minor"] == carry and eq["positions"][book]["valued_outstanding_minor"] == valued and eq["positions"][book]["unrealized_fx_minor"] == gain, "unrealized-FX-" + book)
        elif plan["kind"] == "reverse_revaluation":
            check(active is not None and req["original_revaluation_id"] == active["id"] and eq["original_posting_effect_ids"] == active["posting_effect_ids"], "exact-active-native-inverse")
            assert active is not None
            expected = {book: [(row["account_code"], row["credit_minor"], row["debit_minor"]) for row in rows] for book, rows in active["equation"]["books"].items()}
        else:
            check(plan["kind"] == "eliminate", "known-operation")
            for book in BOOKS:
                cfg = request[book]
                roles = {value: key for key, value in cfg["accounts"].items()}
                balances: dict[str, int] = {}
                for line in native[book]:
                    role = roles[line["account_code"]]
                    value = line["debit_minor"] - line["credit_minor"]
                    translated = value if role in {"party", "cash"} else convert(abs(value), req["income_rates"][book][line["posting_date"]], policies[book]["currency_precision"], gp, line["posting_date"], inverse=True) * (-1 if value < 0 else 1)
                    balances[role] = balances.get(role, 0) + translated
                for role in ("party", "cash"):
                    value = balances.get(role, 0)
                    balances[role] = convert(abs(value), req["closing_rates"][book], policies[book]["currency_precision"], gp, day, inverse=True) * (-1 if value < 0 else 1)
                role_map = {"party": "receivable" if book == "seller" else "payable", "trade": "revenue" if book == "seller" else "expense"}
                translated_balances = {role_map.get(role, role): amount for role, amount in balances.items()}
                translated_balances["cta"] = -sum(translated_balances.values())
                captured = eq["translations"][book]
                check(captured["translation_digest"] == digest({key: value for key, value in captured.items() if key != "translation_digest"}), "translation-digest-" + book)
                check({row["role"]: row["balance_minor"] for row in captured["accounts"]} == translated_balances, "actual-native-translation-and-CTA-" + book)
                check(captured["effect_ids"] == sorted({line["effect_id"] for line in native[book]}), "exact-original-translated-membership-" + book)
                translations[book] = translated_balances
            income, expense = -translations["seller"]["revenue"], translations["buyer"]["expense"]
            ar, ap = translations["seller"]["receivable"], -translations["buyer"]["payable"]
            check(income == expense and ar == ap and ar >= 0 and income > 0, "reviewed-translated-elimination-conservation")
            group = request["adjustment"]["accounts"]
            expected["adjustment"] = [(group["revenue"], income, 0), (group["expense"], 0, expense)]
            if ar:
                expected["adjustment"] += [(group["payable"], ap, 0), (group["receivable"], 0, ar)]
            check(eq["translated_trade_minor"] == income and eq["translated_residual_minor"] == ar, "native-adjustment-reviewed-balances")
        check(set(eq["books"]) == set(expected), f"exact-book-membership-{sequence}")
        for book, rows in expected.items():
            check([(row["account_code"], row["debit_minor"], row["credit_minor"]) for row in eq["books"][book]] == rows, f"independent-native-equation-{sequence}-{book}")
            entry = next(entry for entry in plan["entries"] if entry["book"] == book)
            snapshot = entry["snapshot"]
            check(entry["validation_digest"] == digest(snapshot), f"original-snapshot-digest-{sequence}-{book}")
            check([(row["debit_minor"], row["credit_minor"]) for row in snapshot["lines"]] == [(row[1], row[2]) for row in rows], f"native-snapshot-amounts-{sequence}-{book}")
            check(sum(row[1] for row in rows) == sum(row[2] for row in rows) > 0, f"functional-book-conservation-{sequence}-{book}")
            effect = next(effect for effect in stage["native_effects"] if effect["entry_id"] == entry["entry_id"])
            check(effect["snapshot"] == snapshot and effect["validation_digest"] == entry["validation_digest"] and effect["id"] == plan["posting_effect_ids"][book] and effect["id"] not in effects, f"original-native-effect-{sequence}-{book}")
            effects.add(effect["id"])
            for ordinal, (account, debit, credit) in enumerate(rows, 1):
                native[book].append({"account_code": account, "debit_minor": debit, "credit_minor": credit, "effect_id": effect["id"], "posting_date": day, "line_number": ordinal})
        if plan["kind"] == "settle":
            paid += req["transaction_minor"]
        elif plan["kind"] == "revalue":
            active = plan
        elif plan["kind"] == "reverse_revaluation":
            active = None
    report = proof.get("report")
    if report is not None:
        check(stages[-1]["plan"]["kind"] == "eliminate", "report-after-native-elimination")
        check(report["report_digest"] == digest({key: value for key, value in report.items() if key != "report_digest"}), "complete-report-digest")
        balances: dict[str, int] = {}
        for rows in translations.values():
            for role, value in rows.items():
                balances[role] = balances.get(role, 0) + value
        group_roles = {value: key for key, value in request["adjustment"]["accounts"].items()}
        for line in native["adjustment"]:
            role = group_roles[line["account_code"]]
            balances[role] = balances.get(role, 0) + line["debit_minor"] - line["credit_minor"]
        check({row["role"]: row["balance_minor"] for row in report["trial_balance"]} == balances and sum(balances.values()) == 0, "balanced-actual-translated-adjusted-trial-balance")
        income = -sum(balances.get(role, 0) for role in ("revenue", "realized_gain", "unrealized_gain"))
        expense = sum(balances.get(role, 0) for role in ("expense", "realized_loss", "unrealized_loss"))
        check(report["income_statement"] == {"income_minor": income, "expense_minor": expense, "result_minor": income - expense}, "independent-translated-income-statement")
        check(report["cash_net_movement_minor"] == balances.get("cash", 0) and report["cta_minor"] == -balances.get("cta", 0), "actual-cash-and-CTA")
        check(report["balance_sheet"]["assets_minor"] == balances.get("cash", 0) + balances.get("receivable", 0) == report["balance_sheet"]["liabilities_minor"] + report["balance_sheet"]["equity_minor"] + income - expense, "complete-balanced-management-statement")
    return {"schema_version": "intercompany-fx-independent-oracle-v2", "passed": True, "checks": len(checks), "check_names": checks,
        "source_id": source["id"], "source_digest": source["source_digest"], "stage_count": len(stages), "native_effect_count": len(effects),
        "transaction_paid_minor": paid, "active_revaluation_id": active["id"] if active else None,
        "report_digest": report["report_digest"] if report else None, "performance_measurement": False, "statutory_qualification": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("proof", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.proof.read_bytes()
    result = {**verify(json.loads(raw)), "original_proof_sha256": hashlib.sha256(raw).hexdigest(), "original_proof_bytes": len(raw)}
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    print(serialized)


if __name__ == "__main__":
    main()
