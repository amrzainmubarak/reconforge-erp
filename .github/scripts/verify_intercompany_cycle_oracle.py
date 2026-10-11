"""Independent stdlib integer oracle for downloaded IC1 native three-book proofs.

No ReconForge imports. Content seals are internal integrity evidence, not external
attestation. Optional explicitly trusted manifest binds original downloaded bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

FILES = ("ic-proof-0.json", "ic-proof-1.json", "ic-proof-2.json", "ic-group-report.json")
RUNTIME = {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"}
BOOKS = ("seller", "buyer", "adjustment")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def load(raw: bytes | str) -> Any:
    def refuse(value: str) -> Any:
        raise ValueError("Noninteger JSON number: " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_float=refuse, parse_constant=refuse)


def money(value: Any, *, signed: bool = False) -> int:
    require(type(value) is int or (type(value) is str and re.fullmatch(r"-?(0|[1-9][0-9]*)", value) is not None), "Exact canonical integer minor units required")
    result = int(value)
    require(-(9 * 10**18) <= result <= 9 * 10**18 and (signed or result >= 0), "Minor-unit bound differs")
    require(str(result) == str(value), "Noncanonical integer text")
    return result


def normalize(value: Any, key: str = "") -> Any:
    if key.endswith("_minor"):
        return money(value, signed=True)
    if isinstance(value, dict):
        return {field: normalize(part, field) for field, part in value.items()}
    if isinstance(value, list):
        return [normalize(part) for part in value]
    require(value is None or type(value) in (str, bool, int), "Only exact JSON primitives are permitted")
    return value


def canonical(value: Any) -> str:
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(raw: bytes | str) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def seal(value: dict[str, Any], key: str) -> None:
    require(re.fullmatch(r"[a-f0-9]{64}", value[key]) is not None and sha(canonical({k: v for k, v in value.items() if k != key})) == value[key], "Canonical seal differs: " + key)


def verify(proofs: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, Any]:
    require(len(proofs) == 3, "Exactly original, partial settlement and final group proofs required")
    source = proofs[0]["source"]
    seal(source, "source_digest")
    request, policy = source["request"], source["monetary_policy"]
    gross = money(request["amount_minor"])
    require(0 < gross <= 45 * 10**17, "Original gross ceiling differs")
    entities = {book: request[book + "_entity_id"] for book in BOOKS}
    require(len(set(entities.values())) == 3 and all(type(v) is str and v for v in entities.values()), "Three distinct explicit scopes required")
    accounts = {key: request[key + "_account_code"] for key in ("receivable", "payable", "revenue", "expense", "cash")}
    require(len(set(accounts.values())) == 5, "Five distinct original native accounts required")
    require(type(policy["currency_precision"]) is int and 0 <= policy["currency_precision"] <= 8 and policy["currency_rounding_policy"] == "ROUND_HALF_UP", "Original currency precision/policy differs")
    native: dict[str, dict[str, Any]] = {}
    native_lines: dict[tuple[str, int], tuple[str, str, int, int]] = {}
    party_balances: dict[tuple[str, str], int] = defaultdict(int)
    account_ids: dict[str, str] = {}
    audit_ids: set[str] = set()
    outbox_ids: set[str] = set()
    settled = 0
    plan_ids: set[str] = set()
    for stage, proof in enumerate(proofs):
        require(proof["schema_version"] == "intercompany-native-evidence-v1" and proof["source"] == source, "Proofs must retain one exact original source")
        plan = proof["plan"]
        require(plan["kind"] == ("recognize", "settle", "eliminate")[stage] and type(plan["sequence"]) is int and plan["sequence"] == stage
                and type(plan["phase"]) is int and plan["phase"] == 2 and plan["status"] == "Posted", "Complete contiguous posted history required")
        require(plan["id"] not in plan_ids and plan["source_id"] == source["id"] and plan["source_digest"] == source["source_digest"], "Plan/source membership differs")
        plan_ids.add(plan["id"])
        require(all(plan[book + "_entity_id"] == entity for book, entity in entities.items())
                and all(plan[k] == request[k] for k in ("workspace_id", "organization_id")), "Original scope differs")
        require(plan["currency_code"] == policy["currency_code"] and plan["currency_precision"] == policy["currency_precision"], "Original native currency differs")
        originals = {key: value for key, value in plan.items() if key not in RUNTIME}
        require(proof["canonical_plan_json"] == canonical(originals) and sha(proof["canonical_plan_json"]) == plan["plan_digest"]
                and proof["canonical_source_json"] == canonical({k: v for k, v in source.items() if k != "source_digest"}), "Original source or plan seal differs")
        actors = [plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]]
        require(len(set(actors)) == 3 and all(type(actor) is str and actor for actor in actors), "Three independent humans required")
        require(plan["preparer_actor_id"] == source["preparer_actor_id"], "Original preparer differs")
        phases = proof["phases"]
        require(len(phases) == 3, "Three retained original owner phases required")
        for index, phase in enumerate(phases):
            require(phase["action"] == ("intercompany_operation_prepared", "intercompany_operation_reviewed", "intercompany_operation_posted")[index]
                    and phase["actor_id"] == actors[index], "Owner phase identity differs")
            for field, seen in (("audit_event_id", audit_ids), ("outbox_event_id", outbox_ids)):
                require(type(phase[field]) is str and phase[field] and phase[field] not in seen, "Owner immutable evidence duplicate")
                seen.add(phase[field])
        paid = money(plan["equation"]["settlement_minor"])
        remaining = gross - settled
        if stage == 0:
            require(paid == 0, "Recognition cannot transfer cash")
            expected = {"seller": [(accounts["receivable"], gross, 0), (accounts["revenue"], 0, gross)],
                        "buyer": [(accounts["expense"], gross, 0), (accounts["payable"], 0, gross)]}
        elif stage == 1:
            require(0 < paid < remaining, "Actual partial paired cash required")
            expected = {"seller": [(accounts["cash"], paid, 0), (accounts["receivable"], 0, paid)],
                        "buyer": [(accounts["payable"], paid, 0), (accounts["cash"], 0, paid)]}
        else:
            require(paid == 0, "Final group adjustment cannot transfer cash")
            expected = {"adjustment": [(accounts["revenue"], gross, 0), (accounts["expense"], 0, gross),
                                       (accounts["payable"], remaining, 0), (accounts["receivable"], 0, remaining)]}
        equation = plan["equation"]
        expected_books = {book: [{"account_code": account, "debit_minor": debit, "credit_minor": credit} for account, debit, credit in lines] for book, lines in expected.items()}
        burden = max(sum(line[1] for line in rows) for rows in expected.values())
        require(normalize(equation["books"]) == expected_books and equation["kind"] == plan["kind"]
                and money(equation["original_minor"]) == gross and money(equation["settled_before_minor"]) == settled
                and money(equation["outstanding_before_minor"]) == remaining and money(equation["amount_minor"]) == burden and money(plan["amount_minor"]) == burden, "Independent paired integer equation differs")
        entries, effects, raws = plan["entries"], proof["native_effects"], proof["canonical_snapshot_jsons"]
        require(len(entries) == len(effects) == len(raws) == len(expected) and set(plan["posting_effect_ids"]) == set(expected), "Complete native book/effect population required")
        for entry, effect, raw in zip(entries, effects, raws, strict=True):
            book, snapshot = entry["book"], entry["snapshot"]
            require(book in expected and raw == canonical(snapshot) and sha(raw) == entry["validation_digest"], "Native original snapshot seal differs")
            header = snapshot["entry"]
            require(header["id"] == entry["entry_id"] and header["legal_entity_id"] == entities[book]
                    and header["entry_number"] == plan["id"].upper() + {"seller": "-A", "buyer": "-B", "adjustment": "-G"}[book]
                    and header["period_id"] == plan["period_id"] and header["posting_date"] == plan["posting_date"]
                    and header["source_type"] == "Manual" and header.get("reverses_posting_id") is None
                    and header["preparer_actor_id"] == actors[0]
                    and all(header[k] == request[k] for k in ("workspace_id", "organization_id"))
                    and all(header[k] == v for k, v in policy.items()), "Native original book/header/currency differs")
            require(effect["id"] not in native and effect["id"] == plan["posting_effect_ids"][book]
                    and effect["entry_id"] == entry["entry_id"] and effect["validation_digest"] == entry["validation_digest"]
                    and effect["posted_actor_id"] == actors[2] and canonical(effect["snapshot"]) == raw, "Native immutable effect identity differs")
            for field, seen in (("audit_event_id", audit_ids), ("outbox_event_id", outbox_ids)):
                require(type(effect[field]) is str and effect[field] and effect[field] not in seen, "Native immutable evidence duplicate")
                seen.add(effect[field])
            lines = snapshot["lines"]
            require(len(lines) == len(expected[book]), "Native line population differs")
            for number, (actual, (account, debit, credit)) in enumerate(zip(lines, expected[book], strict=True), 1):
                require(type(actual["line_number"]) is int and actual["line_number"] == number
                        and money(actual["debit_minor"]) == debit and money(actual["credit_minor"]) == credit, "Native journal line differs from independent equation")
                prior = account_ids.setdefault(account, actual["account_id"])
                require(prior == actual["account_id"] and actual["dimensions"] == {}, "Original native account or unbound dimension differs")
                native_lines[(effect["id"], number)] = (entities[book], actual["account_id"], debit, credit)
                party_balances[(entities[book], account)] += debit - credit
            native[effect["id"]] = {"kind": plan["kind"], "book": book, "plan_id": plan["id"], "entry_id": entry["entry_id"], "effect_id": effect["id"]}
        settled += paid
    require(len(native) == 5, "Exactly five original native effects required")
    seal(report, "report_digest")
    require(report["schema_version"] == "intercompany-native-group-report-v1" and report["reporting_scope"] == "explicit-three-book-management"
            and report["source_digest"] == source["source_digest"] and report["adjustment_plan_digest"] == proofs[-1]["plan"]["plan_digest"]
            and type(report["effect_count"]) is int and report["effect_count"] == 5 and report["currency_policy"] == policy, "Actual native group report binding differs")
    require(all(report[k] == request[k] for k in ("workspace_id", "organization_id")), "Report canonical scope differs")
    observed: dict[tuple[str, int], tuple[str, str, int, int]] = {}
    for account in report["trial_balance"]:
        code = account["account_code"]
        require(code in account_ids and account["account_id"] == account_ids[code] and money(account["closing"]["balance_minor"], signed=True) == 0, "Group original account or zero net position differs")
        total = 0
        for line in account["postings"]:
            key = (line["effect_id"], line["line_number"])
            require(key in native_lines and key not in observed and line["entry_id"] == native[key[0]]["entry_id"], "Group drill-down original effect/entry/line membership differs")
            row = (line["legal_entity_id"], account["account_id"], money(line["debit_minor"]), money(line["credit_minor"]))
            require(row == native_lines[key], "Group drill-down native amounts differ")
            observed[key] = row
            total += row[2] - row[3]
        require(total == 0, "Independent group account net differs")
    require(observed == native_lines, "Group report must include exactly all original five-effect lines")
    parties = report["entity_reports"]
    require(len(parties) == 3 and {party["legal_entity_id"] for party in parties} == set(entities.values())
            and len({party["map_id"] for party in parties}) == 3, "Three distinct original reviewed-map report scopes required")
    classification = {accounts["receivable"]: ("Asset", "CurrentAsset", False), accounts["cash"]: ("Asset", "CurrentAsset", True),
                      accounts["payable"]: ("Liability", "CurrentLiability", False), accounts["revenue"]: ("Income", "Income", False),
                      accounts["expense"]: ("Expense", "Expense", False)}
    for party in parties:
        seal(party, "report_digest")
        entity = party["legal_entity_id"]
        require(party["contract_version"] == "financial-reporting-v1"
                and all(party[k] == report[k] for k in ("workspace_id", "organization_id", "period_id", "period_start", "period_end", "as_of_date", "currency_policy")), "Original native party report policy/cutoff differs")
        expected_party = {key: value for key, value in native_lines.items() if value[0] == entity}
        party_effects = {key[0] for key in expected_party}
        require(type(party["effect_count"]) is int and party["effect_count"] == len(party_effects), "Original party effect count differs")
        retained: dict[tuple[str, int], tuple[str, str, int, int]] = {}
        seen_accounts: set[str] = set()
        for account in party["trial_balance"]["accounts"]:
            code = account["account_code"]
            require(code in account_ids and account["account_id"] == account_ids[code] and code not in seen_accounts
                    and (account["account_type"], account["section"], account["is_cash"]) == classification[code], "Original reviewed party account classification differs")
            seen_accounts.add(code)
            debit = credit = 0
            for line in account["postings"]:
                key = (line["effect_id"], line["line_number"])
                row = (entity, account["account_id"], money(line["debit_minor"]), money(line["credit_minor"]))
                require(key in expected_party and key not in retained and row == expected_party[key]
                        and line["entry_id"] == native[key[0]]["entry_id"] and line["phase"] == "activity", "Original party native line membership differs")
                retained[key] = row
                debit += row[2]
                credit += row[3]
            for phase in ("opening", "activity", "closing"):
                dr, cr = (0, 0) if phase == "opening" else (debit, credit)
                expected_position = {"debit_minor": dr, "credit_minor": cr, "balance_minor": dr - cr,
                                     "debit_balance_minor": max(dr - cr, 0), "credit_balance_minor": max(cr - dr, 0)}
                require(normalize(account[phase]) == expected_position, "Independent original party position differs")
        require(retained == expected_party, "Original party report must include all and only its native source lines")
        def amount(code: str, selected_entity: str = entity) -> int:
            return party_balances.get((selected_entity, code), 0)
        income, expense, cash = -amount(accounts["revenue"]), amount(accounts["expense"]), amount(accounts["cash"])
        expected_sheet = {"assets_minor": amount(accounts["receivable"]) + cash, "liabilities_minor": -amount(accounts["payable"]),
                          "equity_minor": 0, "accumulated_unclosed_result_minor": income - expense, "balanced": True}
        require(normalize(party["balance_sheet"]) == expected_sheet
                and normalize(party["income_statement"]) == {"income_minor": income, "expense_minor": expense, "result_minor": income - expense}
                and {key: money(party["cash_movements"][key], signed=True) for key in ("opening_minor", "activity_minor", "closing_minor")}
                    == {"opening_minor": 0, "activity_minor": cash, "closing_minor": cash}, "Independent original party financial statement differs")
    require(normalize(report["income_statement"]) == {"income_minor": 0, "expense_minor": 0, "result_minor": 0}
            and normalize(report["cash_net_movements"]) == {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0}
            and report["balance_sheet"]["balanced"] is True
            and all(money(report["balance_sheet"][k], signed=True) == 0 for k in ("assets_minor", "liabilities_minor", "equity_minor", "accumulated_unclosed_result_minor")), "Independent group financial statement totals differ")
    return {"financial_verification": "passed", "source_id": source["id"], "source_digest": source["source_digest"], "currency_policy": policy,
            "original_minor": str(gross), "cash_minor": str(settled), "residual_minor": str(gross - settled), "group_debit_minor": str(2 * gross - settled),
            "native_effects": list(native.values()), "group_report_digest": report["report_digest"],
            "original_party_balances_minor": {entity + ":" + account: str(value) for (entity, account), value in sorted(party_balances.items())},
            "group_income_minor": "0", "group_expense_minor": "0", "group_cash_minor": "0", "external_attestation": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--trusted-manifest-sha256")
    args = parser.parse_args()
    require(not args.report.exists(), "Use a fresh output report; original evidence is never replaced")
    inputs = {name: (args.proof_directory / name).read_bytes() for name in FILES}
    require(bool(args.manifest) == bool(args.trusted_manifest_sha256), "Manifest and separately trusted SHA must be supplied together")
    if args.manifest:
        raw = args.manifest.read_bytes()
        require(sha(raw) == args.trusted_manifest_sha256, "Trusted original manifest SHA differs")
        manifest = load(raw)
        require(manifest == {name: sha(content) for name, content in inputs.items()}, "Original downloaded raw byte membership differs")
    result = verify([load(inputs[name]) for name in FILES[:3]], load(inputs[FILES[3]]))
    result.update(schema_version="independent-intercompany-oracle-v1", original_inputs_sha256={name: sha(raw) for name, raw in inputs.items()},
                  trusted_original_manifest_sha256=args.trusted_manifest_sha256)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"financial_verification": "passed", "native_effects": 5, "report": str(args.report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
