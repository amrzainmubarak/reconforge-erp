"""Independent standard-library project-minute price oracle; no app imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def integer(value: Any, *, positive: bool = False, maximum: int = 4_500_000_000_000_000_000) -> int:
    if type(value) is str:
        require(re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None, "Canonical minor-unit string required")
        value = int(value)
    require(
        type(value) is int and (1 if positive else 0) <= value <= maximum, "Exact bounded nonboolean integer required"
    )
    return value


def normalize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        if key == "observed_native_balances":
            result = {}
            for name, amount in value.items():
                if type(amount) is str:
                    require(
                        re.fullmatch(r"0|-?[1-9][0-9]{0,18}", amount) is not None,
                        "Canonical signed minor string required",
                    )
                    amount = int(amount)
                require(
                    type(amount) is int and abs(amount) <= 4_500_000_000_000_000_000,
                    "Exact signed source balance required",
                )
                result[name] = amount
            return result
        return {
            name: normalize(item, "amount_minor" if key == "project_minor" else name) for name, item in value.items()
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return integer(value) if key.endswith("_minor") else value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def day(value: Any) -> str:
    require(type(value) is str and date.fromisoformat(value).isoformat() == value, "Canonical business date required")
    return value


def verify_allocation(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = normalize(evidence)
    require(evidence["schema_version"] == "project-billing-allocation-evidence-v1", "Unknown project billing evidence")
    scope = evidence["scope"]
    require(
        type(evidence["currency_code"]) is str and re.fullmatch(r"[A-Z]{3}", evidence["currency_code"]) is not None,
        "Canonical explicit currency required",
    )
    require(
        type(evidence["customer_code"]) is str
        and re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", evidence["customer_code"]) is not None,
        "Canonical customer required",
    )
    require(
        set(scope) == {"tenant_id", "workspace_id", "organization_id", "legal_entity_id"}
        and all(type(value) is str and value for value in scope.values()),
        "Original qualified scope required",
    )
    prices = evidence["prices"]
    times = evidence["times"]
    registry = evidence["registry_snapshot"]
    require(
        set(registry)
        == {"currencies", "published_at", "registry_version", "schema_version", "source", "source_url", "digest"}
        and type(registry["schema_version"]) is int
        and registry["schema_version"] == 1,
        "Closed original registry snapshot required",
    )
    require(
        registry["digest"] == digest({key: value for key, value in registry.items() if key != "digest"}),
        "Original registry digest differs",
    )
    currencies = registry["currencies"]
    require(type(currencies) is list and 1 <= len(currencies) <= 1000, "Bounded registry currencies required")
    codes = [row["code"] for row in currencies]
    require(
        codes == sorted(codes) and len(set(codes)) == len(codes), "Original registry currencies duplicate or unordered"
    )
    matches = [row for row in currencies if row["code"] == evidence["currency_code"]]
    require(
        len(matches) == 1 and matches[0]["rounding_policy"] == "ROUND_HALF_UP",
        "Supported captured native currency rounding required",
    )
    precision = integer(matches[0]["minor_units"], maximum=8)
    monetary_policy = {
        "currency_code": evidence["currency_code"],
        "currency_precision": precision,
        "currency_rounding_policy": matches[0]["rounding_policy"],
        "currency_registry_version": registry["registry_version"],
        "currency_registry_digest": registry["digest"],
    }
    require(
        type(prices) is list and 1 <= len(prices) <= 999 and type(times) is list and 1 <= len(times) <= 1000,
        "Bounded source population required",
    )
    price_ids = set()
    for price in prices:
        require(
            price["id"] not in price_ids and all(price[key] == value for key, value in scope.items()),
            "Duplicate or foreign price",
        )
        require(
            price["customer_code"] == evidence["customer_code"] and price["currency_code"] == evidence["currency_code"],
            "Foreign customer/currency",
        )
        require(
            price["approver_id"] and price["preparer_id"] and price["approver_id"] != price["preparer_id"],
            "Independent price approval required",
        )
        integer(price["hourly_price_minor"], positive=True)
        require(price["monetary_policy"] == monetary_policy, "Price captured native policy differs")
        require(day(price["valid_from"]) <= day(price["valid_through"]), "Canonical ordered price dates required")
        for other in prices:
            if other is not price and other["project_id"] == price["project_id"]:
                require(
                    not (
                        price["valid_from"] <= other["valid_through"] and other["valid_from"] <= price["valid_through"]
                    ),
                    "Effective project price versions overlap",
                )
        require(price["source_digest"] == digest(price["source_json"]), "Price source seal differs")
        require(
            all(
                price["source_json"][key] == price[key]
                for key in (
                    *scope,
                    "id",
                    "customer_code",
                    "currency_code",
                    "project_id",
                    "hourly_price_minor",
                    "valid_from",
                    "valid_through",
                    "preparer_id",
                    "dimension_id",
                    "value_id",
                    "monetary_policy",
                )
            ),
            "Price projection differs",
        )
        price_ids.add(price["id"])
    amounts: dict[str, Fraction] = {}
    minutes: dict[str, int] = {}
    time_ids = set()
    employee_days = set()
    selected_prices = set()
    sources = []
    for source in sorted(times, key=lambda row: row["id"]):
        require(
            source["id"] not in time_ids and all(source[key] == value for key, value in scope.items()),
            "Duplicate or foreign whole approved time",
        )
        require(
            source["approver_id"] and source["approver_id"] != source["submitter_id"],
            "Independent time approval required",
        )
        require(
            source["source_digest"] == digest({**source["request_json"], "employment_id": source["employment_id"]}),
            "Original time seal differs",
        )
        require(
            all(source[key] == source["request_json"][key] for key in ("employee_id", "business_date", "lines")),
            "Time projection differs",
        )
        qualified_day = (source["employee_id"], source["business_date"])
        day(source["business_date"])
        require(qualified_day not in employee_days, "Duplicate employee business date")
        employee_days.add(qualified_day)
        time_ids.add(source["id"])
        require(type(source["lines"]) is list and 1 <= len(source["lines"]) <= 128, "Bounded time intervals required")
        previous = -1
        for line in sorted(source["lines"], key=lambda row: row["start_minute"]):
            start = integer(line["start_minute"], maximum=1439)
            end = integer(line["end_minute"], positive=True, maximum=1440)
            require(previous <= start < end, "Positive nonoverlapping original minute interval required")
            previous = end
            candidates = [
                price
                for price in prices
                if price["project_id"] == line["project_id"]
                and price["valid_from"] <= source["business_date"] <= price["valid_through"]
            ]
            require(len(candidates) == 1, "One effective approved project price required")
            price = candidates[0]
            selected_prices.add(price["id"])
            interval = end - start
            project = line["project_id"]
            amounts[project] = amounts.get(project, Fraction()) + Fraction(price["hourly_price_minor"] * interval, 60)
            minutes[project] = minutes.get(project, 0) + interval
            sources.append(
                {
                    "time_id": source["id"],
                    "time_digest": source["source_digest"],
                    "project_id": project,
                    "start_minute": start,
                    "end_minute": end,
                    "minutes": interval,
                    "price_id": price["id"],
                    "price_digest": price["source_digest"],
                    "hourly_price_minor": price["hourly_price_minor"],
                }
            )
    require(selected_prices == price_ids, "Unused price version supplied")
    result = {}
    for project, exact in sorted(amounts.items()):
        whole, remainder = divmod(exact.numerator, exact.denominator)
        amount = whole + int(remainder * 2 >= exact.denominator)
        result[project] = integer(amount, positive=True)
    total = integer(sum(result.values()), positive=True)
    expected = {
        "contract_version": "project-time-billing-v1",
        "rounding": "captured-currency-per-project-v1",
        "currency_code": evidence["currency_code"],
        "monetary_policy": monetary_policy,
        "time_ids": sorted(time_ids),
        "price_ids": sorted(selected_prices),
        "sources": sources,
        "project_minutes": dict(sorted(minutes.items())),
        "project_minor": result,
        "amount_minor": total,
        "ar_lines": [
            {
                "project_id": project,
                "quantity": "1",
                "unit_price_minor": amount,
                "line_total_minor": amount,
                "tax_minor": 0,
            }
            for project, amount in result.items()
        ],
    }
    require(evidence["calculation"] == expected, "Independent exact project allocation differs")
    return {
        "schema_version": "project-billing-independent-allocation-v1",
        "accepted_calculation": True,
        "amount_minor": total,
        "project_minor": result,
        "whole_time_entries": len(time_ids),
        "native_ar_gl_proven": False,
        "country_tax_supported": 0,
        "performance_comparison_accepted": False,
    }


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
LINE = ("line_number", "account_id", "description", "debit_minor", "credit_minor", "dimensions")
TABLES = {
    "plans",
    "prices",
    "entries",
    "effects",
    "entry_lines",
    "entry_dimensions",
    "account_pins",
    "accounts",
    "projects",
    "dimensions",
    "dimension_values",
    "times",
    "time_claims",
    "claim_events",
    "claim_heads",
    "ar_invoices",
    "ar_lines",
    "ar_receipts",
    "ar_allocations",
    "commands",
    "audits",
    "outbox",
    "customers",
    "organizations",
    "entities",
    "journals",
    "periods",
}


def unique(rows: list[dict[str, Any]], *fields: str) -> dict[Any, dict[str, Any]]:
    keys = [row[fields[0]] if len(fields) == 1 else tuple(row[field] for field in fields) for row in rows]
    require(len(keys) == len(set(keys)), "Duplicate original native/source row")
    return dict(zip(keys, rows, strict=True))


def verify(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = normalize(evidence)
    require(evidence["schema_version"] == "project-billing-evidence-v1", "Unknown native billing evidence")
    scope, raw, invoice = evidence["qualified_scope"], evidence["original_rows"], evidence["invoice"]
    require(
        set(scope) == {"tenant_id", "workspace_id", "organization_id", "legal_entity_id"}
        and all(type(value) is str and value for value in scope.values()),
        "Exact qualified source required",
    )
    require(type(raw) is dict and set(raw) == TABLES, "Closed original native table population required")
    for rows in raw.values():
        require(type(rows) is list and len(rows) <= 20_000, "Bounded original table required")
        for row in rows:
            require(type(row) is dict and row["tenant_id"] == scope["tenant_id"], "Foreign native tenant")
            require(
                all(
                    value is None or type(value) is str and value
                    for key, value in row.items()
                    if key == "id" or key.endswith("_id")
                ),
                "Canonical original identity strings required",
            )
            if "sequence" in row:
                integer(row["sequence"], positive=True)
            if "currency_precision" in row:
                integer(row["currency_precision"], maximum=8)
            require(
                all(row[key] == value for key, value in scope.items() if key in row), "Foreign original native scope"
            )
            if "application_workspace_id" in row:
                require(row["application_workspace_id"] == scope["workspace_id"], "Foreign directory workspace")
    plans = unique(raw["plans"], "id")
    require(2 <= len(plans) <= 201 and invoice["id"] in plans, "Original invoice and partial cash sources required")
    p = plans[invoice["id"]]
    require(
        p["kind"] == "Invoice" and p["parent_id"] is None and p["receipt_id"] is None,
        "Original Invoice source required",
    )

    def view(plan: dict[str, Any]) -> dict[str, Any]:
        return {
            **plan["payload"],
            "phase": plan["phase"],
            "status": ["Prepared", "Reviewed", "Posted", "Cancelled"][plan["phase"]],
            "reviewer_id": plan["reviewer_id"],
            "posted_actor_id": plan["poster_id"],
            "posting_effect_id": plan["effect_id"],
            "receipt_id": plan["receipt_id"],
        }

    require(invoice == view(p), "Original invoice view differs")
    projected_collections = unique(evidence["collections"], "id")
    require(
        set(projected_collections) == {row["id"] for row in plans.values() if row["kind"] == "Collection"}
        and all(row == view(plans[identifier]) for identifier, row in projected_collections.items()),
        "Original cash source views differ",
    )
    for row in raw["prices"]:
        require(
            all(
                row[key] == row["source_json"][key]
                for key in (
                    "id",
                    *scope,
                    "project_id",
                    "customer_code",
                    "valid_from",
                    "valid_through",
                    "currency_code",
                    "hourly_price_minor",
                    "preparer_id",
                )
            ),
            "Raw original price projection differs",
        )
    prices = [
        {
            **row["source_json"],
            "approver_id": row["approver_id"],
            "source_digest": row["source_digest"],
            "source_json": row["source_json"],
        }
        for row in raw["prices"]
    ]
    allocation = verify_allocation(
        {
            "schema_version": "project-billing-allocation-evidence-v1",
            "scope": scope,
            "customer_code": invoice["customer_code"],
            "currency_code": invoice["monetary_policy"]["currency_code"],
            "prices": prices,
            "times": raw["times"],
            "registry_snapshot": evidence["registry_snapshot"],
            "calculation": invoice["calculation"],
        }
    )
    total, projects = allocation["amount_minor"], unique(raw["projects"], "id")
    require(set(projects) == set(allocation["project_minor"]), "Exact original Project population required")
    require(evidence["times"] == raw["times"] and evidence["prices"] == raw["prices"], "Source projections differ")
    customers = unique(raw["customers"], "id")
    require(set(customers) == {invoice["customer_id"]}, "Original native customer required")
    customer = customers[invoice["customer_id"]]
    require(
        customer["customer_code"] == invoice["customer_code"]
        and customer["currency_code"] == invoice["monetary_policy"]["currency_code"],
        "Native customer/currency differs",
    )
    orgs, entities = unique(raw["organizations"], "id"), unique(raw["entities"], "id")
    require(
        set(orgs) == {scope["organization_id"]} and set(entities) == {scope["legal_entity_id"]},
        "Original directory population differs",
    )
    require(
        orgs[scope["organization_id"]]["organization_code"] == invoice["organization_code"]
        and entities[scope["legal_entity_id"]]["entity_code"] == invoice["entity_code"]
        and entities[scope["legal_entity_id"]]["currency_code"] == invoice["monetary_policy"]["currency_code"],
        "Original entity currency or code differs",
    )
    pins = unique(raw["account_pins"], "role")
    require(set(pins) == {"receivable", "revenue", "cash"}, "Exactly three source account roles required")
    accounts = unique(raw["accounts"], "id")
    require(set(accounts) == {pin["account_id"] for pin in pins.values()}, "Native account population differs")
    for role, pin in pins.items():
        account = accounts[pin["account_id"]]
        require(
            pin["invoice_id"] == p["id"] and pin["account_code"] == invoice[role + "_account_code"],
            "Original account code role differs",
        )
        require(
            all(account[key] == pin[key] for key in ("workspace_id", "chart_id", "account_code", "account_type")),
            "Native account pin differs",
        )
        require(
            account["account_type"] == ("Income" if role == "revenue" else "Asset"),
            "Native account classification differs",
        )
    dimensions, values = unique(raw["dimensions"], "id"), unique(raw["dimension_values"], "id")
    require(
        set(dimensions) == {row["dimension_id"] for row in projects.values()}
        and set(values) == {row["value_id"] for row in projects.values()},
        "Exact native Project dimension population required",
    )
    for project in projects.values():
        dimension, value = dimensions[project["dimension_id"]], values[project["value_id"]]
        require(
            dimension["dimension_type"] == "Project"
            and dimension["active"] is True
            and value["active"] is True
            and dimension["dimension_code"] == project["dimension_code"]
            and value["value_code"] == project["value_code"]
            and value["dimension_id"] == dimension["id"]
            and dimension["organization_code"] in {"", invoice["organization_code"]},
            "Native Project identity differs",
        )
        for price in prices:
            if price["project_id"] == project["id"]:
                require(
                    (price["dimension_id"], price["value_id"]) == (dimension["id"], value["id"]),
                    "Price Project dimension custody differs",
                )
    entries, effects = unique(raw["entries"], "id"), unique(raw["effects"], "id")
    require(
        set(entries) == {row["entry_id"] for row in plans.values()}
        and set(effects) == {row["effect_id"] for row in plans.values()},
        "Exact original financial membership required",
    )
    unique(raw["entry_lines"], "id")
    unique(raw["entry_lines"], "entry_id", "line_number")
    unique(raw["entry_dimensions"], "entry_line_id", "dimension_id")
    journals, periods = unique(raw["journals"], "id"), unique(raw["periods"], "id")
    require(
        set(journals) == {row["journal_id"] for row in entries.values()}
        and set(periods) == {row["period_id"] for row in entries.values()},
        "Original journal/period population differs",
    )
    balances = {row["account_code"]: 0 for row in accounts.values()}
    audited, dispatched = set(), set()
    audits, outbox = unique(raw["audits"], "id"), unique(raw["outbox"], "event_id")

    def trace(
        aid: str, oid: str, actor: str, kind: str, identifier: str, action: str, metadata: dict[str, Any]
    ) -> None:
        audit, event = audits[aid], outbox[oid]
        require(
            (audit["actor_user_id"], audit["object_type"], audit["object_id"], audit["action"], audit["metadata_json"])
            == (actor, kind, identifier, action, metadata),
            "Original audit membership differs",
        )
        require(
            (event["aggregate_type"], event["aggregate_id"], event["event_type"], event["payload"])
            == (kind, identifier, action, {**metadata, "audit_event_id": aid}),
            "Original outbox membership differs",
        )
        audited.add(aid)
        dispatched.add(oid)

    for price in raw["prices"]:
        for prefix, actor, action in (
            ("", price["preparer_id"], "price_registered"),
            ("approve_", price["approver_id"], "price_approved"),
        ):
            trace(
                price[prefix + "audit_id"],
                price[prefix + "outbox_id"],
                actor,
                "operational_finance",
                price["id"],
                "project_billing_" + action,
                {"source_digest": price["source_digest"]},
            )
    used_lines, used_dimensions = set(), set()
    for plan in plans.values():
        require(
            plan["kind"] in {"Invoice", "Collection"}
            and plan["payload"]["schema_version"]
            == ("project-invoice-v1" if plan["kind"] == "Invoice" else "project-collection-v1")
            and re.fullmatch(r"PB1-[0-9a-f]{32}" if plan["kind"] == "Invoice" else r"PB1C-[0-9a-f]{32}", plan["id"])
            is not None,
            "Versioned original invoice/cash identity required",
        )
        require(
            type(plan["phase"]) is int
            and plan["phase"] == 2
            and len({plan["preparer_id"], plan["reviewer_id"], plan["poster_id"]}) == 3
            and all(plan[key] for key in ("preparer_id", "reviewer_id", "poster_id")),
            "Three distinct posted source humans required",
        )
        payload, entry, effect = plan["payload"], entries[plan["entry_id"]], effects[plan["effect_id"]]
        require(
            payload["plan_digest"] == digest({key: value for key, value in payload.items() if key != "plan_digest"})
            and payload["id"] == plan["id"]
            and payload["entry_id"] == entry["id"]
            and integer(plan["amount_minor"], positive=True) == payload["amount_minor"],
            "Original immutable plan seal differs",
        )
        require(
            all(payload[key] == value for key, value in scope.items() if key != "tenant_id"),
            "Foreign payload source scope",
        )
        snapshot = payload["snapshot"]
        require(
            set(snapshot) == {"schema_version", "entry", "lines"}
            and snapshot["schema_version"] == "finance-entry-review-v1"
            and set(snapshot["entry"]) == set(HEADER)
            and snapshot["entry"] == {key: entry[key] for key in HEADER}
            and digest(snapshot) == payload["validation_digest"] == entry["validation_digest"],
            "Independent original native snapshot differs",
        )
        require(
            entry["entry_number"] == plan["id"].upper()
            and entry["external_reference"] == plan["id"]
            and entry["source_type"] == "Manual"
            and entry["status"] == "Validated"
            and entry["validator_actor_id"] == plan["reviewer_id"]
            and entry["preparer_actor_id"] == plan["preparer_id"]
            and entry["reverses_posting_id"] is None
            and entry["validation_contract_version"] == "finance-entry-review-v1",
            "Native original status or authority differs",
        )
        require(
            all(entry[key] == value for key, value in invoice["monetary_policy"].items()),
            "Native currency policy differs",
        )
        require(
            periods[entry["period_id"]]["start_date"]
            <= day(entry["posting_date"])
            <= periods[entry["period_id"]]["end_date"],
            "Original posting period differs",
        )
        require(
            all(pin["chart_id"] == journals[entry["journal_id"]]["chart_id"] for pin in pins.values()),
            "Original journal chart differs",
        )
        require(
            effect["entry_id"] == entry["id"]
            and effect["source_id"] == entry["id"]
            and effect["source_kind"] == "Manual"
            and effect["purpose"] == "operational_posting"
            and effect["reverses_effect_id"] is None
            and effect["posted_actor_id"] == plan["poster_id"]
            and effect["snapshot_json"] == snapshot
            and effect["validation_digest"] == payload["validation_digest"],
            "Exact original native effect differs",
        )
        require(
            all(effect[key] == value for key, value in invoice["monetary_policy"].items()),
            "Native effect currency policy differs",
        )
        public = next(row for row in evidence["native_effects"] if row["id"] == effect["id"])
        require(
            public
            == {
                **{key: value for key, value in effect.items() if key not in {"tenant_id", "snapshot_json"}},
                "snapshot": snapshot,
            },
            "Public native effect projection differs",
        )
        trace(
            effect["audit_event_id"],
            effect["outbox_event_id"],
            plan["poster_id"],
            "finance_posting",
            effect["id"],
            "finance_entry_posted",
            {"entry_id": entry["id"], "content_digest": payload["validation_digest"]},
        )
        for prefix, actor, action in (
            ("", plan["preparer_id"], "prepared"),
            ("review_", plan["reviewer_id"], "reviewed"),
            ("post_", plan["poster_id"], "posted"),
        ):
            trace(
                plan[prefix + "audit_id"],
                plan[prefix + "outbox_id"],
                actor,
                "operational_finance",
                plan["id"],
                "project_billing_" + action,
                {"source_digest": payload["plan_digest"]},
            )
        expected = [(pins["receivable"]["account_id"], total, 0, {})]
        if plan["kind"] == "Invoice":
            require(plan["id"] == p["id"] and plan["amount_minor"] == total, "Unexpected second native invoice")
            expected += [
                (
                    pins["revenue"]["account_id"],
                    0,
                    amount,
                    {projects[project]["dimension_id"]: projects[project]["value_id"]},
                )
                for project, amount in sorted(allocation["project_minor"].items())
            ]
        else:
            require(
                plan["parent_id"] == p["id"]
                and plan["ar_invoice_id"] == p["ar_invoice_id"]
                and payload["parent_digest"] == invoice["plan_digest"],
                "Foreign original cash source",
            )
            expected = [
                (pins["cash"]["account_id"], plan["amount_minor"], 0, {}),
                (pins["receivable"]["account_id"], 0, plan["amount_minor"], {}),
            ]
        lines = sorted(
            (row for row in raw["entry_lines"] if row["entry_id"] == entry["id"]), key=lambda row: row["line_number"]
        )
        require(len(lines) == len(expected) == len(snapshot["lines"]), "Exact native line population differs")
        for position, (line, want, sealed) in enumerate(zip(lines, expected, snapshot["lines"], strict=True), 1):
            dims = {
                row["dimension_id"]: row["dimension_value_id"]
                for row in raw["entry_dimensions"]
                if row["entry_line_id"] == line["id"]
            }
            require(
                type(line["line_number"]) is int
                and line["line_number"] == position
                and (line["account_id"], integer(line["debit_minor"]), integer(line["credit_minor"]), dims) == want
                and line["currency_code"] == invoice["monetary_policy"]["currency_code"],
                "Independent original GL amount/account/Project differs",
            )
            require(
                set(sealed) == set(LINE)
                and sealed == {**{key: line[key] for key in LINE if key != "dimensions"}, "dimensions": dims},
                "Native GL lines differ from retained snapshot",
            )
            balances[accounts[line["account_id"]]["account_code"]] += line["debit_minor"] - line["credit_minor"]
            used_lines.add(line["id"])
            used_dimensions.update((line["id"], key) for key in dims)
        require(
            entry["total_debit_minor"] == entry["total_credit_minor"] == plan["amount_minor"],
            "Native header totals differ",
        )
    require(
        used_lines == {row["id"] for row in raw["entry_lines"]}
        and used_dimensions == set(unique(raw["entry_dimensions"], "entry_line_id", "dimension_id")),
        "Detached original native GL row",
    )
    require(set(audits) == audited and set(outbox) == dispatched, "Detached original financial source event")
    require(len(evidence["native_effects"]) == len(effects), "Duplicate public original effect")
    collections = sorted(
        (row for row in plans.values() if row["kind"] == "Collection"),
        key=lambda row: row["payload"]["calculation"]["collected_after_minor"],
    )
    receipts, allocations = unique(raw["ar_receipts"], "id"), unique(raw["ar_allocations"], "receipt_id")
    require(
        set(receipts) == set(allocations) == {row["receipt_id"] for row in collections},
        "Exact original cash/AR membership required",
    )
    collected = 0
    for collection in collections:
        receipt, applied = receipts[collection["receipt_id"]], allocations[collection["receipt_id"]]
        amount = integer(collection["amount_minor"], positive=True)
        collected += amount
        require(
            collected <= total
            and collection["payload"]["calculation"]
            == {
                "amount_minor": amount,
                "collected_after_minor": collected,
                "outstanding_after_minor": total - collected,
            },
            "Original cumulative collection differs",
        )
        require(
            receipt["pb_owner_id"] == collection["id"]
            and receipt["amount_minor"] == applied["amount_minor"] == amount
            and applied["invoice_id"] == p["ar_invoice_id"]
            and receipt["customer_id"] == invoice["customer_id"]
            and receipt["status"] == "Posted"
            and receipt["receipt_date"] == collection["payload"]["posting_date"],
            "Native AR settlement differs",
        )
        require(
            receipt["receipt_number"] == collection["id"].upper()
            and receipt["created_by"] == receipt["posted_by"] == audits[collection["post_audit_id"]]["actor_label"],
            "Native cash actor/identifier differs",
        )
        require(
            all(receipt[key] == value for key, value in invoice["monetary_policy"].items()),
            "Native receipt policy differs",
        )
    native_ar = unique(raw["ar_invoices"], "id")
    require(set(native_ar) == {p["ar_invoice_id"]}, "Exact original native AR invoice required")
    ar = native_ar[p["ar_invoice_id"]]
    require(
        ar["pb_owner_id"] == p["id"]
        and ar["customer_id"] == invoice["customer_id"]
        and ar["subtotal_minor"] == ar["total_minor"] == total
        and ar["tax_minor"] == 0
        and ar["status"] == ("Paid" if collected == total else "PartiallyPaid"),
        "Native AR invoice amount/status differs",
    )
    require(
        ar["invoice_number"] == invoice["invoice_number"]
        and ar["invoice_date"] == invoice["posting_date"]
        and ar["due_date"] == invoice["due_date"]
        and ar["created_by"] == audits[p["audit_id"]]["actor_label"]
        and ar["approved_by"] == audits[p["post_audit_id"]]["actor_label"],
        "Original native AR dates/reference/humans differ",
    )
    require(all(ar[key] == value for key, value in invoice["monetary_policy"].items()), "Native invoice policy differs")
    require(len(raw["ar_lines"]) == len(allocation["project_minor"]), "Native AR line population differs")
    unique(raw["ar_lines"], "id")
    unique(raw["ar_lines"], "line_number")
    for number, (line, (project, amount)) in enumerate(
        zip(raw["ar_lines"], sorted(allocation["project_minor"].items()), strict=True), 1
    ):
        require(
            line["line_number"] == number
            and line["invoice_id"] == ar["id"]
            and line["description"] == project
            and Fraction(line["quantity"]) == 1
            and line["quantity_text"] == "1"
            and line["unit_price_minor"] == line["line_total_minor"] == amount
            and line["tax_minor"] == 0,
            "Original minute priced native AR line differs",
        )
    ar_view = evidence["ar_invoice"]
    require(
        all(
            ar_view[key] == ar[key]
            for key in (
                "id",
                "workspace_id",
                "organization_id",
                "legal_entity_id",
                "customer_id",
                "invoice_number",
                "total_minor",
                "tax_minor",
                "subtotal_minor",
                "status",
            )
        )
        and ar_view["allocated_minor"] == collected
        and ar_view["outstanding_minor"] == total - collected,
        "Native AR projection differs",
    )
    claims, heads = unique(raw["time_claims"], "time_id"), unique(raw["claim_heads"], "time_id")
    require(
        set(claims) == set(heads) == set(invoice["calculation"]["time_ids"]),
        "Exact whole-time original claim population required",
    )
    unique(raw["claim_events"], "id")
    unique(raw["claim_events"], "time_id", "sequence")
    require(
        len(raw["claim_events"]) == 2 * len(claims) and evidence["claims"] == raw["claim_events"],
        "Original claim event population differs",
    )
    times = unique(raw["times"], "id")
    for time_id, claim in claims.items():
        require(
            claim["invoice_id"] == p["id"] and claim["source_digest"] == times[time_id]["source_digest"],
            "Whole-time original claim differs",
        )
        events = [row for row in raw["claim_events"] if row["time_id"] == time_id]
        require(
            [(row["sequence"], row["operation"]) for row in events] == [(1, "Claim"), (2, "Consume")],
            "Consumed original claim chain differs",
        )
        for event, actor, prefix in zip(events, (p["preparer_id"], p["poster_id"]), ("", "post_"), strict=True):
            require(
                event["invoice_id"] == p["id"]
                and event["actor_id"] == actor
                and event["source_digest"] == claim["source_digest"]
                and event["audit_id"] == p[prefix + "audit_id"]
                and event["outbox_id"] == p[prefix + "outbox_id"],
                "Claim source/event custody differs",
            )
            require(
                event["id"]
                == "PBC-"
                + hashlib.sha256(
                    (scope["tenant_id"] + ":" + time_id + ":" + str(event["sequence"])).encode()
                ).hexdigest(),
                "Original claim event identity differs",
            )
        require(
            heads[time_id]["invoice_id"] == p["id"]
            and heads[time_id]["state"] == "Consumed"
            and heads[time_id]["sequence"] == 2,
            "Original claim head differs",
        )
    commands = unique(raw["commands"], "command_id")
    require(len(commands) == 2 * len(prices) + 3 * len(plans), "Exact retained original command population required")
    owners = {**plans, **unique(raw["prices"], "id")}
    operations: dict[str, set[str]] = {key: set() for key in owners}
    for command in commands.values():
        require(
            command["request_digest"]
            == digest({"operation": command["operation"], "request": command["request_json"]}),
            "Original command seal differs",
        )
        response = command["response_json"]
        owner = owners[response["id"]]
        operation = command["operation"]
        operations[owner["id"]].add(operation)
        actor = (
            owner["preparer_id"]
            if operation in {"manage", "prepare", "collect"}
            else owner["approver_id"]
            if operation == "approve_price"
            else owner["reviewer_id"]
            if operation == "review"
            else owner["poster_id"]
        )
        require(command["actor_id"] == actor, "Original command human differs")
        if "payload" in owner:
            require(
                all(response[key] == value for key, value in owner["payload"].items()),
                "Historical source command response differs",
            )
            phase = {"prepare": 0, "collect": 0, "review": 1, "post": 2}[operation]
            require(
                response["phase"] == phase
                and response["status"] == ["Prepared", "Reviewed", "Posted"][phase]
                and response["reviewer_id"] == (owner["reviewer_id"] if phase else None)
                and response["posted_actor_id"] == (owner["poster_id"] if phase == 2 else None)
                and response["posting_effect_id"] == (owner["effect_id"] if phase == 2 else None)
                and response["receipt_id"] == (owner["receipt_id"] if phase == 2 else None),
                "Original command response phase differs",
            )
            if operation in {"prepare", "collect"}:
                require(
                    command["request_json"] == owner["payload"]["command_request"],
                    "Original financial preparation request differs",
                )
            else:
                require(
                    command["request_json"]
                    == {"plan_id": owner["id"], "expected_plan_digest": owner["payload"]["plan_digest"]},
                    "Original reviewed/post request differs",
                )
        else:
            require(
                response["source_digest"] == owner["source_digest"]
                and all(response[key] == value for key, value in owner["source_json"].items()),
                "Original price command differs",
            )
            expected_request = (
                {
                    key: value
                    for key, value in owner["source_json"].items()
                    if key not in {"id", "tenant_id", "preparer_id", "dimension_id", "value_id", "monetary_policy"}
                }
                if operation == "manage"
                else {"price_id": owner["id"], "expected_digest": owner["source_digest"]}
            )
            require(
                command["request_json"] == expected_request
                and response["approver_id"] == (owner["approver_id"] if operation == "approve_price" else None)
                and response["status"] == ("Approved" if operation == "approve_price" else "Submitted"),
                "Original price request/approval phase differs",
            )
    for identifier, operations_seen in operations.items():
        owner = owners[identifier]
        want = (
            {"manage", "approve_price"}
            if "source_json" in owner
            else {"prepare" if owner["kind"] == "Invoice" else "collect", "review", "post"}
        )
        require(operations_seen == want, "Missing/duplicate original source command phase")
    require(
        balances == evidence["observed_native_balances"]
        and balances
        == {
            invoice["receivable_account_code"]: total - collected,
            invoice["revenue_account_code"]: -total,
            invoice["cash_account_code"]: collected,
        },
        "Independent native balance conservation differs",
    )
    return {
        "schema_version": "project-billing-independent-native-cycle-v1",
        "accepted_cycle": True,
        "scope": scope,
        "original_time_entries": len(claims),
        "native_effects": len(effects),
        "amount_minor": total,
        "project_minor": allocation["project_minor"],
        "collected_minor": collected,
        "outstanding_minor": total - collected,
        "native_balances": balances,
        "audit_chain_recomputed": False,
        "current_sql_authority_proven": False,
        "country_tax_supported": 0,
        "bank_transfer_proven": False,
        "performance_comparison_accepted": False,
    }


def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in values:
        require(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(
        re.fullmatch(r"[0-9a-f]{64}", args.expected_evidence_sha256) is not None,
        "Exact separately trusted raw SHA required",
    )
    require(
        not args.output.exists() and args.output.resolve() != args.evidence.resolve(),
        "Fresh distinct proof output required",
    )
    with args.evidence.open("rb") as stream:
        raw = stream.read(16_777_217)
    require(
        len(raw) <= 16_777_216 and hashlib.sha256(raw).hexdigest() == args.expected_evidence_sha256,
        "Original evidence trusted raw anchor differs",
    )

    def refuse(value: str) -> Any:
        raise ValueError("Noninteger JSON number refused")

    result = verify(json.loads(raw, object_pairs_hook=pairs, parse_float=refuse, parse_constant=refuse))
    result.update(raw_evidence_sha256=hashlib.sha256(raw).hexdigest(), raw_export_anchor=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(result) + "\n")


if __name__ == "__main__":
    main()
