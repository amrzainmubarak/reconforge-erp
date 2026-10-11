"""Configure three native books; every IC1 source/effect is made by real Studio."""

import hashlib
from typing import Any

from reconforge.domain.financial_reporting import AccountClassification, ReportingScope
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_browser_restore import require
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_intercompany_operations import (
    ACCOUNTS,
    ENTITIES,
    IntercompanyRuntime,
    seed_intercompany_masters,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

INTERCOMPANY_BROWSER_TABLES = (
    "intercompany_operation_sources", "intercompany_operation_plans", "intercompany_operation_reviews",
    "intercompany_operation_links", "intercompany_operation_post_evidence", "intercompany_operation_commands",
    "financial_reporting_maps", "financial_reporting_map_reviews", "financial_reporting_commands",
)


def seed_intercompany_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    base = seed_receipt_browser(admin_dsn, app_dsn)
    runtime = seed_intercompany_masters(base)
    seed_erp_browser_principals(base)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("erp-maker", "erp-checker", "erp-poster"):
            for entity in ("buyer", "group"):
                authority.grant(tenant_id=base.tenant, grant_id=person + "-" + entity, principal_type="user", principal_id=person,
                    scope_type="legal_entity", scope_id=entity, actor_id=person)
    for entity in sorted(ENTITIES):
        with runtime.actor("browser-maker") as (connection, _, actor):
            mapping = PostgresFinancialReportingRepository(connection, base.tenant).prepare_map(ReportingScope("work", "org", entity),
                name="Browser reviewed " + entity, accounts=[AccountClassification(code, section, code == "CASH") for code, _, section in ACCOUNTS],
                command_id="browser-map-" + entity, actor=actor)
        with runtime.actor("browser-checker") as (connection, _, actor):
            PostgresFinancialReportingRepository(connection, base.tenant).review_map(mapping["id"], expected_digest=mapping["map_digest"],
                reason="Explicit independent account classifications", command_id="browser-map-review-" + entity, actor=actor)
    with runtime.actor("browser-poster") as (connection, _, _):
        require(connection.execute("SELECT count(*) n FROM reconforge.intercompany_operation_sources WHERE tenant_id=%s", (base.tenant,)).fetchone()["n"] == 0,
                "Real browser must begin without prepared IC1 sources.")
        require(connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (base.tenant,)).fetchone()["n"] == 0,
                "Real browser must begin without posted native effects.")
    return base


def verify_intercompany_browser(base: ReceiptRuntime) -> dict[str, Any]:
    runtime = IntercompanyRuntime(base)
    with runtime.actor("browser-poster") as (connection, repository, actor):
        rows = connection.execute("SELECT id FROM reconforge.intercompany_operation_sources WHERE tenant_id=%s", (base.tenant,)).fetchall()
        require(len(rows) == 1, "Lost recognition response must not duplicate the source.")
        source = repository.get_source(rows[0]["id"], actor=actor)
        require(source["request"]["reference"] == "BROWSER-IC1" and source["request"]["amount_minor"] == 10001
                and source["settled_minor"] == 3000 and source["outstanding_minor"] == 7001 and source["closed"],
                "Independent original10001, cash3000 and residual7001 source equation differs.")
        require([plan["kind"] for plan in source["plans"]] == ["recognize", "settle", "eliminate"]
                and [plan["amount_minor"] for plan in source["plans"]] == [10001, 3000, 17002],
                "Three complete native original, partial cash and group adjustment plans are required.")
        effects = []
        for plan in source["plans"]:
            require(plan["phase"] == 2 and (plan["preparer_actor_id"], plan["reviewer_actor_id"], plan["posted_actor_id"]) == ("erp-maker", "erp-checker", "erp-poster"),
                    "Each native operation requires three actual independent humans.")
            proof = repository.evidence(plan["id"], actor=actor)
            require(hashlib.sha256(proof["canonical_source_json"].encode()).hexdigest() == source["source_digest"]
                    and hashlib.sha256(proof["canonical_plan_json"].encode()).hexdigest() == plan["plan_digest"], "Source or plan canonical seal differs.")
            for entry, raw, native in zip(plan["entries"], proof["canonical_snapshot_jsons"], proof["native_effects"], strict=True):
                require(hashlib.sha256(raw.encode()).hexdigest() == entry["validation_digest"] and native["validation_digest"] == entry["validation_digest"]
                        and native["id"] == plan["posting_effect_ids"][entry["book"]] and native["posted_actor_id"] == "erp-poster", "Native book seal or third human differs.")
                effects.append({"kind": plan["kind"], "book": entry["book"], "plan_id": plan["id"], "entry_id": entry["entry_id"], "effect_id": native["id"]})
        mappings = connection.execute("SELECT id,legal_entity_id FROM reconforge.financial_reporting_maps WHERE tenant_id=%s AND status='Reviewed'", (base.tenant,)).fetchall()
        by_entity = {row["legal_entity_id"]: row["id"] for row in mappings}
        report = repository.report(source["id"], seller_map_id=by_entity["entity"], buyer_map_id=by_entity["buyer"], adjustment_map_id=by_entity["group"],
            period_id="period", as_of_date="2026-10-05", actor=actor)
        require(report["effect_count"] == 5 and all(row["closing"]["balance_minor"] == 0 for row in report["trial_balance"])
                and report["income_statement"] == {"income_minor": 0, "expense_minor": 0, "result_minor": 0}
                and report["cash_net_movements"] == {"opening_minor": 0, "activity_minor": 0, "closing_minor": 0}, "Actual consolidated report disagrees with the independent three-book zero-net oracle.")
        native = connection.execute("""SELECT e.legal_entity_id,a.account_code,sum(l.debit_minor-l.credit_minor)::bigint AS balance
            FROM reconforge.finance_posting_effects e JOIN reconforge.finance_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE e.tenant_id=%s GROUP BY e.legal_entity_id,a.account_code""", (base.tenant,)).fetchall()
        expected = {("entity", "IC_AR"): 7001, ("entity", "IC_REVENUE"): -10001, ("entity", "CASH"): 3000,
                    ("buyer", "IC_EXPENSE"): 10001, ("buyer", "IC_AP"): -7001, ("buyer", "CASH"): -3000,
                    ("group", "IC_REVENUE"): 10001, ("group", "IC_EXPENSE"): -10001, ("group", "IC_AP"): 7001, ("group", "IC_AR"): -7001}
        require({(row["legal_entity_id"], row["account_code"]): row["balance"] for row in native} == expected,
                "Native immutable party and explicit adjustment balances differ from independent integer equations.")
        return {"source_id": source["id"], "source_digest": source["source_digest"], "source_plans": 3, "native_posting_effects": 5,
                "original_minor": "10001", "cash_minor": "3000", "residual_minor": "7001", "group_debit_minor": "17002", "native_effects": effects,
                "original_party_balances_minor": {entity + ":" + account: str(value) for (entity, account), value in expected.items()},
                "group_report_digest": report["report_digest"], "group_income_minor": "0", "group_expense_minor": "0", "group_net_cash_minor": "0"}
