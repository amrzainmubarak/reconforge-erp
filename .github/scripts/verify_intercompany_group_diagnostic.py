"""Stdlib original IC2 group bridge oracle; bounded raw custody, no DB writes.

The existing independently pinned Cash oracle verifies each complete original
source. Fraction then derives all translated account roles, CTA and the selected
reporting/native-adjustment bridge from its original native lines and rates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
from pathlib import Path
from typing import Any

MAX_BYTES = 67_108_864
MAX_MINOR = 9_000_000_000_000_000_000
CASHFLOW_HELPER_SHA256 = "416690b7cd6a465952cf918ae864dc510351b9a572423985d4f4ef57082da5f7"
BOOKS = ("seller", "buyer", "adjustment")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError("Original intercompany group diagnostic refused: " + label)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def seal(value: dict[str, Any], field: str) -> None:
    require(value[field] == digest({key: item for key, item in value.items() if key != field}), field)


def integer(value: Any) -> int:
    require(type(value) is int and abs(value) <= MAX_MINOR, "exact bounded integer")
    return value


def exact_display_money(value: Any) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            for key, member in item.items():
                if key.endswith("_minor"):
                    integer(member)
                pending.append(member)
        elif type(item) is list:
            pending.extend(item)


def cash_oracle() -> dict[str, Any]:
    path = Path(__file__).with_name("verify_intercompany_cashflow_oracle.py")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == CASHFLOW_HELPER_SHA256,
            "independently pinned source Cash helper before execution")
    return runpy.run_path(str(path))


def native_membership(proof: dict[str, Any], book: str) -> list[dict[str, Any]]:
    source, final = proof["source"], proof["stages"][-1]["plan"]
    accounts = {row["id"]: row["account_code"] for row in source["native_accounts"][book].values()}
    require(len(accounts) == len(source["native_accounts"][book]), "unique original native account IDs")
    result = []
    for stage in proof["stages"]:
        for entry in stage["plan"]["entries"]:
            if entry["book"] != book:
                continue
            header = entry["snapshot"]["entry"]
            for line in entry["snapshot"]["lines"]:
                row = {"effect_id": stage["plan"]["posting_effect_ids"][book], "entry_id": entry["entry_id"],
                    "line_number": line["line_number"], "account_id": line["account_id"],
                    "account_code": accounts[line["account_id"]], "posting_date": header["posting_date"],
                    "legal_entity_id": header["legal_entity_id"], "debit_minor": line["debit_minor"],
                    "credit_minor": line["credit_minor"]}
                if book != "adjustment":
                    row["income_rate"] = final["command_request"]["income_rates"][book][header["posting_date"]]
                result.append(row)
    return result


def translated_book(proof: dict[str, Any], book: str, api: dict[str, Any]) -> list[dict[str, Any]]:
    source, final = proof["source"], proof["stages"][-1]["plan"]
    config, reporting = source["request"][book], source["request"]["adjustment"]["accounts"]
    role_map = {code: role for role, code in config["accounts"].items()}
    closing = final["command_request"]["closing_rates"][book]
    fp, rp = source["policies"][book]["currency_precision"], source["policies"]["adjustment"]["currency_precision"]
    rows: dict[str, dict[str, Any]] = {}
    original = native_membership(proof, book)
    for member in original:
        native_role = role_map[member["account_code"]]
        role = ("receivable" if book == "seller" else "payable") if native_role == "party" else (
            "revenue" if book == "seller" else "expense") if native_role == "trade" else native_role
        row = rows.setdefault(role, {"role": role, "native_account_code": member["account_code"],
            "account_code": reporting[role], "native_balance_minor": 0, "balance_minor": 0, "contributions": []})
        amount = integer(integer(member["debit_minor"]) - integer(member["credit_minor"]))
        row["native_balance_minor"] = integer(row["native_balance_minor"] + amount)
        row["contributions"].append(member)
        if native_role not in {"party", "cash"}:
            converted = api["inverse"](abs(amount), member["income_rate"], fp, rp, member["posting_date"])
            row["balance_minor"] = integer(row["balance_minor"] + (converted if amount >= 0 else -converted))
            row["translation_method"] = "captured-event-historical-inverse-v2"
    for role, row in rows.items():
        if role in {"receivable", "payable", "cash"}:
            amount = row["native_balance_minor"]
            converted = api["inverse"](abs(amount), closing, fp, rp, final["posting_date"])
            row.update(balance_minor=converted if amount >= 0 else -converted, closing_rate=closing,
                       translation_method="captured-monetary-closing-inverse-v2")
    cta = integer(-sum(row["balance_minor"] for row in rows.values()))
    rows["cta"] = {"role": "cta", "account_code": reporting["cta"], "native_account_code": None,
        "native_balance_minor": None, "balance_minor": cta, "contributions": [],
        "translation_method": "explained-translation-balance-v2",
        "derived_from_effect_ids": sorted({row["effect_id"] for row in original})}
    expected = {"legal_entity_id": config["legal_entity_id"], "functional_policy": source["policies"][book],
        "reporting_policy": source["policies"]["adjustment"], "closing_rate": closing, "cta_minor": -cta,
        "accounts": [rows[key] for key in sorted(rows, key=lambda role: "party" if role in {"receivable", "payable"}
                                                else "trade" if role in {"revenue", "expense"} else role)]}
    expected["effect_ids"] = sorted({row["effect_id"] for row in original})
    expected["translation_digest"] = digest(expected)
    actual = proof["report"]["entity_translations"][book]
    require(expected == actual, "independent complete original translation " + book)
    return expected["accounts"]


def verify(proof: dict[str, Any]) -> dict[str, Any]:
    api = cash_oracle()
    require(proof["schema_version"] == "intercompany-group-diagnostic-evidence-v1"
            and proof["native_execution_proven"] is True and proof["financial_writes"] is False
            and proof["formal_close_workflow_assessed"] is False and proof["audit_chain_recomputed"] is False
            and proof["performance_comparison_accepted"] is False, "finite original native qualification")
    seal(proof, "evidence_digest")
    diagnostic, captures = proof["diagnostic"], proof["source_captures"]
    seal(diagnostic, "diagnostic_digest")
    exact_display_money(diagnostic)
    require(diagnostic["schema_version"] == "intercompany-group-diagnostic-v1"
            and diagnostic["reporting_scope"] == "explicit-selected-complete-paired-trade-sources"
            and diagnostic["formal_close_workflow_assessed"] is False and diagnostic["whole_group_membership_proven"] is False
            and diagnostic["financial_writes"] is False and diagnostic["source_elimination_complete"] is True,
            "selected diagnostic scope")
    pins = proof["selection"]["pins"]
    require(1 <= len(pins) == len(captures) <= 16 and proof["selection"] == diagnostic["selection"], "bounded exact selection")
    ids = [pin["opening"]["source_id"] for pin in pins]
    require(ids == sorted(set(ids)), "unique canonically ordered selected sources")
    first = captures[0]
    scope, registry, reporting_policy = first["qualified_scope"], first["registry_snapshot"], first["source"]["policies"]["adjustment"]
    cfg = {key: value for key, value in first["source"]["request"]["adjustment"].items() if key != "period_id"}
    journal = first["stages"][-1]["plan"]["entries"][0]["snapshot"]["entry"]["journal_id"]
    periods = {row["id"]: row for row in proof["native_periods"]}
    require(len(periods) == len(proof["native_periods"]), "unique observed period population")
    required_periods: set[str] = set()
    effects: set[str] = set()
    bridge: dict[str, dict[str, Any]] = {}
    members = []
    cash = {key: 0 for key in ("opening_minor", "operating_net_minor", "fx_on_cash_minor", "closing_minor")}
    for pin, capture in zip(pins, captures, strict=True):
        original_cash = api["verify"](capture)
        source, final, report = capture["source"], capture["stages"][-1]["plan"], capture["report"]
        require(capture["qualified_scope"] == scope and capture["registry_snapshot"] == registry
                and source["policies"]["adjustment"] == reporting_policy
                and source["native_accounts"]["adjustment"] == first["source"]["native_accounts"]["adjustment"]
                and {key: value for key, value in source["request"]["adjustment"].items() if key != "period_id"} == cfg
                and final["entries"][0]["snapshot"]["entry"]["journal_id"] == journal,
                "exact selected group book/account/policy scope")
        require(pin == {"opening": capture["opening"], "elimination_plan_id": final["id"],
                        "elimination_plan_digest": final["plan_digest"], "report_digest": report["report_digest"]},
                "original selected report/elimination pins")
        current_effects = set(report["source_effect_ids"] + report["native_adjustment_effect_ids"])
        require(not effects.intersection(current_effects), "selected native effect cannot be reused")
        effects.update(current_effects)
        for stage in capture["stages"]:
            for entry in stage["plan"]["entries"]:
                header = entry["snapshot"]["entry"]
                period_id = header["period_id"]
                required_periods.add(period_id)
                observed = periods.get(period_id)
                require(observed is not None and observed["tenant_id"] == scope["tenant_id"]
                        and observed["application_workspace_id"] == scope["workspace_id"]
                        and observed["status"] in {"Open", "Soft Closed", "Closed"}
                        and observed["start_date"] <= header["posting_date"] <= observed["end_date"],
                        "exact scoped observed native period")
        source_rows: dict[str, dict[str, Any]] = {}
        for book in ("seller", "buyer"):
            for item in translated_book(capture, book, api):
                row = source_rows.setdefault(item["role"], {"role": item["role"], "account_code": item["account_code"],
                    "balance_minor": 0, "translated_membership": [], "native_adjustment_membership": []})
                row["balance_minor"] = integer(row["balance_minor"] + item["balance_minor"])
                row["translated_membership"].append({"book": book, **item})
        roles = {code: role for role, code in cfg["accounts"].items()}
        for item in native_membership(capture, "adjustment"):
            role = roles[item["account_code"]]
            row = source_rows.setdefault(role, {"role": role, "account_code": item["account_code"], "balance_minor": 0,
                "translated_membership": [], "native_adjustment_membership": []})
            row["balance_minor"] = integer(row["balance_minor"] + item["debit_minor"] - item["credit_minor"])
            row["native_adjustment_membership"].append(item)
        require([source_rows[key] for key in sorted(source_rows)] == report["trial_balance"],
                "independent original report account and membership population")
        for role, item in source_rows.items():
            translated = integer(sum(row["balance_minor"] for row in item["translated_membership"]))
            native = integer(sum(row["debit_minor"] - row["credit_minor"] for row in item["native_adjustment_membership"]))
            row = bridge.setdefault(role, {"role": role, "account_code": cfg["accounts"][role],
                "translated_minor": 0, "native_adjustment_minor": 0, "combined_minor": 0, "source_membership": []})
            for key, value in (("translated_minor", translated), ("native_adjustment_minor", native), ("combined_minor", item["balance_minor"])):
                row[key] = integer(row[key] + value)
            row["source_membership"].append({"source_id": source["id"], "report_digest": report["report_digest"],
                "translated_minor": translated, "native_adjustment_minor": native, "combined_minor": item["balance_minor"]})
        for key in cash:
            cash[key] = integer(cash[key] + original_cash[key])
        members.append({"source_id": source["id"], "source_digest": source["source_digest"],
            "elimination_plan_id": final["id"], "elimination_plan_digest": final["plan_digest"],
            "report_digest": report["report_digest"], "source_evidence_digest": capture["evidence_digest"],
            "source_effect_ids": report["source_effect_ids"], "native_adjustment_effect_ids": report["native_adjustment_effect_ids"]})
    require(set(periods) == required_periods and diagnostic["native_period_observations"] == [periods[key] for key in sorted(periods)],
            "exact complete observed period population")
    require(diagnostic["qualified_scope"] == scope and diagnostic["reporting_policy"] == reporting_policy
            and diagnostic["group_journal_id"] == journal and diagnostic["source_members"] == members,
            "original diagnostic membership and policy")
    require(diagnostic["trial_balance_bridge"] == [bridge[key] for key in sorted(bridge)], "independent selected original bridge")
    for column in ("translated_minor", "native_adjustment_minor", "combined_minor"):
        require(sum(row[column] for row in bridge.values()) == 0, "independent bridge column balances")
    def balance(role: str) -> int:
        return bridge.get(role, {}).get("combined_minor", 0)
    income = integer(-sum(balance(role) for role in ("revenue", "realized_gain", "unrealized_gain")))
    expense = integer(sum(balance(role) for role in ("expense", "realized_loss", "unrealized_loss")))
    assets, liabilities, equity = integer(balance("receivable") + balance("cash")), -balance("payable"), -balance("cta")
    require(diagnostic["income_statement"] == {"income_minor": income, "expense_minor": expense, "result_minor": income - expense}
            and diagnostic["balance_sheet"] == {"assets_minor": assets, "liabilities_minor": liabilities, "equity_minor": equity,
                "unclosed_result_minor": income - expense, "balanced": True}
            and assets == liabilities + equity + income - expense, "independent statements and CTA equation")
    require(diagnostic["cash_equation"] == cash and cash["opening_minor"] + cash["operating_net_minor"] + cash["fx_on_cash_minor"]
            == cash["closing_minor"] == balance("cash"), "independent selected original Cash equation")
    return {"schema_version": "intercompany-group-diagnostic-oracle-v1", "verified": True,
        "diagnostic_digest": diagnostic["diagnostic_digest"], "sources": len(captures), "native_effects": len(effects),
        "trial_balance_bridge": diagnostic["trial_balance_bridge"], "cash_equation": cash,
        "income_statement": diagnostic["income_statement"], "balance_sheet": diagnostic["balance_sheet"],
        "whole_group_membership_proven": False, "formal_close_workflow_assessed": False,
        "current_authority_recomputed": False, "audit_chain_recomputed": False, "legal_qualification_assessed": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.input.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "byte budget before hash and parse")
    require(re.fullmatch("[0-9a-f]{64}", args.sha256) is not None and hashlib.sha256(raw).hexdigest() == args.sha256,
            "external original raw SHA before parse")
    result = {**verify(cash_oracle()["parse"](raw)), "original_sha256": args.sha256, "original_bytes": len(raw)}
    with args.output.open("x", encoding="utf8") as handle:
        json.dump(result, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    print(json.dumps({"verified": True, "sources": result["sources"], "original_bytes": len(raw)}))


if __name__ == "__main__":
    main()
