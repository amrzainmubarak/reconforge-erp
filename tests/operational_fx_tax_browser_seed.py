"""Canonical masters only; foreign source and every effect come from real Studio."""

import hashlib
from typing import Any

from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_browser_restore import require
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_fx_tax import seed_fx_masters

OPERATIONAL_FX_TABLES = (
    "operational_fx_sources", "operational_fx_plans", "operational_fx_reviews", "operational_fx_links", "operational_fx_commands",
)


def seed_operational_fx_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_receipt_browser(admin_dsn, app_dsn)
    seed_fx_masters(runtime)
    seed_erp_browser_principals(runtime)
    with runtime.actor("browser-poster") as (connection, _, _):
        require(connection.execute("SELECT count(*) amount FROM reconforge.operational_fx_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["amount"] == 0,
                "Actual browser fixture must start without pre-created foreign sources.")
        require(connection.execute("SELECT count(*) amount FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["amount"] == 0,
                "Actual browser fixture must start without posted financial effects.")
    return runtime


def verify_operational_fx_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    """Independent integer equations over actual posted native AR and GL."""
    with runtime.actor("browser-poster") as (connection, _, actor):
        rows = connection.execute("SELECT id FROM reconforge.operational_fx_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(rows) == 1, "Lost acknowledgement must not duplicate the foreign source.")
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        detail = repository.get(rows[0]["id"], actor=actor)
        require(detail["request"]["invoice_number"] == "BROWSER-FX" and detail["foreign_policy"]["currency_code"] == "EUR"
                and detail["functional_policy"]["currency_code"] == "USD", "Actual foreign and functional currency identity differs.")
        require(detail["foreign_gross_minor"] == 11401 and detail["functional_gross_minor"] == 14251
                and detail["foreign_outstanding_minor"] == detail["functional_outstanding_minor"] == 0,
                "Independent original net10001, tax1400, gross11401 and historical gross14251 oracle differs.")
        require(detail["request"]["original_rate"] == {"rate": "1.25", "source": "Browser original spot", "effective_at": "2026-10-01T12:00:00Z"},
                "Immutable original historical rate provenance differs.")
        tax = detail["tax_components"]
        require(len(tax) == 1 and tax[0]["policy_id"] == "BROWSER-SYNTHETIC-TAX" and tax[0]["version"] == "2026-v1"
                and tax[0]["foreign_tax_minor"] == 1400 and tax[0]["functional_tax_minor"] == 1750,
                "Effective original synthetic tax component was changed or omitted.")
        plans = detail["plans"]
        require([plan["kind"] for plan in plans] == ["recognize", "settle", "revalue", "reverse_revaluation", "settle"]
                and [plan["amount_minor"] for plan in plans] == [14251, 5200, 740, 740, 9251], "Five complete recognition, closing valuation/inverse and partial-settlement native plans are required.")
        settlements = [plan for plan in plans if plan["kind"] == "settle"]
        require([plan["equation"]["realized_fx_minor"] for plan in settlements] == [200, -370]
                and [plan["equation"]["historical_release_minor"] for plan in settlements] == [5000, 9251],
                "Original-rate cumulative release and independently rounded gain/loss equations differ.")
        require(plans[2]["equation"]["unrealized_fx_minor"] == 740 and plans[2]["equation"]["valued_outstanding_minor"] == 9991
                and plans[3]["equation"]["unrealized_fx_minor"] == -740
                and plans[3]["snapshot"]["entry"]["reverses_posting_id"] == plans[2]["posting_effect_id"]
                and detail["active_revaluation_plan_id"] is None and detail["unrealized_fx_minor"] == 0,
                "Closing residual7401 at1.35 requires exact native difference740 and its explicit inverse before settlement.")
        require(all(plan["status"] == "Posted" and plan["preparer_actor_id"] == "erp-maker" and plan["reviewer_actor_id"] == "erp-checker" for plan in plans),
                "Distinct actual preparation and review humans differ.")
        for plan in plans:
            proof = repository.plan_evidence(plan["id"], actor=actor)
            require(proof["native_effect"]["posted_actor_id"] == "erp-poster" and proof["native_effect"]["id"] == plan["posting_effect_id"],
                    "Actual third-human native posting source is absent.")
            for key, expected in (("canonical_source_json", detail["source_digest"]), ("canonical_plan_json", plan["plan_digest"]),
                                  ("canonical_snapshot_json", plan["validation_digest"])):
                require(hashlib.sha256(proof[key].encode("utf-8")).hexdigest() == expected, "A retained native canonical evidence seal differs.")
            require([phase["actor_id"] for phase in proof["phases"]] == ["erp-maker", "erp-checker", "erp-poster", "erp-poster"],
                    "Actual source/native audit human chain differs.")
        invoice = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(detail["invoice_id"])
        require(invoice["status"] == "Paid" and invoice["outstanding_minor"] == 0 and invoice["allocated_minor"] == 11401,
                "Native foreign AR is not closed by exactly two original-currency allocations.")
        receipts = connection.execute("SELECT amount_minor,currency_code FROM reconforge.ar_receipts WHERE tenant_id=%s ORDER BY amount_minor", (runtime.tenant,)).fetchall()
        require([(row["amount_minor"], row["currency_code"]) for row in receipts] == [(4000, "EUR"), (7401, "EUR")],
                "Actual native foreign receipts differ or were duplicated.")
        balances = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor)::bigint amount
            FROM reconforge.finance_posting_effects e JOIN reconforge.finance_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE e.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        expected = {"AR": 0, "REVENUE": -12501, "TAX": -1750, "CASH": 14081, "GAIN": -200, "LOSS": 370, "UGAIN": 0}
        require({row["account_code"]: row["amount"] for row in balances} == expected and sum(expected.values()) == 0,
                "Actual posted functional GL differs from the independent native financial oracle.")
        return {"source_id": detail["id"], "invoice_id": detail["invoice_id"], "native_invoice_status": "Paid", "source_plans": 5,
                "native_posting_effects": 5, "unrealized_fx_minor": ["740", "-740"], "foreign_currency": "EUR", "functional_currency": "USD", "foreign_gross_minor": "11401",
                "functional_gross_minor": "14251", "foreign_receipts_minor": ["4000", "7401"], "historical_releases_minor": ["5000", "9251"],
                "realized_fx_minor": ["200", "-370"], "account_balances_minor": {key: str(value) for key, value in expected.items()}}
