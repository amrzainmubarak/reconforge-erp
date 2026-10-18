"""Independent original-Cash Fraction oracle; stdlib only, no database writes.

The required raw-byte SHA is checked before parsing. Original source membership
is the opening basis; this does not substantiate whole-company cash balances.
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
MAX_BYTES = 67_108_864
PARTIES = ("seller", "buyer")
BOOKS = (*PARTIES, "adjustment")
MUTABLE = {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"}


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError("Original source cashflow refused: " + label)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def seal(value: dict[str, Any], field: str) -> None:
    require(value[field] == digest({key: item for key, item in value.items() if key != field}), field)


def integer(value: Any, *, maximum: int = 2 * MAX) -> int:
    require(type(value) is int and abs(value) <= maximum, "bounded exact integer")
    return value


def rate(value: dict[str, str], day: str) -> Fraction:
    require(set(value) == {"rate", "source", "effective_at"} and type(value["rate"]) is str
        and re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?", value["rate"]) is not None,
        "captured rate shape")
    require(type(value["source"]) is str and 0 < len(value["source"]) <= 160
        and value["effective_at"].startswith(day + "T") and value["effective_at"].endswith("Z"), "captured rate provenance")
    result = Fraction(value["rate"])
    require(result > 0, "positive captured rate")
    return result


def half_up(value: Fraction) -> int:
    sign = -1 if value < 0 else 1
    whole, remainder = divmod(abs(value.numerator), value.denominator)
    return sign * (whole + (2 * remainder >= value.denominator))


def inverse(amount: int, captured: dict[str, str], functional_precision: int, reporting_precision: int, day: str) -> int:
    ratio = rate(captured, day)
    return integer(half_up(Fraction(integer(amount, maximum=MAX), 10 ** functional_precision) / ratio * 10 ** reporting_precision), maximum=MAX)


def unique(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    result = {row[field]: row for row in rows}
    require(len(result) == len(rows), "unique original " + field)
    return result


def verify(proof: dict[str, Any]) -> dict[str, Any]:
    require(proof["schema_version"] == "intercompany-source-cashflow-evidence-v1"
        and proof["native_execution_proven"] is True and proof["performance_measurement"] is False
        and proof["financial_writes"] is False and proof["audit_chain_recomputed"] is False, "finite actual native proof scope")
    require(proof["native_role"] == {"rolsuper": False, "rolbypassrls": False}, "restricted native role")
    seal(proof, "evidence_digest")
    source, report, cashflow, opening = (proof[key] for key in ("source", "report", "cashflow", "opening"))
    seal(source, "source_digest")
    seal(report, "report_digest")
    seal(cashflow, "cashflow_digest")
    require(source["schema_version"] == "intercompany-fx-source-v2"
        and report["schema_version"] == "intercompany-fx-management-report-v2"
        and cashflow["schema_version"] == "intercompany-source-cashflow-v1", "versioned original contracts")
    request, policies, scope, originals = source["request"], source["policies"], proof["qualified_scope"], proof["original_rows"]
    require(scope["tenant_id"] and scope["workspace_id"] == request["workspace_id"]
        and scope["organization_id"] == request["organization_id"]
        and scope["legal_entity_ids"] == {book: request[book]["legal_entity_id"] for book in BOOKS}
        and len(set(scope["legal_entity_ids"].values())) == 3, "qualified native source hierarchy")
    require(set(originals) == {"effects", "entries", "lines", "dimensions", "plans", "source", "links", "reviews", "commands", "audit", "outbox"}
        and all(row["tenant_id"] == scope["tenant_id"] for rows in originals.values() for row in rows), "all original tenant custody")
    require(len(originals["source"]) == 1 and originals["source"][0]["payload"] == source, "actual original source row")
    require(originals["source"][0]["id"] == source["id"], "exact original source row identity")
    for rows in (originals["source"], originals["plans"], originals["commands"]):
        for row in rows:
            require(row["workspace_id"] == scope["workspace_id"] and row["organization_id"] == scope["organization_id"]
                and all(row[{"adjustment": "adjustment_entity_id", "seller": "seller_entity_id", "buyer": "buyer_entity_id"}[book]]
                    == request[book]["legal_entity_id"] for book in BOOKS), "all original source hierarchy columns")
    registry = proof["registry_snapshot"]
    seal(registry, "digest")
    currencies = unique(registry["currencies"], "code")
    require(all(type(row["minor_units"]) is int and 0 <= row["minor_units"] <= 8 for row in currencies.values()), "exact registry precision")
    require(set(policies) == {"transaction", *BOOKS}, "complete captured currency policies")
    for book, policy in policies.items():
        code = request["transaction_currency_code"] if book == "transaction" else request[book]["currency_code"]
        require(policy["currency_code"] == code and type(policy["currency_precision"]) is int
            and 0 <= policy["currency_precision"] <= 8 and policy["currency_precision"] == currencies[code]["minor_units"]
            and policy["currency_rounding_policy"] == currencies[code]["rounding_policy"] == "ROUND_HALF_UP"
            and policy["currency_registry_digest"] == registry["digest"]
            and policy["currency_registry_version"] == registry["registry_version"], "captured policy " + book)
    stages = proof["stages"]
    require(2 <= len(stages) <= 64 and len(originals["plans"]) == len(stages), "complete bounded source history")
    plans = [stage["plan"] for stage in stages]
    require([plan["sequence"] for plan in plans] == list(range(len(plans)))
        and plans[0]["kind"] == "recognize" and plans[-1]["kind"] == "eliminate"
        and all(plan["kind"] != "eliminate" for plan in plans[:-1]), "original source origin and closing elimination")
    require(opening == {"source_id": source["id"], "source_digest": source["source_digest"],
        "origin_plan_id": plans[0]["id"], "origin_plan_digest": plans[0]["plan_digest"],
        "seller_minor": 0, "buyer_minor": 0, "basis": "complete-native-source-origin-membership"}
        and type(opening["seller_minor"]) is int and type(opening["buyer_minor"]) is int, "explicit known source opening")
    require(report["source_id"] == cashflow["source_id"] == source["id"]
        and report["source_digest"] == cashflow["source_digest"] == source["source_digest"]
        and cashflow["report_digest"] == report["report_digest"]
        and report["adjustment_plan_digest"] == cashflow["elimination_plan_digest"] == plans[-1]["plan_digest"]
        and cashflow["elimination_plan_id"] == plans[-1]["id"]
        and report["currency_policy"] == cashflow["reporting_policy"] == policies["adjustment"], "posted native report and elimination binding")
    require(cashflow["scope"] == "explicit-paired-trade-native-source-membership"
        and cashflow["opening_basis"] == opening["basis"] and cashflow["opening_origin_plan_id"] == opening["origin_plan_id"]
        and cashflow["opening_origin_plan_digest"] == opening["origin_plan_digest"], "exact declared source opening basis")
    effects, entries, retained_plans = (unique(originals[key], "id") for key in ("effects", "entries", "plans"))
    reviews = unique(originals["reviews"], "plan_id")
    require(set(reviews) == {plan["id"] for plan in plans} and len(originals["commands"]) == 3 * len(plans),
        "complete original review and command population")
    original_lines = unique(originals["lines"], "id")
    require(all(row["entry_id"] in entries for row in original_lines.values())
        and len({(row["entry_id"], row["line_number"]) for row in original_lines.values()}) == len(original_lines), "complete original line population")
    require(all(row["entry_line_id"] in original_lines for row in originals["dimensions"])
        and len({(row["entry_line_id"], row["dimension_id"]) for row in originals["dimensions"]}) == len(originals["dimensions"]),
        "complete unique original dimension population")
    audit, outbox = unique(originals["audit"], "id"), unique(originals["outbox"], "event_id")
    linked: set[str] = set()
    cash: dict[str, list[dict[str, Any]]] = {book: [] for book in PARTIES}
    book_effects: dict[str, set[str]] = {book: set() for book in BOOKS}
    all_lines = 0
    for stage, plan in zip(stages, plans, strict=True):
        require(stage["source"] == source and plan["source_id"] == source["id"] and plan["source_digest"] == source["source_digest"]
            and plan["phase"] == 2 and plan["status"] == "Posted"
            and plan["plan_digest"] == digest({key: value for key, value in plan.items() if key not in MUTABLE}), "posted original plan seal")
        require(retained_plans[plan["id"]]["payload"] == {key: value for key, value in plan.items() if key not in MUTABLE - {"plan_digest"}}
            and retained_plans[plan["id"]]["phase"] == 2 and retained_plans[plan["id"]]["source_id"] == source["id"]
            and retained_plans[plan["id"]]["sequence"] == plan["sequence"]
            and retained_plans[plan["id"]]["kind"] == plan["kind"], "actual original plan row")
        require(len(stage["phases"]) == 3 and [row["action"] for row in stage["phases"]] == ["intercompany_fx_" + action for action in ("prepared", "reviewed", "posted")]
            and [row["actor_id"] for row in stage["phases"]] == [plan[field] for field in ("preparer_actor_id", "reviewer_actor_id", "posted_actor_id")]
            and len({row["actor_id"] for row in stage["phases"]}) == 3, "three original human phases")
        require(reviews[plan["id"]]["reviewer_actor_id"] == plan["reviewer_actor_id"]
            and reviews[plan["id"]]["audit_event_id"] == stage["phases"][1]["audit_event_id"]
            and reviews[plan["id"]]["outbox_event_id"] == stage["phases"][1]["outbox_event_id"], "actual original review row")
        for phase in stage["phases"]:
            require(phase["audit_event_id"] in audit and phase["outbox_event_id"] in outbox
                and phase["metadata_json"]["plan_digest"] == plan["plan_digest"]
                and audit[phase["audit_event_id"]]["actor_user_id"] == phase["actor_id"]
                and audit[phase["audit_event_id"]]["metadata_json"] == phase["metadata_json"]
                and outbox[phase["outbox_event_id"]]["payload"] == {**phase["metadata_json"], "audit_event_id": phase["audit_event_id"]}, "native phase references")
        commands = [row for row in originals["commands"] if row["plan_id"] == plan["id"]]
        require(len(commands) == 3 and {row["operation"] for row in commands} == {"prepare", "review", "post"}, "complete original command membership")
        for command in commands:
            expected_phase = {"prepare": 0, "review": 1, "post": 2}[command["operation"]]
            require(command["request_digest"] == digest(command["request_json"])
                and command["request_json"]["operation"] == command["operation"]
                and command["request_json"]["actor_id"] == command["actor_id"]
                and command["response_json"]["id"] == plan["id"] and command["response_json"]["plan_digest"] == plan["plan_digest"]
                and command["response_json"]["phase"] == expected_phase
                and command["actor_id"] == plan[{0: "preparer_actor_id", 1: "reviewer_actor_id", 2: "posted_actor_id"}[expected_phase]], "original immutable command actor/body/ACK")
        expected_books = {"adjustment"} if plan["kind"] == "eliminate" else set(PARTIES)
        require(len(plan["entries"]) == len(expected_books) and {entry["book"] for entry in plan["entries"]} == expected_books
            and set(plan["posting_effect_ids"]) == expected_books, "exact native book membership")
        stage_effects = unique(stage["native_effects"], "id")
        require(set(stage_effects) == set(plan["posting_effect_ids"].values()), "complete stage effects")
        for entry in plan["entries"]:
            book, snapshot = entry["book"], entry["snapshot"]
            effect_id = plan["posting_effect_ids"][book]
            require(effect_id not in linked, "no reused native effect")
            linked.add(effect_id)
            book_effects[book].add(effect_id)
            effect, header = effects[effect_id], snapshot["entry"]
            require(effect["snapshot_json"] == stage_effects[effect_id]["snapshot"] == snapshot
                and effect["validation_digest"] == entry["validation_digest"] == digest(snapshot)
                and effect["entry_id"] == header["id"] == entry["entry_id"]
                and effect["posted_actor_id"] == plan["posted_actor_id"]
                and effect["audit_event_id"] in audit and effect["outbox_event_id"] in outbox
                and entries[header["id"]]["status"] == "Validated", "actual posted original native effect")
            original_effect = plan["equation"].get("original_posting_effect_ids", {}).get(book)
            reverse = plan["kind"] == "reverse_revaluation"
            require(effect["source_kind"] == ("Reversal" if reverse else "Manual")
                and effect["source_id"] == (original_effect if reverse else header["id"])
                and effect["reverses_effect_id"] == (original_effect if reverse else None)
                and effect["purpose"] == "operational_posting", "original native effect owner and inverse")
            for field, value in {"workspace_id": scope["workspace_id"], "organization_id": scope["organization_id"],
                    "legal_entity_id": request[book]["legal_entity_id"], **policies[book]}.items():
                require(effect[field] == header[field] == value, "native book policy and scope")
            native_entry = entries[header["id"]]
            require(native_entry["organization_code"] == request["organization_code"] and native_entry["entity_code"] == request[book]["entity_code"]
                and native_entry["validator_actor_id"] == plan["reviewer_actor_id"]
                and native_entry["validation_digest"] == effect["validation_digest"]
                and all(native_entry[field] == value for field, value in header.items() if field not in {"organization_id", "legal_entity_id"}),
                "actual native header snapshot and review")
            require(header["posting_date"] == plan["posting_date"] and header["preparer_actor_id"] == plan["preparer_actor_id"], "native original date and preparer")
            raw_lines = [row for row in originals["lines"] if row["entry_id"] == entry["entry_id"]]
            require(len(raw_lines) == len(snapshot["lines"]) and len({row["id"] for row in raw_lines}) == len(raw_lines), "complete native entry lines")
            account_ids = {row["id"] for row in source["native_accounts"][book].values()}
            total = 0
            for row in snapshot["lines"]:
                all_lines += 1
                require(all_lines <= 512 and row["account_id"] in account_ids, "bounded declared native accounts")
                matching = [native for native in raw_lines if native["line_number"] == row["line_number"]]
                require(len(matching) == 1 and all(matching[0][key] == row[key] for key in ("account_id", "line_number", "debit_minor", "credit_minor", "description")), "actual native line bytes")
                dimensions = {native["dimension_id"]: native["dimension_value_id"] for native in originals["dimensions"] if native["entry_line_id"] == matching[0]["id"]}
                require(dimensions == row["dimensions"], "actual native line dimensions")
                debit, credit = integer(row["debit_minor"], maximum=MAX), integer(row["credit_minor"], maximum=MAX)
                require(debit >= 0 and credit >= 0 and (debit > 0) != (credit > 0), "one-sided original native money")
                total = integer(total + debit - credit)
                if row["account_id"] != source["native_accounts"][book]["cash"]["id"]:
                    continue
                require(book in PARTIES and plan["kind"] == "settle" and (credit == 0 if book == "seller" else debit == 0), "covered paired settlement Cash only")
                req = plan["command_request"]
                expected = half_up(Fraction(integer(req["transaction_minor"], maximum=MAX), 10 ** policies["transaction"]["currency_precision"])
                    * rate(req["rates"][book], plan["posting_date"]) * 10 ** policies[book]["currency_precision"])
                require(abs(debit - credit) == expected, "original settlement Cash business amount")
                cash[book].append({"effect_id": effect_id, "entry_id": entry["entry_id"], "line_number": row["line_number"],
                    "account_id": row["account_id"], "account_code": request[book]["accounts"]["cash"], "posting_date": plan["posting_date"],
                    "native_minor": debit - credit})
            require(total == 0, "balanced original native book")
    require(linked == set(effects) and len(entries) == len(effects) and len(original_lines) == all_lines,
        "complete original effect/entry/line membership")
    links = {(row["plan_id"], row["book"]): row for row in originals["links"]}
    require(len(links) == len(originals["links"]) == len(effects)
        and all(links[(plan["id"], book)]["posting_effect_id"] == effect_id
            and links[(plan["id"], book)]["entry_id"] == effects[effect_id]["entry_id"]
            and links[(plan["id"], book)]["posted_actor_id"] == plan["posted_actor_id"]
            for plan in plans for book, effect_id in plan["posting_effect_ids"].items()), "actual owner link bijection")
    for field, membership in (("source_effect_ids", book_effects["seller"] | book_effects["buyer"]), ("native_adjustment_effect_ids", book_effects["adjustment"])):
        require(set(report[field]) == set(cashflow[field]) == membership and len(report[field]) == len(cashflow[field]) == len(membership), "complete report " + field)
    operating_total = closing_total = inflow = outflow = 0
    derived = {}
    require(set(cashflow["books"]) == set(PARTIES), "exact classified source books")
    for key in ("opening_minor", "operating_inflow_minor", "operating_outflow_minor", "operating_net_minor", "fx_on_cash_minor", "closing_minor"):
        integer(cashflow[key])
    for book in PARTIES:
        translation = report["entity_translations"][book]
        require(translation == plans[-1]["equation"]["translations"][book], "reviewed translation membership")
        seal(translation, "translation_digest")
        closing_rate = plans[-1]["command_request"]["closing_rates"][book]
        require(translation["closing_rate"] == closing_rate, "reviewed original closing rate")
        selected = [row for row in translation["accounts"] if row["role"] == "cash"]
        require(len(selected) == (1 if cash[book] else 0), "complete native Cash account presence")
        contributions = {(row["effect_id"], row["line_number"]): row for row in selected[0]["contributions"]} if selected else {}
        require(len(contributions) == len(cash[book]) and set(contributions) == {(row["effect_id"], row["line_number"]) for row in cash[book]}, "exact translated Cash population")
        native_total = operating = 0
        movements = []
        for row in cash[book]:
            historical = plans[-1]["command_request"]["income_rates"][book][row["posting_date"]]
            member = contributions[(row["effect_id"], row["line_number"])]
            require(all(member[key] == row[key] for key in ("entry_id", "account_id", "account_code", "posting_date"))
                and integer(member["debit_minor"]) - integer(member["credit_minor"]) == row["native_minor"]
                and member["income_rate"] == historical, "original historical Cash membership")
            translated = inverse(abs(row["native_minor"]), historical, policies[book]["currency_precision"], policies["adjustment"]["currency_precision"], row["posting_date"])
            movement = translated if row["native_minor"] > 0 else -translated
            movements.append({**row, "historical_rate": historical, "operating_minor": movement})
            operating = integer(operating + movement)
            native_total = integer(native_total + row["native_minor"])
        closing = inverse(abs(native_total), closing_rate, policies[book]["currency_precision"], policies["adjustment"]["currency_precision"], plans[-1]["posting_date"])
        if native_total < 0:
            closing = -closing
        declared = cashflow["books"][book]
        for key in ("opening_minor", "native_cash_minor", "operating_minor", "closing_minor", "fx_on_cash_minor"):
            integer(declared[key])
        require(declared["legal_entity_id"] == request[book]["legal_entity_id"] and declared["functional_policy"] == policies[book]
            and declared["closing_rate"] == closing_rate and declared["movements"] == movements
            and declared["opening_minor"] == 0 and declared["native_cash_minor"] == native_total
            and declared["operating_minor"] == operating and declared["closing_minor"] == closing
            and declared["fx_on_cash_minor"] == closing - operating, "independent original Cash equation " + book)
        require(not selected or selected[0]["native_balance_minor"] == native_total and selected[0]["balance_minor"] == closing, "original closing translation arithmetic")
        operating_total, closing_total = integer(operating_total + operating), integer(closing_total + closing)
        inflow, outflow = inflow + max(operating, 0), outflow + max(-operating, 0)
        derived[book] = {"native_cash_minor": native_total, "operating_minor": operating, "closing_minor": closing, "fx_on_cash_minor": closing - operating}
    require(cashflow["opening_minor"] == 0 and cashflow["operating_net_minor"] == operating_total
        and cashflow["operating_inflow_minor"] == inflow and cashflow["operating_outflow_minor"] == outflow
        and cashflow["fx_on_cash_minor"] == closing_total - operating_total
        and cashflow["closing_minor"] == report["cash_net_movement_minor"] == closing_total, "independent group opening + operating + FX = closing")
    return {"schema_version": "intercompany-source-cashflow-oracle-v1", "verified": True, "source_id": source["id"],
        "source_digest": source["source_digest"], "cashflow_digest": cashflow["cashflow_digest"], "books": derived,
        "opening_minor": 0, "operating_net_minor": operating_total, "fx_on_cash_minor": closing_total - operating_total,
        "closing_minor": closing_total, "native_effects": len(effects), "native_lines": all_lines,
        "scope": "explicit-paired-trade-native-source-membership", "whole_company_cash_balance_proven": False,
        "audit_chain_recomputed": False, "legal_qualification_assessed": False}


def parse(raw: bytes) -> dict[str, Any]:
    require(len(raw) <= MAX_BYTES, "original evidence byte budget")
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        require(len({key for key, _ in items}) == len(items), "duplicate JSON keys")
        return dict(items)
    def numeric(_: str) -> Any:
        raise ValueError("Original source cashflow refused: floating point or non-finite JSON")
    value = json.loads(raw, object_pairs_hook=pairs, parse_float=numeric, parse_constant=numeric)
    require(type(value) is dict, "original evidence object")
    pending, nodes = [value], 0
    while pending:
        item = pending.pop()
        nodes += 1
        require(nodes <= 1_000_000, "original evidence node budget")
        if type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.input.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "original evidence byte budget before hash/parse")
    require(re.fullmatch(r"[0-9a-f]{64}", args.sha256) is not None and hashlib.sha256(raw).hexdigest() == args.sha256,
        "external original raw SHA before parse")
    result = {**verify(parse(raw)), "original_sha256": args.sha256, "original_bytes": len(raw)}
    with args.output.open("x", encoding="utf8") as handle:
        json.dump(result, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    print(json.dumps({"verified": True, "original_bytes": len(raw), "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
