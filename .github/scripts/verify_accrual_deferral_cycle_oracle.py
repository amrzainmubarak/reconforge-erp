"""Standalone original-byte AD1 schedule/native-effect oracle; stdlib only."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

RESERVED_ORIGINALS = ("IC1-", "IC2-", "IC2S-", "IC2R-", "IC2E-", "FX1-", "ME1-", "ME1C-", "ME2-", "ME2C-", "HC1-", "HC1P-",
    "OPS1-", "OB1-", "FI1-", "CA1-", "LC1-", "FA1-", "CR1-", "CRF1-", "SR1-", "AD1-", "AD1R-", "PB1-", "PB1C-")


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def integer(value: Any, *, signed: bool = False) -> int:
    if isinstance(value, str):
        sign = value.startswith("-") and signed
        digits = value[1:] if sign else value
        require(digits.isascii() and digits.isdecimal() and (digits == "0" or not digits.startswith("0"))
                and value != "-0", "Noncanonical minor units")
        value = int(value)
    require(type(value) is int and abs(value) <= 9_000_000_000_000_000_000 and (signed or value >= 0), "Exact bounded minor units required")
    return value


def normalize(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: normalize(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return integer(value, signed=field == "cash_changed_minor") if field.endswith("_minor") or field == "weight" else value


def line(account: str, debit: int, credit: int, dimensions: dict[str, str]) -> dict[str, Any]:
    require(type(dimensions) is dict and len(dimensions) <= 8 and all(type(key) is str and type(value) is str
        and 0 < len(key) <= 160 and 0 < len(value) <= 160 and key.strip() == key and value.strip() == value for key, value in dimensions.items()),
        "At most eight canonical original dimension references are required")
    return {"account_code": account, "debit_minor": debit, "credit_minor": credit, "dimensions": dimensions}


def allocations(amount: int, tranches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    require(amount > 0 and 1 <= len(tranches) <= 36 and len({row["id"] for row in tranches}) == len(tranches)
            and len({row["period_id"] for row in tranches}) == len(tranches), "Distinct bounded tranche schedule required")
    total = sum(integer(row["weight"]) for row in tranches)
    require(total > 0 and all(integer(row["weight"]) > 0 for row in tranches), "Positive original source weights required")
    exact = {row["id"]: Fraction(amount * integer(row["weight"]), total) for row in tranches}
    assigned = {key: value.numerator // value.denominator for key, value in exact.items()}
    remaining = amount - sum(assigned.values())
    for key in sorted(exact, key=lambda key: (-(exact[key] - assigned[key]), key))[:remaining]:
        assigned[key] += 1
    require(all(value > 0 for value in assigned.values()), "Zero native tranche refused")
    return [{**row, "amount_minor": assigned[row["id"]]} for row in sorted(tranches, key=lambda row: (row["posting_date"], row["id"]))]


def verify(raw: dict[str, Any]) -> dict[str, Any]:
    proof = normalize(raw)
    require(proof["schema_version"] == "accrual-deferral-native-evidence-v1"
            and proof["evidence_digest"] == digest({key: value for key, value in proof.items() if key != "evidence_digest"}), "Original evidence seal differs")
    source = proof["source"]
    base = {key: value for key, value in source.items() if key not in {"plans", "claims", "cancelled", "source_digest"}}
    require(source["source_digest"] == digest(base), "Original source seal differs")
    request, policy, accounts = source["request"], source["policy"], source["request"]["accounts"]
    amount = integer(request["amount_minor"])
    require(request["allocation_policy"] == "native-hamilton-stable-id-v1"
            and request["tranches"] == allocations(amount, request["tranches"]), "Independent Fraction allocation differs")
    require(policy["currency_code"] == request["currency_code"] and policy["currency_rounding_policy"] == "ROUND_HALF_UP", "Original functional currency policy differs")
    scope = {key: request[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
    tenant = proof["qualified_scope"]["tenant_id"]
    require(isinstance(tenant, str) and bool(tenant) and proof["qualified_scope"] == {"tenant_id": tenant, **scope}, "Captured native qualified scope differs")
    for population in (source["claims"], proof["claims"], proof["account_pins"], proof["calendar_pins"], proof["phases"], proof["commands"],
                       proof["native_effects"], proof["original_claims"], proof["original_releases"], proof["financial_directory"], proof["financial_directory_releases"]):
        for row in population:
            require(row["tenant_id"] == tenant and all(row[key] == value for key, value in scope.items() if key in row),
                    "Raw native tenant or hierarchy custody differs")
    for population in (source["claims"], proof["claims"], proof["account_pins"], proof["calendar_pins"], proof["original_claims"], proof["original_releases"]):
        require(all(row["source_id"] == source["id"] for row in population), "Raw AD1 source membership differs")
    modes = {"new_prepaid_voucher", "attach_paid_expense", "attach_prepaid_voucher", "expense_accrual"}
    require(request["mode"] in modes and len(set(accounts.values())) == 4, "Original source mode and account roles differ")
    account_ids = {row["id"]: row["account_code"] for row in source["native_accounts"].values()}
    require(len(account_ids) == 4, "Native account identity membership differs")
    account_pins = {pin["role"]: pin for pin in proof["account_pins"]}
    require(len(account_pins) == len(proof["account_pins"]) == 4 and set(account_pins) == set(accounts), "Structural account role pin population differs")
    for role, pin in account_pins.items():
        require(pin["source_id"] == source["id"] and pin["workspace_id"] == request["workspace_id"]
                and source["native_accounts"][role] == {"id": pin["account_id"], **{key: pin[key] for key in ("chart_id", "account_code", "account_type")}},
                "Frozen native account identity chart code type tuple differs")
    plans = {row["id"]: row for row in source["plans"]}
    effects = {row["id"]: row for row in proof["native_effects"]}
    require(len(plans) == len(source["plans"]) <= 160 and len(effects) == len(proof["native_effects"]), "Duplicate native source population")
    require(len(proof["phases"]) == len({(row["plan_id"], row["operation"]) for row in proof["phases"]})
            and len(proof["commands"]) == len({(row["plan_id"], row["operation"]) for row in proof["commands"]})
            and all(row["plan_id"] in plans for row in [*proof["phases"], *proof["commands"]]), "Duplicate or foreign phase population")
    require(len(source["claims"]) == len(request["tranches"])
            and {row["tranche_id"] for row in source["claims"]} == {row["id"] for row in request["tranches"]}
            and all(row["tranche_id"] in {item["id"] for item in request["tranches"]} for row in proof["claims"]), "Claim head or event population differs")
    original_periods = {request["period_id"], *(row["period_id"] for row in request["tranches"]),
                        *(row["reversal_period_id"] for row in request["tranches"] if "reversal_period_id" in row)}
    require(set(source["native_periods"]) == original_periods, "Original fiscal calendar population differs")
    pins = {row["period_id"]: row for row in proof["calendar_pins"]}
    require(len(pins) == len(proof["calendar_pins"]) and set(pins) == original_periods | {plan["period_id"] for plan in plans.values()},
            "Structural native period pin population differs")
    for identifier, captured in [*source["native_periods"].items(), *((plan["period_id"], plan["native_period"]) for plan in plans.values())]:
        pin = pins[identifier]
        require(captured == {"id": pin["period_id"], **{key: pin[key] for key in ("start_date", "end_date", "fiscal_year", "period_number", "application_workspace_id")}}
                and captured["application_workspace_id"] == request["workspace_id"] and pin["source_id"] == source["id"], "Exact original native calendar tuple differs")
        require(date.fromisoformat(captured["start_date"]).isoformat() == captured["start_date"]
                and date.fromisoformat(captured["end_date"]).isoformat() == captured["end_date"]
                and captured["start_date"] <= captured["end_date"], "Captured canonical fiscal dates differ")
    initial = [row for row in plans.values() if row["kind"] == "source"]
    require(len(initial) == 1, "One original voucher approval required")
    external = source["equation"]["external_original_membership"]
    dimensions = external.get("basis_dimensions", {})
    expected_source_rows: list[dict[str, Any]] = []
    used_effects: set[str] = set()
    balances: dict[str, int] = {}

    def observe(effect: dict[str, Any]) -> None:
        require(effect["id"] not in used_effects, "Native effect reused")
        used_effects.add(effect["id"])
        snapshot = effect["snapshot"]
        require(effect["source_id"] == (effect["reverses_effect_id"] if effect["source_kind"] == "Reversal" else effect["entry_id"]),
                "Native ledger original or inverse source commitment differs")
        require(effect["validation_digest"] == digest(snapshot), "Native reviewed snapshot seal differs")
        require(all(snapshot["entry"][field] == value for field, value in {**scope, **policy}.items()), "Native scope or monetary policy differs")
        require(sum(row["debit_minor"] for row in snapshot["lines"]) == sum(row["credit_minor"] for row in snapshot["lines"]) > 0,
                "Native effect conservation differs")
        for row in snapshot["lines"]:
            require(row["account_id"] in account_ids and (row["debit_minor"] > 0) != (row["credit_minor"] > 0), "Native account or one-sided amount differs")
            code = account_ids[row["account_id"]]
            balances[code] = balances.get(code, 0) + row["debit_minor"] - row["credit_minor"]

    if request["mode"].startswith("attach_"):
        original = effects[request["original_effect_id"]]
        require(all(not str(original["snapshot"]["entry"][field]).upper().startswith(RESERVED_ORIGINALS) for field in ("id", "entry_number")),
                "Operating original must retain its original source owner")
        observe(original)
        review = external["original_review"]
        require(original["source_kind"] == "Manual" and original["reverses_effect_id"] is None
                and original["snapshot"] == external["original_snapshot"] and original["validation_digest"] == external["original_validation_digest"], "External paid original membership differs")
        require(len(set(external["original_actor_ids"])) == 3 and external["original_actor_ids"] == [original["snapshot"]["entry"]["preparer_actor_id"], review["validator_actor_id"], original["posted_actor_id"]]
                and review["validation_digest"] == original["validation_digest"], "Original paid native review actors differ")
        role = "expense" if request["mode"] == "attach_paid_expense" else "prepaid"
        expected_original = [line(accounts[role], amount, 0, dimensions), line(accounts["cash"], 0, amount, external["original_cash_dimensions"])]
        actual_original = [{"account_code": account_ids[row["account_id"]], **{key: row[key] for key in ("debit_minor", "credit_minor", "dimensions")}} for row in original["snapshot"]["lines"]]
        require(actual_original == expected_original, "Paid original account amount or dimensions differ")
        require(len(proof["original_claims"]) == len(proof["financial_directory"]) == 1, "Whole-original claim/directory population differs")
        claim, directory = proof["original_claims"][0], proof["financial_directory"][0]
        require(claim["effect_id"] == directory["source_effect_id"] == original["id"] and claim["id"] == directory["id"] == directory["owner_claim_id"]
                and claim["source_id"] == source["id"] and directory["owner_namespace"] == "AD1", "Original effect owner directory differs")
    else:
        require(external == {} and not proof["original_claims"] and not proof["financial_directory"] and request["original_effect_id"] is None,
                "New voucher or accrual estimate cannot silently consume an existing paid original")
    if request["mode"] == "new_prepaid_voucher":
        expected_source_rows = [line(accounts["prepaid"], amount, 0, {}), line(accounts["cash"], 0, amount, {})]
    elif request["mode"] == "attach_paid_expense":
        expected_source_rows = [line(accounts["prepaid"], amount, 0, dimensions), line(accounts["expense"], 0, amount, dimensions)]
    expected_source = {"schema_version": "accrual-deferral-source-v1", "operation": "source", "mode": request["mode"], "policy": policy,
        "lines": expected_source_rows, "cash_changed_minor": -amount if request["mode"] == "new_prepaid_voucher" else 0,
        "native_effect_required": bool(expected_source_rows), "external_original_membership": external, "allocated_minor": amount,
        "allocation_policy": request["allocation_policy"], "tranches": request["tranches"]}
    require(source["equation"] == expected_source, "Independent original source cash membership differs")
    posted_financial = 0
    for plan in plans.values():
        phase = integer(plan["phase"])
        require(phase <= 2 and plan["source_id"] == source["id"] and plan["source_digest"] == source["source_digest"]
                and all(plan[key] == value for key, value in scope.items()), "Native source plan scope differs")
        sealed = {key: value for key, value in plan.items() if key not in {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_id", "plan_digest"}}
        require(plan["plan_digest"] == digest(sealed), "Original plan seal differs")
        equation = plan["equation"]
        require(plan["native_period"]["start_date"] <= plan["posting_date"] <= plan["native_period"]["end_date"], "Plan date lies outside its exact original fiscal period")
        if plan["kind"] == "source":
            expected = expected_source
        elif plan["kind"] in {"release", "accrue"}:
            tranche = next(row for row in request["tranches"] if row["id"] == plan["tranche_id"])
            allocated = tranche["amount_minor"]
            accrue = request["mode"] == "expense_accrual"
            require(initial[0]["phase"] == 2 and plan["kind"] == ("accrue" if accrue else "release"), "Tranche original approval differs")
            expected = {"schema_version": "accrual-deferral-source-v1", "operation": plan["kind"], "tranche_id": tranche["id"],
                "period_id": tranche["period_id"], "posting_date": tranche["posting_date"], "amount_minor": allocated,
                "lines": [line(accounts["expense"], allocated, 0, dimensions), line(accounts["accrued_liability"] if accrue else accounts["prepaid"], 0, allocated, dimensions)],
                "policy": policy, "cash_changed_minor": 0, "native_effect_required": True}
        elif plan["kind"] == "reverse":
            original = plans[plan["original_plan_id"]]
            require(original["phase"] == 2 and original["kind"] in {"release", "accrue"}, "Exact inverse original differs")
            if original["kind"] == "accrue":
                tranche = next(row for row in request["tranches"] if row["id"] == original["tranche_id"])
                require((plan["period_id"], plan["posting_date"]) == (tranche["reversal_period_id"], tranche["reversal_date"]), "Original next-period accrual inverse date differs")
            expected = {"schema_version": "accrual-deferral-source-v1", "operation": "reverse", "original_plan_id": original["id"],
                "original_plan_digest": original["plan_digest"], "original_posting_effect_id": original["posting_effect_id"], "original_kind": original["kind"],
                "tranche_id": original["tranche_id"], "amount_minor": original["equation"]["amount_minor"], "policy": policy,
                "lines": [line(row["account_code"], row["credit_minor"], row["debit_minor"], row["dimensions"]) for row in original["equation"]["lines"]],
                "cash_changed_minor": 0, "native_effect_required": True}
        else:
            require(plan["kind"] == "cancel", "Unknown source plan kind")
            expected = {"schema_version": "accrual-deferral-source-v1", "operation": "cancel", "lines": [], "policy": policy,
                "cash_changed_minor": 0, "native_effect_required": False}
        require(equation == expected, "Independent tranche liability source cash or exact inverse differs")
        phases = {row["operation"]: row for row in proof["phases"] if row["plan_id"] == plan["id"]}
        commands = {row["operation"]: row for row in proof["commands"] if row["plan_id"] == plan["id"]}
        operations = ["prepare", "review", "post"][:phase + 1]
        require(set(phases) == set(commands) == set(operations), "Original phase command/evidence population differs")
        actors = [plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]][:phase + 1]
        require(len(set(actors)) == len(actors) and all(actors), "Three original human identities differ")
        for operation, actor in zip(operations, actors, strict=True):
            event, command = phases[operation], commands[operation]
            require(event["actor_id"] == command["actor_id"] == actor and command["request_digest"] == digest(command["request_json"]), "Original actor/command digest differs")
            require(event["posting_effect_id"] == (plan["posting_effect_id"] if operation == "post" else None), "Phase native effect membership differs")
            response = command["response_json"]
            require({key: value for key, value in response.items() if key not in {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_id"}} == {**sealed, "plan_digest": plan["plan_digest"]}, "Retained original acknowledgement differs")
        if expected["native_effect_required"]:
            require(plan["validation_digest"] == digest(plan["snapshot"]), "Prepared native content seal differs")
            header = plan["snapshot"]["entry"]
            require(header["preparer_actor_id"] == plan["preparer_actor_id"] and header["period_id"] == plan["period_id"]
                    and header["posting_date"] == plan["posting_date"] and header["entry_number"] == plan["id"].upper(), "Original native plan period or source header differs")
            actual = [{"account_code": account_ids[row["account_id"]], **{key: row[key] for key in ("debit_minor", "credit_minor", "dimensions")}} for row in plan["snapshot"]["lines"]]
            require(actual == expected["lines"], "Every original native account line and dimension must match source allocation")
            if phase == 2:
                effect = effects[plan["posting_effect_id"]]
                require(effect["snapshot"] == plan["snapshot"] and effect["posted_actor_id"] == plan["posted_actor_id"]
                        and effect["entry_id"] == plan["entry_id"]
                        and effect["source_kind"] == ("Reversal" if plan["kind"] == "reverse" else "Manual")
                        and effect["reverses_effect_id"] == (expected["original_posting_effect_id"] if plan["kind"] == "reverse" else None), "Posted native exact membership differs")
                observe(effect)
                posted_financial += 1
        else:
            require(plan["entry_id"] is None and plan["snapshot"] is None and plan["validation_digest"] is None and plan["posting_effect_id"] is None, "External-only membership cannot fabricate native GL")
    require(used_effects == set(effects) and sum(balances.values()) == 0, "Observed native effect membership and ledger conservation differ")
    require(source["cancelled"] == any(plan["kind"] == "cancel" and plan["phase"] == 2 for plan in plans.values()), "Source cancellation state differs")
    if source["cancelled"]:
        require(posted_financial == 0, "Consumed original cannot be cancelled")
    for tranche in request["tranches"]:
        events = [row for row in proof["claims"] if row["tranche_id"] == tranche["id"]]
        state, previous = "", ""
        require([row["sequence"] for row in events] == list(range(1, len(events) + 1)) and 1 <= len(events) <= 16, "Claim history is not contiguous")
        for event in events:
            plan = plans[event["plan_id"]]
            require(event["source_id"] == source["id"], "Foreign tranche claim")
            operation = event["operation"]
            if operation == "Initialize":
                require(event["sequence"] == 1 and plan["kind"] == "source", "Original claim initialization differs")
                state = "Available"
            elif operation == "Claim":
                require(state == "Available" and plan["kind"] in {"release", "accrue"} and plan["tranche_id"] == tranche["id"], "Duplicate/foreign tranche reservation")
                state = "Reserved"
            elif operation == "Consume":
                require(state == "Reserved" and plan["id"] == previous and plan["phase"] == 2 and plan["posting_effect_id"], "Detached native tranche consumption")
                state = "Consumed"
            elif operation == "Reverse":
                require(state == "Consumed" and plan["kind"] == "reverse" and plan["phase"] == 2 and plan["original_plan_id"] == previous, "Exact original inverse claim differs")
                state = "Available"
            else:
                require(operation == "Cancel" and state != "Consumed" and plan["kind"] == "cancel" and plan["phase"] == 2 and posted_financial == 0, "Invalid original cancellation release")
                state = "Available"
            require(event["state"] == state, "Claim event state differs")
            previous = plan["id"]
        heads = [row for row in source["claims"] if row["tranche_id"] == tranche["id"]]
        require(len(heads) == 1 and (heads[0]["sequence"], heads[0]["state"], heads[0]["plan_id"]) == (len(events), state, previous), "Current head does not bind its exact original event")
    if proof["original_claims"]:
        claim = proof["original_claims"][0]
        expected_state = "Released" if source["cancelled"] else "Consumed" if posted_financial else "Reserved"
        require(claim["state"] == expected_state, "Shared original claim consumption differs")
        if expected_state == "Released":
            require(len(proof["original_releases"]) == len(proof["financial_directory_releases"]) == 1
                    and proof["original_releases"][0]["id"] == proof["financial_directory_releases"][0]["release_id"]
                    and proof["original_releases"][0]["claim_id"] == claim["id"] == proof["financial_directory_releases"][0]["guard_id"], "Cancellation directory release membership differs")
        else:
            require(not proof["original_releases"] and not proof["financial_directory_releases"], "Consumed original ownership cannot be silently released")
    return {"schema_version": "accrual-deferral-independent-oracle-v1", "accepted": True, "source_mode": request["mode"],
        "original_minor": amount, "allocated_minor": [row["amount_minor"] for row in request["tranches"]], "native_effects": len(effects),
        "posted_source_plans": sum(plan["phase"] == 2 for plan in plans.values()), "posted_financial_effects": posted_financial,
        "native_balances": balances, "cancelled": source["cancelled"], "country_statutory_packs": 0,
        "audit_chain_recomputed": False, "performance_comparison_accepted": False}


def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def refuse(value: str) -> Any:
    raise ValueError("Noninteger JSON number refused")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.evidence.read_bytes()
    require(len(raw) <= 67_108_864 and hashlib.sha256(raw).hexdigest() == args.expected_evidence_sha256,
            "Evidence differs from the trusted original byte anchor")
    result = verify(json.loads(raw, object_pairs_hook=unique_pairs, parse_float=refuse, parse_constant=refuse))
    result.update(raw_evidence_sha256=hashlib.sha256(raw).hexdigest(), raw_anchor_verified=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(canonical(result) + "\n")


if __name__ == "__main__":
    main()
