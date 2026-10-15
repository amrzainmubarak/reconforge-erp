"""Genuine existing Stock owner resale and new partial returns of zero costs."""

import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from tests.test_postgres_customer_partial_return_rounding import (
    create_remainder_runtime,
    current_v2,
    phase_v2,
    post_v2,
    prepare_v2,
    reverse_v2,
)
from tests.test_postgres_customer_partial_return_rounding_security import capture_rounding
from tests.test_postgres_customer_partial_returns import SCOPE, retained_partial_state
from tests.test_postgres_customer_returns import balances
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_inventory_receipt_posting import request as receipt_request
from tests.test_postgres_stock_sales import execute
from tests.test_postgres_stock_sales import repository as stock_repository

_ = receipt_database


def create_restituted_resale(runtime: ReceiptRuntime, *, quantity: str = "0.1", number: str = "ZERO-RESALE") -> dict[str, Any]:
    """Public synthetic helper; all issue/physical/revenue effects use real owners."""
    with runtime.actor("maker") as (connection, _, actor):
        sale = stock_repository(connection, runtime).create(StockOrder(number, "CUSTOMER", "CUSTOMER-PO-1", "ITEM", "MAIN", "STOCK",
            quantity, 1000, "USD", "2026-10-14", "Actual governed restituted inventory resale"), command_id=number + ":create", actor=actor)
    for operation, who in (("submit", "maker"), ("approve", "checker"), ("reserve", "maker")):
        sale = execute(runtime, sale, operation, who)
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-14", "period_id": "period", "policy_code": "FIFO"})
    assert sale["cost_admission_policy"] == "partial-return-restituted-v1"
    sale = execute(runtime, sale, "review-issue", "checker")
    sale = execute(runtime, sale, "deliver", "poster")
    invoice = SalesInvoicePreparation(number + "-INVOICE", "2026-10-14", "2026-10-31", "SALES", "period", "AR", "REVENUE",
        "Actual original resale through native revenue").payload()
    invoice.pop("reason")
    sale = execute(runtime, sale, "prepare-invoice", "maker", invoice)
    sale = execute(runtime, sale, "review-invoice", "checker")
    return execute(runtime, sale, "invoice", "poster")


def test_actual_zero_cost_restituted_stock_resale_new_return_and_transfer_pool_keep_real_effects_only(receipt_database: tuple[str, str]) -> None:
    runtime, original = create_remainder_runtime(receipt_database, zero=True)
    captures = [capture_rounding(runtime)]
    old_zero = post_v2(runtime, prepare_v2(runtime, original, 1, 0, "original-zero-return"))
    captures.append(capture_rounding(runtime))
    assert old_zero["entries"] == [] and current_v2(runtime, original)["history_version"] == 1
    sale = create_restituted_resale(runtime)
    captures.append(capture_rounding(runtime))
    assert sale["cogs_minor"] == "0" and sale["cogs_entry_id"] is sale["cogs_effect_id"] is None
    assert sale["movement_id"] is not None and sale["valuation_id"] is not None
    plan = prepare_v2(runtime, sale["id"], 1, 0, "resale-zero-cost-return")
    assert (plan["credit_minor"], plan["cogs_restored_minor"], plan["receivable_released_minor"]) == (100, 0, 100)
    assert [part["purpose"] for part in plan["entries"]] == ["RevenueCredit"]
    posted = post_v2(runtime, plan)
    captures.append(capture_rounding(runtime))
    retained = retained_partial_state(runtime)
    assert phase_v2(runtime, plan, "post", "poster") == posted
    assert retained_partial_state(runtime) == retained
    with pytest.raises(FinancePostingError) as dependency:
        reverse_v2(runtime, old_zero, 1)
    assert dependency.value.code == "customer_partial_return_reversal_dependency"
    assert retained_partial_state(runtime) == retained
    assert current_v2(runtime, sale["id"])["outstanding_minor"] == 0
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
        assert owner.get(posted["id"], actor=actor) == posted
        original_row = connection.execute("SELECT source_payload,original_cogs_effect_id FROM reconforge.customer_partial_return_sources WHERE tenant_id=%s AND source_order_id=%s", (runtime.tenant, sale["id"])).fetchone()
        assert original_row["original_cogs_effect_id"] is None
        assert original_row["source_payload"]["fingerprint_payload"]["contract"] == "customer-partial-return-original-v2"
        assert original_row["source_payload"]["original_source"]["cost_admission"]["posting_effect"] is None
        pool = connection.execute("SELECT reconforge.it1_cost_snapshot(%s,'work','org','entity',%s) value", (runtime.tenant, original_row["source_payload"]["typed_source"]["scope"]["item_id"])).fetchone()["value"]
        assert pool["schema_version"] == "inventory-transfer-cost-v3" and pool["remaining_quantity_scaled"] == 1 and pool["remaining_value_minor"] == 0
        assert len(pool["sources"][0]["restituted_consumption_admissions"]) == 1
        totals = connection.execute("SELECT count(DISTINCT e.id) effects,count(l.id) lines,sum(l.debit_minor) debit,sum(l.credit_minor) credit FROM reconforge.finance_posting_effects e JOIN reconforge.finance_entry_lines l ON(l.tenant_id,l.entry_id)=(e.tenant_id,e.entry_id) WHERE e.tenant_id=%s", (runtime.tenant,)).fetchone()
        assert (totals["effects"], totals["lines"], totals["debit"], totals["credit"]) == (5, 10, 203, 203)
    values = balances(runtime)
    assert (values["INVENTORY"], values["CLEARING"], values["COGS"], values["AR"], values["REVENUE"]) == (0, -1, 1, 1, -1)
    destination = os.environ.get("RECONFORGE_PARTIAL_REMAINDER_PRIVATE_OUTPUT")
    if destination:
        private = Path(destination)
        if not private.is_absolute() or not private.is_dir():
            raise AssertionError("An explicit existing private custody directory is required.")
        for candidate in (private, *private.parents):
            if candidate.is_symlink() or getattr(candidate.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise AssertionError("Private custody ancestry must remain owned and unlinked.")
        packet = {"schema_version": "customer-partial-return-restituted-cycle-input-v1", "tenant_id": runtime.tenant,
                  "original_source_order_id": original, "resale_source_order_id": sale["id"], "captures": captures}
        with (private / "native-restituted-cycle-original-v1.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(packet, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")


def test_actual_mixed_zero_original_consumption_keeps_one_real_total_cogs_effect(receipt_database: tuple[str, str]) -> None:
    runtime, original = create_remainder_runtime(receipt_database, zero=True)
    post_v2(runtime, prepare_v2(runtime, original, 1, 0, "mixed-original-zero-return"))
    request = replace(receipt_request("MIXED-EXTRA"), quantity="0.1", total_value_minor=10)
    with runtime.actor("maker") as (_, owner, actor):
        prepared = owner.prepare_receipt(request, command_id="mixed-extra-prepare", actor=actor)
    with runtime.actor("checker") as (_, owner, actor):
        review = owner.review(prepared["plan_id"], command_id="mixed-extra-review", expected_plan_digest=prepared["plan_digest"], reason="Independent original positive extra layer", actor=actor)
    with runtime.actor("poster") as (_, owner, actor):
        owner.commit(prepared["plan_id"], command_id="mixed-extra-post", expected_review_digest=review["review_digest"], reason="Actual extra original receipt", actor=actor)
    sale = create_restituted_resale(runtime, quantity="0.2", number="MIXED-RESALE")
    assert sale["cogs_minor"] == "10" and sale["cogs_entry_id"] is not None and sale["cogs_effect_id"] is not None
    first = post_v2(runtime, prepare_v2(runtime, sale["id"], 1, 0, "mixed-first"))
    second = post_v2(runtime, prepare_v2(runtime, sale["id"], 1, 1, "mixed-second"))
    assert (first["credit_minor"], first["cogs_restored_minor"], second["credit_minor"], second["cogs_restored_minor"]) == (100, 0, 100, 10)
    assert [part["purpose"] for part in first["entries"]] == ["RevenueCredit"]
    assert [part["purpose"] for part in second["entries"]] == ["RevenueCredit", "CostRestoration"]
    with runtime.actor("maker") as (connection, _, actor):
        assert PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2).balance(sale["id"], SCOPE, actor=actor)["remaining_quantity_scaled"] == 0
        originals = connection.execute("SELECT value_minor FROM reconforge.inventory_layer_consumptions consumed JOIN reconforge.inventory_valuation_lines detail ON(detail.tenant_id,detail.id)=(consumed.tenant_id,consumed.valuation_line_id) WHERE consumed.tenant_id=%s AND detail.valuation_document_id=%s ORDER BY consumed.value_minor", (runtime.tenant, sale["valuation_id"])).fetchall()
        assert [row["value_minor"] for row in originals] == [0, 10]
