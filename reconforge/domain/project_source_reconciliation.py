"""One Project's original governed wage/revenue ledger, never a new ledger."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, cast

from reconforge.domain.finance_posting import (
    FinancePostingError,
    digest_payload,
    make_entry_snapshot,
    text,
    validation_digest,
)
from reconforge.domain.people_project_payroll import PeopleScope


def refuse(message: str) -> None:
    raise FinancePostingError("project_reconciliation_invalid", message)


def require(condition: bool, message: str) -> None:
    if not condition:
        refuse(message)


def exact(value: object, *, positive: bool = False) -> int:
    require(
        type(value) is int and (1 if positive else 0) <= value <= 9_000_000_000_000_000_000,
        "Original amounts require exact bounded integer minor units.",
    )
    return cast(int, value)


@dataclass(frozen=True)
class ProjectSourceSelection:
    scope: PeopleScope
    project_id: str
    period_id: str
    payrun_id: str
    invoice_id: str

    def __post_init__(self) -> None:
        for field in ("project_id", "period_id", "payrun_id", "invoice_id"):
            text(getattr(self, field), field)
        require(
            self.payrun_id.startswith("HC1-") and self.invoice_id.startswith("PB1-"),
            "Select original governed payroll and project invoice sources.",
        )


def reconcile_project_sources(selection: ProjectSourceSelection, original: Mapping[str, Any]) -> dict[str, Any]:
    """Reconcile public original allocations with their exact native effects.

    The private earnings formula is not re-executed from this public export.
    Its original seal remains an opaque custody reference; native expense,
    Project allocation and consumed-time membership are independently checked.
    """
    qualified = original["qualified_scope"]
    expected_scope = {
        "tenant_id": qualified["tenant_id"],
        **{key: getattr(selection.scope, key) for key in ("workspace_id", "organization_id", "legal_entity_id")},
    }
    require(qualified == expected_scope, "Original qualified source scope differs.")

    def scoped(row: Mapping[str, Any]) -> None:
        require(
            all(row.get(key) == value for key, value in expected_scope.items()),
            "An original source belongs to another tenant or hierarchy.",
        )

    def table(name: str, key: str = "id") -> dict[str, dict[str, Any]]:
        rows = original[name]
        require(isinstance(rows, list) and len(rows) <= 20_000, "Original population is not bounded.")
        require(all(row.get("tenant_id") == qualified["tenant_id"] for row in rows), "Foreign native tenant row.")
        result = {row[key]: row for row in rows}
        require(len(result) == len(rows), "Original population repeats a native identity.")
        return result

    payruns, plans = table("payruns"), table("plans")
    require(set(payruns) == {selection.payrun_id} and selection.invoice_id in plans, "Original source pair is absent.")
    wage, bill = payruns[selection.payrun_id], plans[selection.invoice_id]
    scoped(wage)
    scoped(bill)
    require(wage["phase"] == bill["phase"] == 2 and bill["kind"] == "Invoice", "Both original sources must be posted.")
    w, b = wage["payload"], bill["payload"]
    require(
        w["period_id"] == b["period_id"] == selection.period_id,
        "Source periods differ from the selected native period.",
    )
    time_ids = w["time_entry_ids"]
    billing_time_ids = b["calculation"]["time_ids"]
    require(
        isinstance(time_ids, list)
        and 1 <= len(time_ids) <= 1000
        and len(set(time_ids)) == len(time_ids)
        and isinstance(billing_time_ids, list)
        and len(billing_time_ids) == len(time_ids)
        and len(set(billing_time_ids)) == len(billing_time_ids)
        and set(time_ids) == set(billing_time_ids),
        "Whole approved time coverage must be identical and unique.",
    )
    times = table("times")
    require(set(times) == set(time_ids), "Original approved time coverage is incomplete or extra.")
    for time in times.values():
        scoped(time)
        require(
            bool(time["approver_id"]) and time["approver_id"] != time["submitter_id"],
            "Time is not independently approved.",
        )
    for family, owner_key, owner_id in (
        ("hc", "payrun_id", selection.payrun_id),
        ("pb", "invoice_id", selection.invoice_id),
    ):
        heads = table(family + "_claim_heads", "time_id")
        all_events = table(family + "_claim_events")
        require(all(event["time_id"] in times for event in all_events.values()), "Detached approved-time history.")
        require(set(heads) == set(time_ids), "Consumed time head coverage differs.")
        for identifier, head in heads.items():
            require(
                head[owner_key] == owner_id and head["state"] == "Consumed",
                "Time is owned by another or incomplete source.",
            )
            events = [event for event in all_events.values() if event["time_id"] == identifier]
            active: str | None = None
            consumed = False
            for event in events:
                operation, event_owner = event["operation"], event[owner_key]
                require(not consumed, "Consumed original time cannot be claimed or released again.")
                if operation == "Claim":
                    require(active is None, "Two active whole-time owners exist.")
                    active = event_owner
                elif operation in {"Release", "Consume"}:
                    require(active == event_owner, "History changes another original owner's claim.")
                    active = None if operation == "Release" else active
                    consumed = operation == "Consume"
                else:
                    refuse("Unknown original claim operation.")
            require(
                [event["sequence"] for event in events] == list(range(1, head["sequence"] + 1))
                and events[-1]["operation"] == "Consume"
                and events[-1][owner_key] == owner_id,
                "Original append-only claim history does not close its consumed head.",
            )
            require(all(event["tenant_id"] == qualified["tenant_id"] for event in events), "Foreign claim history.")
            require(
                all(
                    event["source_digest"] == times[identifier]["source_digest"] and type(event["sequence"]) is int
                    for event in events
                ),
                "Original approved-time claim digest or sequence differs.",
            )
    original_intervals = [
        (time["id"], row["project_id"], row["start_minute"], row["end_minute"], time["source_digest"])
        for time in times.values()
        for row in time["lines"]
    ]
    billed_intervals = [
        (row["time_id"], row["project_id"], row["start_minute"], row["end_minute"], row["time_digest"])
        for row in b["calculation"]["sources"]
    ]
    require(
        len(set(original_intervals)) == len(original_intervals)
        and sorted(original_intervals) == sorted(billed_intervals),
        "Billing lineage does not cover every exact original approved interval once.",
    )
    projects = table("projects")
    masters, values = table("dimension_masters"), table("dimension_values")
    require(
        set(masters) == {row["dimension_id"] for row in projects.values()}
        and set(values) == {row["value_id"] for row in projects.values()},
        "Project master population differs.",
    )
    for native_project in projects.values():
        scoped(native_project)
        master, value = masters[native_project["dimension_id"]], values[native_project["value_id"]]
        require(
            master["workspace_id"] == value["workspace_id"] == selection.scope.workspace_id
            and master["dimension_type"] == "Project"
            and master["organization_code"] in ("", selection.scope.organization_code)
            and value["dimension_id"] == master["id"]
            and value["value_code"] == native_project["project_code"]
            and master["active"] is True
            and value["active"] is True,
            "Original native Project master differs.",
        )
    require(selection.project_id in projects, "Selected Project is not owned by the original source pair.")
    project = projects[selection.project_id]
    scoped(project)
    require(project["id"] == selection.project_id, "Selected Project source differs.")
    wage_projects, revenue_projects = w["project_minor"], b["calculation"]["project_minor"]
    require(set(projects) == set(wage_projects) | set(revenue_projects), "Original Project population differs.")
    require(
        selection.project_id in wage_projects and selection.project_id in revenue_projects,
        "The selected Project must have both governed allocation sources.",
    )
    require(
        sum(exact(value) for value in wage_projects.values()) == exact(w["amount_minor"], positive=True)
        and sum(exact(value) for value in revenue_projects.values()) == exact(b["amount_minor"], positive=True),
        "Original Project allocations do not conserve source totals.",
    )
    policy_fields = (
        "currency_code",
        "currency_precision",
        "currency_rounding_policy",
        "currency_registry_version",
        "currency_registry_digest",
    )
    require(
        all(w["monetary_policy"][key] == b["monetary_policy"][key] for key in policy_fields),
        "The first Project report requires one captured functional currency policy.",
    )
    prices = table("prices")
    require(
        set(prices) == set(b["calculation"]["price_ids"]) and len(prices) == len(b["calculation"]["price_ids"]),
        "Approved original price population differs.",
    )
    for price in prices.values():
        scoped(price)
        source = price["source_json"]
        require(
            digest_payload(source) == price["source_digest"]
            and all(
                source[key] == price[key]
                for key in (
                    *expected_scope,
                    "id",
                    "project_id",
                    "customer_code",
                    "valid_from",
                    "valid_through",
                    "hourly_price_minor",
                    "currency_code",
                    "preparer_id",
                )
            )
            and bool(price["approver_id"])
            and price["approver_id"] != price["preparer_id"]
            and price["customer_code"] == b["customer_code"]
            and source["monetary_policy"] == b["monetary_policy"],
            "Original approved price source seal, actor or policy differs.",
        )
        native_project = projects[price["project_id"]]
        require(
            source["dimension_id"] == native_project["dimension_id"]
            and source["value_id"] == native_project["value_id"],
            "Original price Project reference differs.",
        )
    for applied in b["calculation"]["sources"]:
        price = prices[applied["price_id"]]
        require(
            applied["price_digest"] == price["source_digest"]
            and applied["hourly_price_minor"] == price["hourly_price_minor"]
            and applied["project_id"] == price["project_id"]
            and price["valid_from"] <= times[applied["time_id"]]["business_date"] <= price["valid_through"],
            "Applied service rate differs from its effective approved original price.",
        )
    payments = table("payments")
    sources = [wage, bill, *payments.values(), *[row for key, row in plans.items() if key != selection.invoice_id]]
    require(len(sources) <= 200, "At most200 posted native source operations are admitted.")
    for row in sources:
        scoped(row)
        require(
            type(row["phase"]) is int and row["phase"] == 2 and row["effect_id"],
            "An incomplete source operation cannot become a completed financial total.",
        )
        require(
            exact(row["amount_minor"], positive=True) == exact(row["payload"]["amount_minor"], positive=True),
            "Original source amount projection differs.",
        )
        if row["id"] in payments:
            require(row["payrun_id"] == selection.payrun_id, "Foreign payroll cash source.")
        elif row["id"] != selection.invoice_id and row["id"] != selection.payrun_id:
            require(
                row["kind"] == "Collection" and row["parent_id"] == selection.invoice_id,
                "Foreign customer collection source.",
            )
    entries, effects, lines = table("entries"), table("effects"), table("entry_lines")
    accounts = table("accounts")
    journals = table("journals")
    require(
        set(journals) == {entry["journal_id"] for entry in entries.values()}
        and set(accounts) == {line["account_id"] for line in lines.values()},
        "Original account/journal population differs.",
    )
    commands, audits, outbox = table("native_post_commands", "command_id"), table("audits"), table("outbox", "event_id")
    require(
        len(commands) == len(sources), "Each original native effect requires exactly one acknowledged post command."
    )
    expected_audits = {row[key] for row in sources for key in ("audit_id", "review_audit_id", "post_audit_id")}
    expected_audits.update(row["audit_event_id"] for row in effects.values())
    expected_audits.update(row[key] for row in prices.values() for key in ("audit_id", "approve_audit_id"))
    expected_outbox = {row[key] for row in sources for key in ("outbox_id", "review_outbox_id", "post_outbox_id")}
    expected_outbox.update(row["outbox_event_id"] for row in effects.values())
    expected_outbox.update(row[key] for row in prices.values() for key in ("outbox_id", "approve_outbox_id"))
    require(
        set(audits) == expected_audits and set(outbox) == expected_outbox,
        "Original source audit/outbox membership differs.",
    )

    def trace(
        aid: str, oid: str, identifier: str, action: str, actor_id: str, metadata: dict[str, Any], native: bool = False
    ) -> None:
        audit, event = audits[aid], outbox[oid]
        require(
            audit["object_id"] == event["aggregate_id"] == identifier
            and audit["object_type"]
            == event["aggregate_type"]
            == ("finance_posting" if native else "operational_finance")
            and audit["action"] == event["event_type"] == action
            and audit["actor_user_id"] == actor_id
            and audit["metadata_json"] == metadata
            and event["payload"] == {**metadata, "audit_event_id": aid},
            "Original financial source audit or event custody differs.",
        )
        scoped(event)

    for price in prices.values():
        for prefix, action, actor_key in (
            ("", "price_registered", "preparer_id"),
            ("approve_", "price_approved", "approver_id"),
        ):
            trace(
                price[prefix + "audit_id"],
                price[prefix + "outbox_id"],
                price["id"],
                "project_billing_" + action,
                price[actor_key],
                {"source_digest": price["source_digest"]},
            )

    dimensions = original["entry_dimensions"]
    require(
        set(entries) == {row["entry_id"] for row in sources} and set(effects) == {row["effect_id"] for row in sources},
        "Native ledger/effect membership does not match every original source.",
    )
    require(all(line["entry_id"] in entries for line in lines.values()), "Detached native line.")
    require(
        all(row["tenant_id"] == qualified["tenant_id"] and row["entry_line_id"] in lines for row in dimensions),
        "Detached native Project dimension.",
    )
    for source in sources:
        entry, effect, payload = entries[source["entry_id"]], effects[source["effect_id"]], source["payload"]
        require(
            entry["entry_number"] == source["id"].upper()
            and entry["period_id"] == selection.period_id
            and entry["workspace_id"] == selection.scope.workspace_id
            and entry["organization_code"] == selection.scope.organization_code
            and entry["entity_code"] == selection.scope.entity_code
            and entry["status"] == "Validated",
            "Original native ledger header identity/period differs.",
        )
        require(
            effect["entry_id"] == entry["id"]
            and effect["source_kind"] == "Manual"
            and effect["source_id"] == entry["id"]
            and effect["reverses_effect_id"] is None
            and effect["purpose"] == "operational_posting",
            "Unsupported or detached native effect.",
        )
        scoped(effect)
        require(
            all(type(source[key]) is str and bool(source[key]) for key in ("preparer_id", "reviewer_id", "poster_id"))
            and len({source["preparer_id"], source["reviewer_id"], source["poster_id"]}) == 3
            and entry["preparer_actor_id"] == source["preparer_id"]
            and entry["validator_actor_id"] == source["reviewer_id"]
            and effect["posted_actor_id"] == source["poster_id"],
            "Original financial three-person custody differs.",
        )
        acknowledgement = [command for command in commands.values() if command["result_json"]["id"] == effect["id"]]
        require(len(acknowledgement) == 1, "Native post command/effect bijection differs.")
        command = acknowledgement[0]
        scoped(command)
        result = {key: value for key, value in effect.items() if key not in {"tenant_id", "snapshot_json"}}
        result["snapshot"] = effect["snapshot_json"]
        require(
            command["operation"] == "post"
            and command["actor_id"] == source["poster_id"]
            and command["result_json"] == result
            and command["request_digest"]
            == digest_payload(
                {
                    "operation": "post",
                    "actor_id": source["poster_id"],
                    "workspace_id": selection.scope.workspace_id,
                    "entry_id": entry["id"],
                    "expected_validation_digest": effect["validation_digest"],
                    "reason": effect["reason"],
                }
            ),
            "Native command request or original acknowledged result differs.",
        )
        trace(
            effect["audit_event_id"],
            effect["outbox_event_id"],
            effect["id"],
            "finance_entry_posted",
            source["poster_id"],
            {"entry_id": entry["id"], "content_digest": effect["validation_digest"]},
            True,
        )
        if source["id"] in plans:
            actions = ("project_billing_prepared", "project_billing_reviewed", "project_billing_posted")
        else:
            actions = (
                "people_payrun_prepared" if source["id"] == selection.payrun_id else "people_payment_prepared",
                "people_plan_reviewed",
                "people_plan_posted",
            )
        for prefix, action, actor_field in zip(
            ("", "review_", "post_"), actions, ("preparer_id", "reviewer_id", "poster_id"), strict=True
        ):
            trace(
                source[prefix + "audit_id"],
                source[prefix + "outbox_id"],
                source["id"],
                action,
                source[actor_field],
                {"source_digest": payload["plan_digest"]},
            )
        native_lines = []
        for line in sorted(
            (row for row in lines.values() if row["entry_id"] == entry["id"]), key=lambda row: row["line_number"]
        ):
            attached = [row for row in dimensions if row["entry_line_id"] == line["id"]]
            require(
                len({row["dimension_id"] for row in attached}) == len(attached),
                "Duplicate native dimension attachment.",
            )
            native_lines.append(
                {**line, "dimensions": {row["dimension_id"]: row["dimension_value_id"] for row in attached}}
            )
        snapshot = make_entry_snapshot(entry, native_lines)
        require(
            snapshot == effect["snapshot_json"]
            and validation_digest(snapshot)
            == payload["validation_digest"]
            == effect["validation_digest"]
            == entry["validation_digest"],
            "Native reviewed ledger lines or original validation seal differ.",
        )
        if source["id"] in plans:
            require(snapshot == payload["snapshot"], "Original public billing snapshot differs.")
        require(
            all(entry[key] == w["monetary_policy"][key] for key in policy_fields), "Native currency policy differs."
        )

        def expected_line(
            code: str,
            role: str,
            debit: int,
            credit: int,
            project_id: str | None = None,
            *,
            chart_id: str = journals[entry["journal_id"]]["chart_id"],
        ) -> tuple[Any, ...]:
            choices = [
                account
                for account in accounts.values()
                if account["account_code"] == code
                and account["chart_id"] == chart_id
                and account["workspace_id"] == selection.scope.workspace_id
            ]
            require(
                len(choices) == 1 and choices[0]["account_type"] == role,
                "Original source account is absent, ambiguous or reclassified.",
            )
            attached: tuple[Any, ...] = ()
            if project_id is not None:
                native_project = projects[project_id]
                scoped(native_project)
                attached = ((native_project["dimension_id"], native_project["value_id"]),)
            return choices[0]["id"], exact(debit), exact(credit), attached

        if source["id"] == selection.payrun_id:
            expected = [
                expected_line(w["expense_account_code"], "Expense", amount, 0, project_id)
                for project_id, amount in wage_projects.items()
                if amount
            ]
            expected.append(expected_line(w["liability_account_code"], "Liability", 0, w["amount_minor"]))
        elif source["id"] == selection.invoice_id:
            expected = [expected_line(b["receivable_account_code"], "Asset", b["amount_minor"], 0)]
            expected.extend(
                expected_line(b["revenue_account_code"], "Income", 0, amount, project_id)
                for project_id, amount in revenue_projects.items()
            )
        elif source["id"] in payments:
            expected = [
                expected_line(w["liability_account_code"], "Liability", source["amount_minor"], 0),
                expected_line(w["cash_account_code"], "Asset", 0, source["amount_minor"]),
            ]
        else:
            expected = [
                expected_line(b["cash_account_code"], "Asset", source["amount_minor"], 0),
                expected_line(b["receivable_account_code"], "Asset", 0, source["amount_minor"]),
            ]
        actual = [
            (line["account_id"], line["debit_minor"], line["credit_minor"], tuple(sorted(line["dimensions"].items())))
            for line in native_lines
        ]
        require(
            sorted(actual) == sorted(expected),
            "Original source role, amount or Project dimension differs from native ledger.",
        )
        if source["id"] in plans:
            require(
                digest_payload({key: value for key, value in payload.items() if key != "plan_digest"})
                == payload["plan_digest"],
                "Original public billing source seal differs.",
            )
    dimension_key = (project["dimension_id"], project["value_id"])

    def project_amount(source: Mapping[str, Any], account_code: str, credit: bool) -> int:
        total = 0
        for line in lines.values():
            if line["entry_id"] != source["entry_id"]:
                continue
            account = accounts[line["account_id"]]
            matches = [row for row in dimensions if row["entry_line_id"] == line["id"]]
            if account["account_code"] == account_code and any(
                (row["dimension_id"], row["dimension_value_id"]) == dimension_key for row in matches
            ):
                require(len(matches) == 1, "Project source has an unknown additional dimension.")
                require(account["account_type"] == ("Income" if credit else "Expense"), "Project account role differs.")
                total += exact(line["credit_minor"] if credit else line["debit_minor"])
                require(
                    (line["debit_minor"] if credit else line["credit_minor"]) == 0, "Project posting direction differs."
                )
        return total

    cost = project_amount(wage, w["expense_account_code"], False)
    revenue = project_amount(bill, b["revenue_account_code"], True)
    require(
        cost == wage_projects[selection.project_id] and revenue == revenue_projects[selection.project_id],
        "Project native allocation does not match original governed amounts.",
    )
    known = {wage["entry_id"], bill["entry_id"]}
    require(
        all(
            row["tenant_id"] == qualified["tenant_id"] and row["entry_id"] in known
            for row in original["project_ledger"]
        ),
        "Unknown posted Project cost/revenue exists outside the selected original source pair.",
    )
    scanned = [row["id"] for row in original["project_ledger"]]
    expected_scanned = {
        line["id"]
        for line in lines.values()
        if line["entry_id"] in known
        and accounts[line["account_id"]]["account_type"] in {"Expense", "Income"}
        and any(
            row["entry_line_id"] == line["id"] and (row["dimension_id"], row["dimension_value_id"]) == dimension_key
            for row in dimensions
        )
    }
    require(
        len(set(scanned)) == len(scanned) and set(scanned) == expected_scanned,
        "The original posted Project population is missing or duplicated.",
    )
    paid = sum(exact(row["amount_minor"], positive=True) for row in payments.values())
    collected = sum(
        exact(row["amount_minor"], positive=True) for key, row in plans.items() if key != selection.invoice_id
    )
    require(
        paid <= w["amount_minor"] and collected <= b["amount_minor"],
        "Source cash exceeds its original liability or AR.",
    )
    ar = original["ar_invoice"]
    scoped(ar)
    require(
        ar["id"] == bill["ar_invoice_id"]
        and ar["pb_owner_id"] == selection.invoice_id
        and ar["status"] == ("Paid" if collected == b["amount_minor"] else "PartiallyPaid" if collected else "Approved")
        and ar["total_minor"] == b["amount_minor"]
        and ar["allocated_minor"] == collected,
        "Native AR header/settlement differs from its exact source owner.",
    )
    receipts = table("ar_receipts")
    collections = [row for row in plans.values() if row["id"] != selection.invoice_id]
    require(set(receipts) == {row["receipt_id"] for row in collections}, "Native cash receipt membership differs.")
    allocations = original["ar_allocations"]
    require(len(allocations) == len(collections), "Native AR allocation population differs.")
    for source in collections:
        receipt = receipts[source["receipt_id"]]
        scoped(receipt)
        allocation = [row for row in allocations if row["receipt_id"] == receipt["id"]]
        require(
            receipt["pb_owner_id"] == source["id"]
            and receipt["status"] == "Posted"
            and receipt["posted_by"] == source["poster_id"]
            and receipt["amount_minor"] == source["amount_minor"]
            and len(allocation) == 1
            and allocation[0]["tenant_id"] == qualified["tenant_id"]
            and allocation[0]["invoice_id"] == ar["id"]
            and allocation[0]["amount_minor"] == source["amount_minor"],
            "Cash/AR allocation is detached from its original collection source.",
        )
    summary = {
        "schema_version": "project-source-reconciliation-v1",
        "qualified_scope": qualified,
        "selection": {key: value for key, value in asdict(selection).items() if key != "scope"},
        "currency_policy": {key: w["monetary_policy"][key] for key in policy_fields},
        "project": {
            "id": project["id"],
            "project_code": project["project_code"],
            "dimension_id": project["dimension_id"],
            "value_id": project["value_id"],
        },
        "project_totals": {
            "wage_cost_minor": str(cost),
            "revenue_minor": str(revenue),
            "source_margin_minor": str(revenue - cost),
        },
        "whole_source_settlement": {
            "wage_accrued_minor": str(w["amount_minor"]),
            "wage_paid_minor": str(paid),
            "wage_liability_minor": str(w["amount_minor"] - paid),
            "invoice_minor": str(b["amount_minor"]),
            "collected_minor": str(collected),
            "ar_outstanding_minor": str(b["amount_minor"] - collected),
            "per_project_cash_allocated": False,
        },
        "source_membership": [
            {
                "id": source["id"],
                "plan_digest": source["payload"]["plan_digest"],
                "entry_id": source["entry_id"],
                "effect_id": source["effect_id"],
                "validation_digest": source["payload"]["validation_digest"],
            }
            for source in sorted(sources, key=lambda row: row["id"])
        ],
        "approved_time": [{"id": key, "source_digest": times[key]["source_digest"]} for key in sorted(times)],
        "limitations": {
            "private_earnings_digest_recomputed": False,
            "private_personnel_rows_included": False,
            "original_time_request_digest_recomputed": False,
            "audit_chain_recomputed": False,
            "comprehensive_project_profit_and_loss": False,
            "bank_transfer_proven": False,
            "country_tax_packs": 0,
            "performance_comparison_accepted": False,
        },
    }
    return {**summary, "report_digest": digest_payload(summary)}


def diagnose_project_source_close(
    selection: ProjectSourceSelection,
    source_evidence: Mapping[str, Any],
    observed_periods: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe selected original obligations without performing a Close.

    The source evidence and its v1 report remain unchanged. This separate
    derivative checks the same complete public source population, then adds
    exact referenced period observations from one read-only statement snapshot.
    """
    require(
        source_evidence["schema_version"] == "project-source-reconciliation-evidence-v1"
        and source_evidence["native_execution_proven"] is True
        and source_evidence["financial_writes"] is False
        and source_evidence["private_personnel_reads"] is False
        and source_evidence["private_payroll_command_receipts_exported"] is False,
        "An original ordinary governed source capture is required.",
    )
    original = source_evidence["original_rows"]
    report = reconcile_project_sources(selection, original)
    require(report == source_evidence["report"], "Original source report differs from its public native population.")
    scope = report["qualified_scope"]
    period_fields = {"tenant_id", "id", "application_workspace_id", "name", "start_date", "end_date", "status", "updated_at"}
    for row in observed_periods:
        require(set(row) == period_fields and all(type(row[key]) is str and row[key] for key in period_fields),
                "Only exact observed native period metadata is admitted.")
        try:
            require(date.fromisoformat(row["start_date"]).isoformat() == row["start_date"]
                    and date.fromisoformat(row["end_date"]).isoformat() == row["end_date"],
                    "Observed period dates must be canonical native dates.")
        except ValueError:
            refuse("Observed period dates are invalid.")
    periods = {row["id"]: row for row in observed_periods}
    required = {row["period_id"] for row in original["entries"]}
    require(
        len(observed_periods) == len(periods) and set(periods) == required == {selection.period_id},
        "Observed period membership is duplicate, missing or unrelated to the selected source entries.",
    )
    for header in original["entries"]:
        observed = periods[header["period_id"]]
        require(
            observed["tenant_id"] == scope["tenant_id"]
            and observed["application_workspace_id"] == scope["workspace_id"]
            and observed["status"] in {"Open", "Soft Closed", "Closed"}
            and observed["start_date"] <= header["posting_date"] <= observed["end_date"],
            "An original posting is outside its exact observed native period.",
        )
    claims = []
    for time in report["approved_time"]:
        rows = {}
        for family in ("hc", "pb"):
            head = next(row for row in original[family + "_claim_heads"] if row["time_id"] == time["id"])
            rows[family] = {"owner_id": head["payrun_id" if family == "hc" else "invoice_id"],
                            "sequence": head["sequence"], "state": head["state"]}
        claims.append({"time_id": time["id"], "time_digest": time["source_digest"],
                       "wage_claim": rows["hc"], "billing_claim": rows["pb"]})
    obligations = report["whole_source_settlement"]
    issues = []
    if int(obligations["wage_liability_minor"]) != 0:
        issues.append("selected_payrun_wages_outstanding")
    if int(obligations["ar_outstanding_minor"]) != 0:
        issues.append("selected_invoice_receivable_outstanding")
    result = {
        "schema_version": "project-source-close-diagnostic-v1",
        "qualified_scope": scope,
        "selection": report["selection"],
        "source_report_digest": report["report_digest"],
        "currency_policy": report["currency_policy"],
        "project_totals": report["project_totals"],
        "whole_source_obligations": obligations,
        "whole_time_claims": claims,
        "source_membership": report["source_membership"],
        "observed_native_periods": [periods[key] for key in sorted(periods)],
        "source_obligations_settled": not issues,
        "findings": issues,
        "coverage": "one-selected-original-payrun-and-invoice-with-identical-whole-approved-time",
        "period_capture_scope": "one-readonly-statement-snapshot-without-period-row-locks",
        "limitations": {
            "formal_close_workflow_assessed": False,
            "whole_period_membership_proven": False,
            "comprehensive_project_profit_and_loss": False,
            "private_earnings_formula_recomputed": False,
            "per_project_cash_allocated": False,
            "bank_transfer_proven": False,
            "country_statutory_packs": 0,
            "financial_writes": False,
            "performance_comparison_accepted": False,
        },
    }
    return {**result, "diagnostic_digest": digest_payload(result)}
