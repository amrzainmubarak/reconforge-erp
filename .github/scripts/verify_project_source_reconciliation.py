"""Independent bounded stdlib oracle for public Project source reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

MAX_BYTES = 67_108_864
HEADER = (
    "id",
    "workspace_id",
    "organization_id",
    "legal_entity_id",
    "journal_id",
    "period_id",
    "entry_number",
    "posting_date",
    "description",
    "external_reference",
    "source_type",
    "currency_code",
    "currency_precision",
    "currency_rounding_policy",
    "currency_registry_version",
    "currency_registry_digest",
    "preparer_actor_id",
    "reverses_posting_id",
)
POLICY = (
    "currency_code",
    "currency_precision",
    "currency_rounding_policy",
    "currency_registry_version",
    "currency_registry_digest",
)


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def number(value: Any) -> int:
    need(type(value) is int and 0 <= value <= 9_000_000_000_000_000_000, "Exact bounded native integer required")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        need(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def verify(proof: dict[str, Any]) -> dict[str, Any]:
    need(proof["schema_version"] == "project-source-reconciliation-evidence-v1", "Unknown evidence contract")
    need(
        proof["evidence_digest"] == sha({k: v for k, v in proof.items() if k != "evidence_digest"}),
        "Evidence seal differs",
    )
    report, raw, selected = proof["report"], proof["original_rows"], proof["selection"]
    need(
        report["report_digest"] == sha({k: v for k, v in report.items() if k != "report_digest"}), "Report seal differs"
    )
    need(
        report["schema_version"] == "project-source-reconciliation-v1"
        and report["limitations"]
        == {
            "private_earnings_digest_recomputed": False,
            "private_personnel_rows_included": False,
            "original_time_request_digest_recomputed": False,
            "audit_chain_recomputed": False,
            "comprehensive_project_profit_and_loss": False,
            "bank_transfer_proven": False,
            "country_tax_packs": 0,
            "performance_comparison_accepted": False,
        },
        "Unsupported report coverage claim",
    )
    scope = raw["qualified_scope"]
    need(
        report["qualified_scope"] == scope
        and all(scope[k] == selected["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")),
        "Qualified source scope differs",
    )
    need(report["selection"] == {k: v for k, v in selected.items() if k != "scope"}, "Selected source identity differs")
    need(
        raw["native_role"] == {"rolsuper": False, "rolbypassrls": False, "personnel_member": False},
        "Ordinary native role required",
    )
    for key in (
        "financial_writes",
        "private_personnel_reads",
        "private_payroll_command_receipts_exported",
        "audit_chain_recomputed",
        "performance_comparison_accepted",
    ):
        need(proof[key] is False, "Unsupported evidence claim")
    need(
        proof["native_execution_proven"] is True
        and proof["capture_scope"] == "one-fixed-readonly-postgresql-statement-snapshot",
        "Original native statement required",
    )
    pending = [proof]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            need(
                not {
                    "private",
                    "employee_id",
                    "employee_name",
                    "employees",
                    "employees_minor",
                    "hourly_rate_minor",
                }.intersection(item),
                "Private personnel field refused",
            )
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        else:
            need(item is None or type(item) in (str, bool, int), "Exact JSON primitives required")

    def rows(name: str, key: str = "id") -> dict[str, Any]:
        population = raw[name]
        need(type(population) is list and len(population) <= 20_000, "Bounded population required")
        result = {}
        for row in population:
            need(
                row["tenant_id"] == scope["tenant_id"]
                and type(row[key]) is str
                and bool(row[key])
                and len(row[key]) <= 160
                and not any(ord(char) < 32 or ord(char) == 127 for char in row[key])
                and row[key] not in result,
                "Foreign or duplicate native identity",
            )
            result[row[key]] = row
        return result

    def scoped(row: dict[str, Any]) -> None:
        need(all(row.get(k) == v for k, v in scope.items()), "Foreign qualified source")

    wages, plans, cash = rows("payruns"), rows("plans"), rows("payments")
    need(set(wages) == {selected["payrun_id"]} and selected["invoice_id"] in plans, "Original pair absent")
    wage, invoice = wages[selected["payrun_id"]], plans[selected["invoice_id"]]
    w, bill = wage["payload"], invoice["payload"]
    need(
        invoice["kind"] == "Invoice" and w["period_id"] == bill["period_id"] == selected["period_id"],
        "Original period/kind differs",
    )
    times, projects = rows("times"), rows("projects")
    need(
        set(times) == set(w["time_entry_ids"]) == set(bill["calculation"]["time_ids"])
        and len(times) == len(w["time_entry_ids"]) == len(bill["calculation"]["time_ids"]),
        "Whole approved time coverage differs",
    )
    need(
        report["approved_time"] == [{"id": key, "source_digest": times[key]["source_digest"]} for key in sorted(times)],
        "Reported approved-time custody differs",
    )
    intervals = {}
    for time in times.values():
        scoped(time)
        need(
            bool(time["approver_id"]) and time["approver_id"] != time["submitter_id"],
            "Independent time approval required",
        )
        previous = -1
        for line in sorted(time["lines"], key=lambda x: x["start_minute"]):
            start, end = number(line["start_minute"]), number(line["end_minute"])
            need(previous <= start < end <= 1440, "Original time overlap/range differs")
            previous = end
            key = (time["id"], line["project_id"], start, end)
            need(key not in intervals, "Duplicate approved interval")
            intervals[key] = time["source_digest"]
    prices = rows("prices")
    need(
        set(prices) == set(bill["calculation"]["price_ids"]) and len(prices) == len(bill["calculation"]["price_ids"]),
        "Original approved price population differs",
    )
    for price in prices.values():
        scoped(price)
        immutable = price["source_json"]
        need(
            sha(immutable) == price["source_digest"]
            and all(
                immutable[key] == price[key]
                for key in (
                    *scope,
                    "id",
                    "customer_code",
                    "project_id",
                    "valid_from",
                    "valid_through",
                    "currency_code",
                    "hourly_price_minor",
                    "preparer_id",
                )
            )
            and bool(price["approver_id"])
            and price["approver_id"] != price["preparer_id"]
            and price["customer_code"] == bill["customer_code"]
            and immutable["monetary_policy"] == bill["monetary_policy"],
            "Original approved price seal/actor/policy differs",
        )
        project = projects[price["project_id"]]
        need(
            immutable["dimension_id"] == project["dimension_id"] and immutable["value_id"] == project["value_id"],
            "Original price Project differs",
        )
    pricing: dict[str, Fraction] = {}
    observed = set()
    for line in bill["calculation"]["sources"]:
        price = prices[line["price_id"]]
        need(
            line["price_digest"] == price["source_digest"]
            and line["hourly_price_minor"] == price["hourly_price_minor"]
            and line["project_id"] == price["project_id"]
            and price["valid_from"] <= times[line["time_id"]]["business_date"] <= price["valid_through"],
            "Applied rate differs from approved effective original price",
        )
        key = (line["time_id"], line["project_id"], number(line["start_minute"]), number(line["end_minute"]))
        need(
            key in intervals
            and key not in observed
            and line["time_digest"] == intervals[key]
            and number(line["minutes"]) == key[3] - key[2],
            "Detached or altered billed interval",
        )
        observed.add(key)
        pricing[key[1]] = pricing.get(key[1], Fraction()) + Fraction(
            number(line["hourly_price_minor"]) * line["minutes"], 60
        )
    need(observed == set(intervals), "Incomplete service-minute pricing")
    need(
        w["monetary_policy"] == bill["monetary_policy"]
        and bill["monetary_policy"]["currency_rounding_policy"] == "ROUND_HALF_UP",
        "Captured functional policy differs",
    )
    policy = w["monetary_policy"]
    need(
        type(policy["currency_precision"]) is int
        and 0 <= policy["currency_precision"] <= 8
        and type(policy["currency_code"]) is str
        and re.fullmatch(r"[A-Z]{3}", policy["currency_code"]) is not None
        and type(policy["currency_registry_digest"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", policy["currency_registry_digest"]) is not None
        and type(policy["currency_registry_version"]) is str
        and bool(policy["currency_registry_version"]),
        "Captured currency metadata invalid",
    )
    need(
        report["currency_policy"] == {key: w["monetary_policy"][key] for key in POLICY},
        "Displayed currency policy differs",
    )
    independent_revenue = {
        key: (2 * value.numerator + value.denominator) // (2 * value.denominator) for key, value in pricing.items()
    }
    need(
        independent_revenue == bill["calculation"]["project_minor"]
        and sum(independent_revenue.values()) == number(bill["amount_minor"]),
        "Independent Fraction service allocation differs",
    )
    need(
        sum(number(v) for v in w["project_minor"].values()) == number(w["amount_minor"]),
        "Public governed wage allocation does not conserve",
    )
    need(set(projects) == set(w["project_minor"]) | set(independent_revenue), "Original Project population differs")
    for family, owner_key, owner in (("hc", "payrun_id", wage["id"]), ("pb", "invoice_id", invoice["id"])):
        heads, history = rows(family + "_claim_heads", "time_id"), rows(family + "_claim_events")
        need(
            set(heads) == set(times) and all(e["time_id"] in times for e in history.values()), "Claim coverage differs"
        )
        for key, head in heads.items():
            events = sorted([e for e in history.values() if e["time_id"] == key], key=lambda e: e["sequence"])
            need(
                [number(e["sequence"]) for e in events] == list(range(1, number(head["sequence"]) + 1)),
                "Claim sequence differs",
            )
            active, consumed = None, False
            for event in events:
                need(
                    not consumed and event["source_digest"] == times[key]["source_digest"],
                    "Consumed or altered original claim",
                )
                if event["operation"] == "Claim":
                    need(active is None, "Multiple active whole-time claims")
                    active = event[owner_key]
                else:
                    need(
                        event["operation"] in ("Release", "Consume") and active == event[owner_key],
                        "Unknown or foreign claim transition",
                    )
                    consumed = event["operation"] == "Consume"
                    active = active if consumed else None
            need(
                consumed and active == head[owner_key] == owner and head["state"] == "Consumed",
                "Final consumed owner differs",
            )
    sources = [wage, *cash.values(), *plans.values()]
    entries, effects, lines, accounts, journals = (
        rows(k) for k in ("entries", "effects", "entry_lines", "accounts", "journals")
    )
    need(
        set(journals) == {e["journal_id"] for e in entries.values()}
        and set(accounts) == {line["account_id"] for line in lines.values()},
        "Original account/journal metadata population differs",
    )
    need(
        len(sources) <= 200
        and set(entries) == {s["entry_id"] for s in sources}
        and set(effects) == {s["effect_id"] for s in sources},
        "Source/native population differs",
    )
    attached: dict[str, dict[str, str]] = {key: {} for key in lines}
    for item in raw["entry_dimensions"]:
        need(
            item["tenant_id"] == scope["tenant_id"]
            and item["entry_line_id"] in attached
            and item["dimension_id"] not in attached[item["entry_line_id"]],
            "Detached/duplicate native dimension",
        )
        attached[item["entry_line_id"]][item["dimension_id"]] = item["dimension_value_id"]
    need(all(line["entry_id"] in entries for line in lines.values()), "Detached original ledger line")
    masters, values = rows("dimension_masters"), rows("dimension_values")
    need(
        set(masters) == {p["dimension_id"] for p in projects.values()}
        and set(values) == {p["value_id"] for p in projects.values()},
        "Project master population differs",
    )
    for project in projects.values():
        scoped(project)
        master, value = masters[project["dimension_id"]], values[project["value_id"]]
        need(
            master["dimension_type"] == "Project"
            and master["active"] is True
            and value["active"] is True
            and master["organization_code"] in ("", selected["scope"]["organization_code"])
            and master["workspace_id"] == value["workspace_id"] == scope["workspace_id"]
            and value["dimension_id"] == master["id"]
            and value["value_code"] == project["project_code"],
            "Project master identity differs",
        )
    commands, audits, outbox = rows("native_post_commands", "command_id"), rows("audits"), rows("outbox", "event_id")
    need(len(commands) == len(sources), "Native command population differs")
    expected_audits, expected_outbox = set(), set()

    def event(
        aid: str, oid: str, source_id: str, action: str, actor: str, metadata: dict[str, Any], native: bool = False
    ) -> None:
        expected_audits.add(aid)
        expected_outbox.add(oid)
        a, o = audits[aid], outbox[oid]
        scoped(o)
        need(
            a["object_id"] == o["aggregate_id"] == source_id
            and a["actor_user_id"] == actor
            and a["object_type"] == o["aggregate_type"] == ("finance_posting" if native else "operational_finance")
            and a["action"] == o["event_type"] == action
            and a["metadata_json"] == metadata
            and o["payload"] == {**metadata, "audit_event_id": aid},
            "Original event custody differs",
        )

    for price in prices.values():
        for prefix, action, actor_key in (
            ("", "price_registered", "preparer_id"),
            ("approve_", "price_approved", "approver_id"),
        ):
            event(
                price[prefix + "audit_id"],
                price[prefix + "outbox_id"],
                price["id"],
                "project_billing_" + action,
                price[actor_key],
                {"source_digest": price["source_digest"]},
            )
    for source in sources:
        scoped(source)
        need(type(source["phase"]) is int and source["phase"] == 2, "Incomplete source refused")
        payload, entry, effect = source["payload"], entries[source["entry_id"]], effects[source["effect_id"]]
        need(number(source["amount_minor"]) == number(payload["amount_minor"]), "Source amount projection differs")
        need(
            entry["entry_number"] == source["id"].upper()
            and entry["period_id"] == selected["period_id"]
            and entry["status"] == "Validated"
            and entry["organization_code"] == selected["scope"]["organization_code"]
            and entry["entity_code"] == selected["scope"]["entity_code"],
            "Native header differs",
        )
        scoped(entry)
        scoped(effect)
        need(
            len({source["preparer_id"], source["reviewer_id"], source["poster_id"]}) == 3
            and all(type(source[k]) is str and bool(source[k]) for k in ("preparer_id", "reviewer_id", "poster_id"))
            and entry["preparer_actor_id"] == source["preparer_id"]
            and entry["validator_actor_id"] == source["reviewer_id"]
            and effect["posted_actor_id"] == source["poster_id"],
            "Three-human custody differs",
        )
        need(
            effect["entry_id"] == entry["id"] == effect["source_id"]
            and effect["source_kind"] == "Manual"
            and effect["reverses_effect_id"] is None
            and effect["purpose"] == "operational_posting",
            "Detached native effect",
        )
        selected_lines = sorted(
            [line for line in lines.values() if line["entry_id"] == entry["id"]], key=lambda line: line["line_number"]
        )
        need(
            2 <= len(selected_lines) <= 1000
            and len({number(line["line_number"]) for line in selected_lines}) == len(selected_lines),
            "Native line population differs",
        )
        projected = [
            {k: line[k] for k in ("line_number", "account_id", "description", "debit_minor", "credit_minor")}
            | {"dimensions": attached[line["id"]]}
            for line in selected_lines
        ]
        for line in projected:
            debit, credit = number(line["debit_minor"]), number(line["credit_minor"])
            need((debit > 0) != (credit > 0), "Native line direction differs")
        need(
            sum(line["debit_minor"] for line in projected) == sum(line["credit_minor"] for line in projected),
            "Native double entry differs",
        )
        snapshot = {
            "schema_version": "finance-entry-review-v1",
            "entry": {k: entry[k] for k in HEADER},
            "lines": projected,
        }
        need(
            snapshot == effect["snapshot_json"]
            and sha(snapshot)
            == effect["validation_digest"]
            == payload["validation_digest"]
            == entry["validation_digest"],
            "Original native seal differs",
        )
        need(all(entry[k] == effect[k] == w["monetary_policy"][k] for k in POLICY), "Original native policy differs")
        if source["id"] in plans:
            need(
                payload["snapshot"] == snapshot
                and payload["plan_digest"] == sha({k: v for k, v in payload.items() if k != "plan_digest"}),
                "Original public source seal differs",
            )
        ack = [c for c in commands.values() if c["result_json"]["id"] == effect["id"]]
        need(len(ack) == 1, "Native ACK/effect bijection differs")
        command = ack[0]
        scoped(command)
        result = {k: v for k, v in effect.items() if k not in ("tenant_id", "snapshot_json")} | {"snapshot": snapshot}
        need(
            command["operation"] == "post"
            and command["actor_id"] == source["poster_id"]
            and command["result_json"] == result
            and command["request_digest"]
            == sha(
                {
                    "operation": "post",
                    "actor_id": source["poster_id"],
                    "workspace_id": scope["workspace_id"],
                    "entry_id": entry["id"],
                    "expected_validation_digest": effect["validation_digest"],
                    "reason": effect["reason"],
                }
            ),
            "Original acknowledged command differs",
        )
        event(
            effect["audit_event_id"],
            effect["outbox_event_id"],
            effect["id"],
            "finance_entry_posted",
            source["poster_id"],
            {"entry_id": entry["id"], "content_digest": effect["validation_digest"]},
            True,
        )
        actions = (
            ("project_billing_prepared", "project_billing_reviewed", "project_billing_posted")
            if source["id"] in plans
            else (
                "people_payrun_prepared" if source is wage else "people_payment_prepared",
                "people_plan_reviewed",
                "people_plan_posted",
            )
        )
        for prefix, action, actor_key in zip(
            ("", "review_", "post_"), actions, ("preparer_id", "reviewer_id", "poster_id"), strict=True
        ):
            event(
                source[prefix + "audit_id"],
                source[prefix + "outbox_id"],
                source["id"],
                action,
                source[actor_key],
                {"source_digest": payload["plan_digest"]},
            )

        def expected(
            code: str,
            role: str,
            debit: int,
            credit: int,
            project: str | None = None,
            chart_id: str = journals[entry["journal_id"]]["chart_id"],
        ) -> tuple[Any, ...]:
            found = [
                a
                for a in accounts.values()
                if a["account_code"] == code
                and a["chart_id"] == chart_id
                and a["workspace_id"] == scope["workspace_id"]
            ]
            need(len(found) == 1 and found[0]["account_type"] == role, "Original account role differs")
            dims = () if project is None else ((projects[project]["dimension_id"], projects[project]["value_id"]),)
            return found[0]["id"], number(debit), number(credit), dims

        if source is wage:
            wanted = [
                expected(w["expense_account_code"], "Expense", v, 0, p) for p, v in w["project_minor"].items() if v
            ]
            wanted.append(expected(w["liability_account_code"], "Liability", 0, w["amount_minor"]))
        elif source is invoice:
            wanted = [expected(bill["receivable_account_code"], "Asset", bill["amount_minor"], 0)]
            wanted.extend(
                expected(bill["revenue_account_code"], "Income", 0, v, p) for p, v in independent_revenue.items()
            )
        elif source["id"] in cash:
            need(source["payrun_id"] == wage["id"], "Foreign wage cash source")
            wanted = [
                expected(w["liability_account_code"], "Liability", source["amount_minor"], 0),
                expected(w["cash_account_code"], "Asset", 0, source["amount_minor"]),
            ]
        else:
            need(source["parent_id"] == invoice["id"] and source["kind"] == "Collection", "Foreign AR cash source")
            wanted = [
                expected(bill["cash_account_code"], "Asset", source["amount_minor"], 0),
                expected(bill["receivable_account_code"], "Asset", 0, source["amount_minor"]),
            ]
        actual = [
            (line["account_id"], line["debit_minor"], line["credit_minor"], tuple(sorted(line["dimensions"].items())))
            for line in projected
        ]
        need(sorted(actual) == sorted(wanted), "Original independent ledger roles/amounts/Project membership differ")
    need(set(audits) == expected_audits and set(outbox) == expected_outbox, "Original event population differs")
    need(
        report["source_membership"]
        == [
            {
                "id": s["id"],
                "plan_digest": s["payload"]["plan_digest"],
                "entry_id": s["entry_id"],
                "effect_id": s["effect_id"],
                "validation_digest": s["payload"]["validation_digest"],
            }
            for s in sorted(sources, key=lambda s: s["id"])
        ],
        "Reported source membership differs",
    )
    project = projects[selected["project_id"]]
    need(
        report["project"] == {k: project[k] for k in ("id", "project_code", "dimension_id", "value_id")},
        "Reported Project differs",
    )
    cost, revenue = w["project_minor"][project["id"]], independent_revenue[project["id"]]
    need(
        report["project_totals"]
        == {"wage_cost_minor": str(cost), "revenue_minor": str(revenue), "source_margin_minor": str(revenue - cost)},
        "Reported Project arithmetic differs",
    )
    known = {wage["entry_id"], invoice["entry_id"]}
    scanned = {
        line["id"]
        for line in lines.values()
        if line["entry_id"] in known
        and accounts[line["account_id"]]["account_type"] in ("Expense", "Income")
        and attached[line["id"]] == {project["dimension_id"]: project["value_id"]}
    }
    population = raw["project_ledger"]
    need(
        len(population) == len(scanned)
        and {line["id"] for line in population} == scanned
        and all(
            line["tenant_id"] == scope["tenant_id"]
            and line["entry_id"] in known
            and all(line[k] == lines[line["id"]][k] for k in ("entry_id", "account_id", "debit_minor", "credit_minor"))
            for line in population
        ),
        "Unknown/missing/altered posted Project population",
    )
    paid, received = (
        sum(number(s["amount_minor"]) for s in cash.values()),
        sum(number(s["amount_minor"]) for s in plans.values() if s is not invoice),
    )
    need(paid <= w["amount_minor"] and received <= bill["amount_minor"], "Whole-source cash exceeds source")
    need(
        report["whole_source_settlement"]
        == {
            "wage_accrued_minor": str(w["amount_minor"]),
            "wage_paid_minor": str(paid),
            "wage_liability_minor": str(w["amount_minor"] - paid),
            "invoice_minor": str(bill["amount_minor"]),
            "collected_minor": str(received),
            "ar_outstanding_minor": str(bill["amount_minor"] - received),
            "per_project_cash_allocated": False,
        },
        "Whole-source settlement arithmetic differs",
    )
    ar, receipts, allocations = raw["ar_invoice"], rows("ar_receipts"), raw["ar_allocations"]
    scoped(ar)
    need(
        ar["id"] == invoice["ar_invoice_id"]
        and ar["pb_owner_id"] == invoice["id"]
        and ar["total_minor"] == bill["amount_minor"]
        and ar["allocated_minor"] == received
        and ar["status"]
        == ("Paid" if received == bill["amount_minor"] else "PartiallyPaid" if received else "Approved"),
        "Native AR owner/settlement differs",
    )
    collections = [s for s in plans.values() if s is not invoice]
    need(
        set(receipts) == {s["receipt_id"] for s in collections} and len(allocations) == len(collections),
        "Native AR receipt/allocation population differs",
    )
    for s in collections:
        receipt = receipts[s["receipt_id"]]
        scoped(receipt)
        found = [a for a in allocations if a["receipt_id"] == receipt["id"]]
        need(
            receipt["pb_owner_id"] == s["id"]
            and receipt["status"] == "Posted"
            and receipt["posted_by"] == s["poster_id"]
            and receipt["amount_minor"] == s["amount_minor"]
            and len(found) == 1
            and found[0]["tenant_id"] == scope["tenant_id"]
            and found[0]["invoice_id"] == ar["id"]
            and found[0]["amount_minor"] == s["amount_minor"],
            "Native Cash/AR source bijection differs",
        )
    return {
        "schema_version": "project-source-independent-oracle-v1",
        "qualified_scope": scope,
        "project_totals": report["project_totals"],
        "whole_source_settlement": report["whole_source_settlement"],
        "source_effect_count": len(effects),
        "whole_approved_time_count": len(times),
        "report_digest": report["report_digest"],
        "evidence_digest": proof["evidence_digest"],
        "private_earnings_formula_recomputed": False,
        "current_sql_authority_proven": False,
        "audit_chain_recomputed": False,
        "per_project_cash_allocated": False,
        "comprehensive_project_pnl": False,
        "statutory_country_packs": 0,
        "performance_comparison_accepted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    need(re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256) is not None, "Separately trusted raw SHA256 required")
    need(
        args.output.resolve() != args.evidence.resolve() and not args.output.exists(), "Fresh distinct output required"
    )
    with args.evidence.open("rb") as handle:
        original = handle.read(MAX_BYTES + 1)
    need(
        len(original) <= MAX_BYTES and hashlib.sha256(original).hexdigest() == args.expected_sha256,
        "Original raw byte anchor differs",
    )
    result = verify(
        json.loads(
            original,
            object_pairs_hook=pairs,
            parse_float=lambda _: (_ for _ in ()).throw(ValueError("Float refused")),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite refused")),
        )
    )
    result.update(raw_sha256=args.expected_sha256, raw_bytes=len(original), raw_export_anchor=True)
    with args.output.open("x", encoding="utf8") as handle:
        handle.write(canonical(result).decode("utf8") + "\n")


if __name__ == "__main__":
    main()
