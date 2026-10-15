"""Ordinary-app hostile SQL for explicit restituted zero-cost originals.

These are unexecuted until the native gate runs. Controls use real owners;
attacks retain exact named SQL causes and all 79 original table row strings.
No fabricated financial entry/effect is used as successful fixture data.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
import pytest
from psycopg import sql

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreError
from tests.test_postgres_customer_partial_return_rounding import create_remainder_runtime, post_v2, prepare_v2
from tests.test_postgres_customer_partial_return_rounding_security import capture_rounding, check_cause
from tests.test_postgres_customer_partial_return_zero_stock import create_restituted_resale
from tests.test_postgres_customer_partial_returns import create_partial_runtime, phase, prepare_return
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_sales import execute
from tests.test_postgres_stock_sales import repository as stock_repository

_ = receipt_database
ACTIVE_MESSAGE = "Zero-valued native stock requires its current exact third-human reviewed restitution issue"
NULL_MESSAGE = "Absent original COGS restitution requires the exact visible zero-cost factual source and current third-human owner"


def _cause(error: BaseException, constraint: str, message: str | None = None) -> None:
    native = check_cause(error)
    assert native.sqlstate == "23514" and native.diag.constraint_name == constraint
    if message is not None:
        assert native.diag.message_primary == message


def _prepared_zero_stock(database: tuple[str, str]) -> tuple[ReceiptRuntime, dict[str, Any]]:
    runtime, original = create_remainder_runtime(database, zero=True)
    returned = post_v2(runtime, prepare_v2(runtime, original, 1, 0, "security-zero-original-return"))
    assert returned["phase"] == 2 and returned["entries"] == []
    with runtime.actor("maker") as (connection, _, actor):
        sale = stock_repository(connection, runtime).create(StockOrder(
            "SECURITY-ZERO-RESALE", "CUSTOMER", "CUSTOMER-PO-1", "ITEM", "MAIN", "STOCK", "0.1", 1000,
            "USD", "2026-10-14", "Genuine restituted zero-cost issue security control"),
            command_id="security-zero-resale:create", actor=actor)
    for operation, who in (("submit", "maker"), ("approve", "checker"), ("reserve", "maker")):
        sale = execute(runtime, sale, operation, who)
    sale = execute(runtime, sale, "prepare-issue", "maker", {
        "posting_date": "2026-10-14", "period_id": "period", "policy_code": "FIFO"})
    assert sale["status"] == "IssuePrepared" and sale["cost_admission_policy"] == "partial-return-restituted-v1"
    assert sale["cogs_minor"] == "0" and sale["cogs_entry_id"] is sale["cogs_effect_id"] is None
    return runtime, sale


def test_legacy_positive_original_cannot_insert_a_null_cogs_source_even_before_posting(
    receipt_database: tuple[str, str],
) -> None:
    runtime, source_id, _invoice = create_partial_runtime(receipt_database)
    prepared = prepare_return(runtime, source_id, 1, command="security-legacy-null-control")
    assert prepared["schema_version"] == "customer-partial-return-v1" and prepared["phase"] == 0
    before = capture_rounding(runtime)
    assert len(before) == 79
    with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("maker") as (connection, _, actor):
        source = connection.execute("""SELECT id,original_cogs_effect_id,source_payload,
            source_payload->'original_source'=reconforge.customer_partial_return_source_dispatch(tenant_id,source_order_id) native_equal
            FROM reconforge.customer_partial_return_sources WHERE tenant_id=%s AND source_order_id=%s""",
            (runtime.tenant, source_id)).fetchone()
        assert source is not None and source["original_cogs_effect_id"] is not None and source["native_equal"] is True
        assert "allocation_policy" not in source["source_payload"]
        connection.execute("SELECT set_config('app.customer_partial_return_actor_id',%s,true)", (actor.user_id,))
        # The unchanged native original and maker pass the BEFORE admission.
        # PostgreSQL row CHECK runs before duplicate-key insertion, so the
        # intended new NULL constraint must be the exact observed refusal.
        connection.execute("""INSERT INTO reconforge.customer_partial_return_sources
            SELECT (jsonb_populate_record(NULL::reconforge.customer_partial_return_sources,
                to_jsonb(original)||jsonb_build_object('original_cogs_effect_id',NULL::text))).*
            FROM reconforge.customer_partial_return_sources original WHERE original.tenant_id=%s AND original.id=%s""",
            (runtime.tenant, source["id"]))
    _cause(denied.value, "customer_partial_return_original_cost_evidence")
    assert capture_rounding(runtime) == before


def test_zero_issue_requires_native_review_and_current_third_human_before_zero_children(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, prepared = _prepared_zero_stock(receipt_database)
    before = capture_rounding(runtime)
    with pytest.raises(PostgresInventoryCoreError) as unreviewed, runtime.actor("poster") as (connection, _, actor):
        owner = stock_repository(connection, runtime)
        row = connection.execute("SELECT status,issue_plan FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
            (runtime.tenant, prepared["id"])).fetchone()
        assert row is not None and row["status"] == "IssuePrepared"
        connection.execute("SELECT set_config('app.stock_sales_actor_id',%s,true)", (actor.user_id,))
        # The real native SS1 boundary refuses the physical parent before an
        # unreviewed source can create either zero valuation or consumption.
        owner.inventory.create_movement(movement_number=row["issue_plan"]["entry_number"], movement_type="Delivery",
            organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-14",
            description="Unreviewed native zero-issue attack", source_reference=prepared["id"], source_type="Generated",
            workspace="work", actor_label=row["issue_plan"]["preparer_username"],
            lines=[{"item_code": "ITEM", "quantity": "0.1", "from_location": "MAIN/STOCK"}])
    _cause(unreviewed.value, "stock_sales_owner_phase", "SS1 movement namespace requires its complete StockSales owner.")
    assert capture_rounding(runtime) == before

    reviewed = execute(runtime, prepared, "review-issue", "checker")
    assert reviewed["status"] == "IssueReviewed"
    before = capture_rounding(runtime)
    reached: list[bool] = []
    with pytest.raises(psycopg.errors.CheckViolation) as wrong_human, runtime.actor("poster") as (connection, _, actor):
        owner = stock_repository(connection, runtime)
        native = connection.execute("SELECT issue_reviewer_id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s",
            (runtime.tenant, reviewed["id"])).fetchone()
        assert native is not None and native["issue_reviewer_id"] != actor.user_id
        real_post = owner.inventory.post_movement

        def change_only_native_actor(movement_id: str, *, reason: str, actor_label: str) -> dict[str, Any]:
            result = real_post(movement_id, reason=reason, actor_label=actor_label)
            physical = connection.execute("SELECT status,source_reference FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s",
                (runtime.tenant, movement_id)).fetchone()
            assert physical is not None and physical["status"] == "Posted" and physical["source_reference"] == reviewed["id"]
            reached.append(True)
            # Real application posting actor, review and physical work remain;
            # native zero-child admission must independently reject this GUC.
            connection.execute("SELECT set_config('app.stock_sales_actor_id',%s,true)", (native["issue_reviewer_id"],))
            return result

        with monkeypatch.context() as adversary:
            adversary.setattr(owner.inventory, "post_movement", change_only_native_actor)
            owner.act(reviewed["id"], "deliver", expected_version=reviewed["row_version"], command_id="security-wrong-native-human",
                reason="Real reviewed zero issue with native actor substitution", parameters={}, actor=actor)
    assert reached == [True]
    _cause(wrong_human.value, "inventory_transfer_owner", ACTIVE_MESSAGE)
    assert capture_rounding(runtime) == before

    # The identical reviewed owner can still deliver with its real third human.
    delivered = execute(runtime, reviewed, "deliver", "poster")
    after = capture_rounding(runtime)
    assert delivered["status"] == "Delivered" and delivered["cogs_entry_id"] is delivered["cogs_effect_id"] is None
    assert after["finance_entries"] == before["finance_entries"] and after["finance_posting_effects"] == before["finance_posting_effects"]
    assert len(after["inventory_layer_consumptions"]) == len(before["inventory_layer_consumptions"]) + 1


def test_closed_zero_stock_claim_cannot_admit_fresh_valuation_or_consumption_children(
    receipt_database: tuple[str, str],
) -> None:
    runtime, original = create_remainder_runtime(receipt_database, zero=True)
    post_v2(runtime, prepare_v2(runtime, original, 1, 0, "security-closed-zero-return"))
    sale = create_restituted_resale(runtime)
    assert sale["status"] == "Invoiced" and sale["cogs_minor"] == "0"
    with runtime.actor("maker") as (connection, _, _actor):
        state = connection.execute("SELECT state FROM reconforge.stock_sales_issue_claims WHERE tenant_id=%s AND order_id=%s",
            (runtime.tenant, sale["id"])).fetchone()
        line = connection.execute("SELECT id,value_minor FROM reconforge.inventory_valuation_lines WHERE tenant_id=%s AND valuation_document_id=%s",
            (runtime.tenant, sale["valuation_id"])).fetchone()
        assert state is not None and state["state"] == "Consumed" and line is not None and line["value_minor"] == 0
        consumed = connection.execute("SELECT id,value_minor FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s AND valuation_line_id=%s",
            (runtime.tenant, line["id"])).fetchall()
        assert len(consumed) == 1 and consumed[0]["value_minor"] == 0
    for table, row_id in (("inventory_valuation_lines", line["id"]), ("inventory_layer_consumptions", consumed[0]["id"])):
        before = capture_rounding(runtime)
        with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("poster") as (connection, _, actor):
            connection.execute("SELECT set_config('app.stock_sales_actor_id',%s,true)", (actor.user_id,))
            connection.execute(sql.SQL("""INSERT INTO reconforge.{table}
                SELECT (jsonb_populate_record(NULL::reconforge.{table},
                    to_jsonb(original)||jsonb_build_object('id',%s::text))).*
                FROM reconforge.{table} original WHERE original.tenant_id=%s AND original.id=%s""")
                .format(table=sql.Identifier(table)), ("HOSTILE-CLOSED-" + table, runtime.tenant, row_id))
        _cause(denied.value, "inventory_transfer_owner", ACTIVE_MESSAGE)
        assert capture_rounding(runtime) == before


def test_positive_original_cannot_restore_with_null_cogs_after_real_posting_work(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, source_id, _invoice = create_partial_runtime(receipt_database)
    reviewed = phase(runtime, prepare_return(runtime, source_id, 1, command="security-null-restoration"), "review", "checker")
    assert reviewed["cogs_restored_minor"] == 1200 and len(reviewed["entries"]) == 2
    before = capture_rounding(runtime)
    reached: list[int] = []
    real_restore = PostgresCustomerPartialReturnsRepository._restorations

    def null_original_only(self: PostgresCustomerPartialReturnsRepository, plan: Mapping[str, Any], effects: list[str]) -> None:
        assert plan["id"] == reviewed["id"] and len(effects) == 2
        original_source = self._source_row(plan["source_id"])
        assert original_source["original_cogs_effect_id"] is not None
        reached.append(len(effects))
        real_source = self._source_row

        def altered_source(identifier: str) -> dict[str, Any]:
            assert identifier == original_source["id"]
            return {**real_source(identifier), "original_cogs_effect_id": None}

        with monkeypatch.context() as adversary:
            adversary.setattr(self, "_source_row", altered_source)
            real_restore(self, plan, effects)

    with monkeypatch.context() as adversary:
        adversary.setattr(PostgresCustomerPartialReturnsRepository, "_restorations", null_original_only)
        with pytest.raises(FinancePostingError) as denied:
            phase(runtime, reviewed, "post", "poster")
    assert reached == [2]
    _cause(denied.value, "inventory_transfer_owner", NULL_MESSAGE)
    assert capture_rounding(runtime) == before
