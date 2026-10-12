"""Standalone exact wage/GL oracle. Imports only the Python standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def integer(value: Any) -> int:
    if isinstance(value, str):
        require(value.isascii() and value.isdecimal() and (value == "0" or not value.startswith("0")), "Noncanonical money")
        value = int(value)
    require(type(value) is int and 0 <= value <= 9_000_000_000_000_000_000, "Exact bounded integer required")
    return value


def normalize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {field: normalize(item, "amount_minor" if key in {"project_minor", "employees_minor"} else field) for field, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return integer(value) if key.endswith("_minor") else value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def even(value: Fraction) -> int:
    whole, remainder = divmod(value.numerator, value.denominator)
    return whole + int(2 * remainder > value.denominator or 2 * remainder == value.denominator and whole % 2 == 1)


def verify(raw: dict[str, Any]) -> dict[str, Any]:
    proof = normalize(raw)
    require(proof["schema_version"] == "people-payroll-evidence-v1", "Unknown evidence contract")
    parent = proof["payrun"]
    scope = {key: parent[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
    require(parent["schema_version"] == "people-payrun-v1" and parent["phase"] == 2 and parent["earnings_rounding"] == "HALF_EVEN", "Original posted accrual required")
    times: dict[str, dict[str, Any]] = {}
    earned: dict[str, dict[str, Fraction]] = {}
    employee_times: dict[str, list[str]] = {}
    for source in proof["times"]:
        require(source["id"] not in times and source["approver_id"] not in {None, source["submitter_id"]}, "Duplicate/unapproved time")
        require(all(source[key] == value for key, value in scope.items()), "Foreign approved time")
        require(source["source_digest"] == digest({**source["request_json"], "employment_id": source["employment_id"]}), "Time source digest differs")
        require(all(source[key] == value for key, value in parent["monetary_policy"].items()), "Original employment currency policy differs")
        times[source["id"]] = source
        employee_times.setdefault(source["employee_id"], []).append(source["id"])
        amounts = earned.setdefault(source["employee_id"], {})
        rate = integer(source["hourly_rate_minor"])
        require(rate > 0, "Positive original hourly rate required")
        previous_end = -1
        for line in sorted(source["lines"], key=lambda row: row["start_minute"]):
            start, end = integer(line["start_minute"]), integer(line["end_minute"])
            require(start >= previous_end and end > start and end <= 1440, "Invalid/overlapping original time")
            previous_end = end
            project = line["project_id"]
            amounts[project] = amounts.get(project, Fraction()) + Fraction(rate * (end - start), 60)
    employees = []
    projects: dict[str, int] = {}
    for employee, amounts in sorted(earned.items()):
        cumulative, previous, allocation = Fraction(), 0, {}
        for project, amount in sorted(amounts.items()):
            cumulative += amount
            rounded = even(cumulative)
            allocation[project] = rounded - previous
            previous = rounded
            projects[project] = projects.get(project, 0) + allocation[project]
        employees.append({"employee_id": employee, "time_entry_ids": sorted(employee_times[employee]), "gross_minor": previous, "project_minor": allocation})
    total = sum(row["gross_minor"] for row in employees)
    calculation = {"contract_version": "people-project-payroll-v1", "earnings_rounding": "HALF_EVEN", "allocation": "canonical-project-cumulative-v1", "time_entry_ids": sorted(times), "employees": employees, "project_minor": dict(sorted(projects.items())), "gross_minor": total}
    require(parent["private"] == calculation and parent["amount_minor"] == total and parent["project_minor"] == projects and parent["time_entry_ids"] == sorted(times), "Independent wages/project allocation differ")
    accounts = {row["account_code"]: row["id"] for row in proof["accounts"]}
    dimensions = {row["id"]: row for row in proof["projects"]}
    require(len(accounts) == 3 and len(accounts) == len(proof["accounts"]) and set(dimensions) == set(projects), "Native accounts/projects differ")
    effects = {row["id"]: row for row in proof["native_effects"]}
    plans = [parent, *proof["payments"]]
    require(len(effects) == len(proof["native_effects"]) == len(plans), "Native effect population differs")
    paid = {employee: 0 for employee in earned}
    balances: dict[str, int] = {}
    used_effects: set[str] = set()
    for index, plan in enumerate(plans):
        require(plan["phase"] == 2 and all(plan[key] == value for key, value in scope.items()), "Unposted/foreign settlement")
        require(all(plan[key] for key in ("preparer_id", "reviewer_id", "posted_actor_id")) and len({plan["preparer_id"], plan["reviewer_id"], plan["posted_actor_id"]}) == 3, "Financial human separation differs")
        excluded = {"phase", "status", "reviewer_id", "posted_actor_id", "posting_effect_id", "plan_digest", "native_effect"}
        require(plan["plan_digest"] == digest({key: value for key, value in plan.items() if key not in excluded}), "Source seal differs")
        require(plan["posting_effect_id"] not in used_effects, "Native effect reused")
        used_effects.add(plan["posting_effect_id"])
        effect = effects[plan["posting_effect_id"]]
        require(plan["native_effect"] == effect, "Private native effect projection differs")
        snapshot, header = effect["snapshot"], effect["snapshot"]["entry"]
        require(effect["entry_id"] == plan["entry_id"] and effect["posted_actor_id"] == plan["posted_actor_id"] and effect["source_kind"] == "Manual" and effect["reverses_effect_id"] is None, "Original native effect relation differs")
        require(digest(snapshot) == effect["validation_digest"] == plan["validation_digest"], "Native reviewed content differs")
        require(all(header[key] == value for key, value in scope.items()) and all(header[key] == value for key, value in parent["monetary_policy"].items()), "Native scope/currency policy differs")
        require(header["entry_number"] == plan["id"].upper() and header["external_reference"] == plan["id"] and header["preparer_actor_id"] == plan["preparer_id"] and header["posting_date"] == plan["posting_date"] and header["period_id"] == plan["period_id"] and header["reverses_posting_id"] is None, "Native header/source differs")
        if index == 0:
            expected = [{"account_id": accounts[parent["expense_account_code"]], "debit_minor": amount, "credit_minor": 0, "dimensions": {dimensions[project]["dimension_id"]: dimensions[project]["value_id"]}} for project, amount in sorted(projects.items()) if amount]
            expected.append({"account_id": accounts[parent["liability_account_code"]], "debit_minor": 0, "credit_minor": total, "dimensions": {}})
        else:
            allocation = plan["private"]["employees_minor"]
            require(plan["payrun_id"] == parent["id"] and sum(allocation.values()) == plan["amount_minor"] == plan["private"]["amount_minor"], "Settlement conservation differs")
            for employee, amount in allocation.items():
                require(employee in paid and amount > 0, "Foreign employee settlement")
                paid[employee] += amount
                require(paid[employee] <= next(row["gross_minor"] for row in employees if row["employee_id"] == employee), "Employee overpayment")
            expected = [{"account_id": accounts[parent["liability_account_code"]], "debit_minor": plan["amount_minor"], "credit_minor": 0, "dimensions": {}}, {"account_id": accounts[parent["cash_account_code"]], "debit_minor": 0, "credit_minor": plan["amount_minor"], "dimensions": {}}]
        lines = snapshot["lines"]
        require([row["line_number"] for row in lines] == list(range(1, len(expected) + 1)), "Native line population/order differs")
        require([{key: row[key] for key in ("account_id", "debit_minor", "credit_minor", "dimensions")} for row in lines] == expected, "Native GL/project allocation differs")
        for line in lines:
            code = next(code for code, identifier in accounts.items() if identifier == line["account_id"])
            balances[code] = balances.get(code, 0) + line["debit_minor"] - line["credit_minor"]
    budget = proof["observed_budget"]
    require(integer(budget["consumed_minor"]) == total and integer(budget["reserved_minor"]) == 0 and integer(budget["available_minor"]) + total == integer(budget["limit_minor"]), "Budget conservation differs")
    require([row["operation"] for row in proof["budget_events"]] == ["Reserve", "Consume"] and all(row["source_reference"] == parent["id"] and row["amount_minor"] == total for row in proof["budget_events"]), "Budget original source differs")
    require(proof["observed_native_balances"] == balances and sum(balances.values()) == 0, "Observed ledger differs")
    require(len(proof["claims"]) == 2 * len(times), "Whole-time claim population differs")
    for identifier, source in times.items():
        claims = [row for row in proof["claims"] if row["time_id"] == identifier]
        require([row["operation"] for row in claims] == ["Claim", "Consume"] and all(row["payrun_id"] == parent["id"] and row["source_digest"] == source["source_digest"] for row in claims), "Original consumed claim differs")
    return {"schema_version": "people-payroll-independent-oracle-v1", "accepted": True, "gross_minor": total, "project_minor": projects, "settled_minor": sum(paid.values()), "native_effects": len(effects), "approved_time_entries": len(times), "balances": balances, "statutory_country_packs": 0, "bank_execution_proven": False, "performance_comparison_accepted": False, "audit_chain_recomputed": False}


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.evidence.read_bytes()
    require(len(raw) <= 16_777_216, "Evidence exceeds bound")
    require(hashlib.sha256(raw).hexdigest() == args.expected_evidence_sha256, "Evidence differs from trusted raw anchor")
    def refuse(value: str) -> Any:
        raise ValueError("Noninteger JSON number refused")
    result = verify(json.loads(raw, object_pairs_hook=pairs, parse_float=refuse, parse_constant=refuse))
    result.update(raw_evidence_sha256=hashlib.sha256(raw).hexdigest(), raw_export_anchor=True)
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
