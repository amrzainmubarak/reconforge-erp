"""Native restricted-role landed cost, quantity, FIFO, AP, cash and GL gates."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.landed_cost import LandedCostPreparation
from reconforge.domain.procurement_partial import ProcurementLineQuantity
from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_multiline import (
    CHECKER,
    MAKER,
    POSTER,
    accrue_invoice,
    action,
    create_multiline_runtime,
    create_order,
    enterprise_digest,
    pay_invoice,
    receipt_database,
)

__all__ = ["receipt_database"]


@pytest.fixture
def runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_multiline_runtime(receipt_database)


def request(view: dict[str, Any], number: str = "LANDED-1") -> LandedCostPreparation:
    return LandedCostPreparation(number=number, order_id=view["order"]["id"], expected_version=view["order"]["row_version"],
        lines=tuple(ProcurementLineQuantity(line_id=line["id"], quantity=line["quantity_text"]) for line in view["lines"]),
        freight_minor=777, duty_minor=224, posting_date="2026-10-03", period_id="period", reason="Paid freight and import duty for synthetic goods")


def prepare(runtime: ReceiptRuntime, view: dict[str, Any]) -> dict[str, Any]:
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        arguments = {"command_id": "lc-prepare", "actor": actor}
        plan = owner.prepare(request(view), **arguments)
        assert owner.prepare(request(view), **arguments) == plan
        return plan


def phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, name: str) -> dict[str, Any]:
    with runtime.actor(name) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": "lc-" + operation,
                "reason": "Independent review and atomic receiving", "actor": actor}
        result = owner.act(plan["id"], operation, **args)
        ack = connection.execute("SELECT reconforge.landed_cost_ack(%s,%s,%s) AS ack", (runtime.tenant, plan["id"], result["phase"])).fetchone()["ack"]
        assert ack == result
        assert owner.act(plan["id"], operation, **args) == result
        return result


def state(connection: Any, tenant: str) -> str:
    from psycopg import sql
    value = {"native": enterprise_digest(connection, tenant)}
    for table in ("landed_cost_plans", "landed_cost_allocations", "landed_cost_reviews", "landed_cost_links", "landed_cost_commands"):
        value[table] = [row["value"] for row in connection.execute(sql.SQL("SELECT to_jsonb(x) AS value FROM reconforge.{} x WHERE tenant_id=%s ORDER BY to_jsonb(x)::text")
                        .format(sql.Identifier(table)), (tenant,)).fetchall()]
    return digest_payload(value)


def test_mixed_unit_warehouse_landed_receipts_two_ap_invoices_four_payments(runtime: ReceiptRuntime) -> None:
    view = create_order(runtime)
    plan = phase(runtime, phase(runtime, prepare(runtime, view), "review", CHECKER), "post", POSTER)
    assert plan["phase"] == 2 and plan["amount_minor"] == "1001" and len(plan["allocations"]) == 2
    with runtime.actor(POSTER) as (connection, _, actor):
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        view = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
        assert view["totals"]["received_minor"] == "17000"  # original merchandise matching basis
        layers = connection.execute("""SELECT x.item_code,c.original_quantity_scaled,c.original_value_minor,c.remaining_value_minor
            FROM reconforge.inventory_cost_layers c JOIN reconforge.inventory_items x ON x.tenant_id=c.tenant_id AND x.id=c.item_id
            WHERE c.tenant_id=%s ORDER BY x.item_code""", (runtime.tenant,)).fetchall()
        # Independent integer oracle: freight 777 -> 548/229; duty224 ->158/66.
        assert [tuple(row) for row in layers] == [("ITEM", 10, 12706, 12706), ("WEIGHT", 250, 5295, 5295)]
    view = accrue_invoice(runtime, view, ((0, "4"), (1, "1")))
    first = view["invoices"][-1]
    assert first["total_minor"] == "6800"
    pay_invoice(runtime, first["native_invoice_id"], 3000, "first-1")
    pay_invoice(runtime, first["native_invoice_id"], 3800, "first-2")
    view = accrue_invoice(runtime, view, ((0, "6"), (1, "1.5")))
    second = view["invoices"][-1]
    assert second["total_minor"] == "10200"
    pay_invoice(runtime, second["native_invoice_id"], 5000, "second-1")
    pay_invoice(runtime, second["native_invoice_id"], 5200, "second-2")
    with runtime.actor(POSTER) as (connection, _, actor):
        final = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
        assert final["totals"]["paid_minor"] == "17000" and final["totals"]["outstanding_minor"] == "0"
        # Posted evidence rather than draft totals; all nine native effects.
        balances = connection.execute("""SELECT a.account_code,sum((x->>'debit_minor')::bigint-(x->>'credit_minor')::bigint) balance
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') x
            JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=x->>'account_id'
            WHERE f.tenant_id=%s GROUP BY a.account_code ORDER BY a.account_code""", (runtime.tenant,)).fetchall()
        assert {row["account_code"]: int(row["balance"]) for row in balances} == {"AP": 0, "CASH": -18001, "CLEARING": 0, "INVENTORY": 18001}
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 9
        totals = connection.execute("""SELECT sum((x->>'debit_minor')::bigint),sum((x->>'credit_minor')::bigint)
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') x WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert tuple(totals) == (53002, 53002)


def test_bare_receipt_review_cannot_detach_paid_charge_stage(runtime: ReceiptRuntime) -> None:
    view = create_order(runtime)
    plan = prepare(runtime, view)
    with runtime.actor(MAKER) as (connection, _, actor):
        view = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
        before = state(connection, runtime.tenant)
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation, match="whole conserved bundle|three human stages"):
        action(runtime, view, "review-receipt", CHECKER, plan["allocations"][0]["receipt_id"])
    with runtime.actor(MAKER) as (connection, _, _):
        assert state(connection, runtime.tenant) == before


@pytest.mark.parametrize("name", [MAKER, CHECKER])
def test_three_person_cash_and_receipt_posting_is_mandatory(runtime: ReceiptRuntime, name: str) -> None:
    plan = phase(runtime, prepare(runtime, create_order(runtime)), "review", CHECKER)
    with runtime.actor(MAKER) as (connection, _, _):
        before = state(connection, runtime.tenant)
    with pytest.raises(FinancePostingError, match="three distinct"):
        phase(runtime, plan, "post", name)
    with runtime.actor(MAKER) as (connection, _, _):
        assert state(connection, runtime.tenant) == before


def test_cash_failure_rolls_back_all_stock_and_native_goods_receipts(runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
    plan = phase(runtime, prepare(runtime, create_order(runtime)), "review", CHECKER)
    with runtime.actor(MAKER) as (connection, _, _):
        before = state(connection, runtime.tenant)
    original = PostgresFinancePostingRepository.post
    def fail_cash(self: Any, entry_id: str, **kwargs: Any) -> dict[str, Any]:
        if kwargs["command_id"].startswith("LC1:"):
            raise RuntimeError("injected cash publication failure")
        return original(self, entry_id, **kwargs)
    monkeypatch.setattr(PostgresFinancePostingRepository, "post", fail_cash)
    with pytest.raises(RuntimeError, match="injected cash"):
        phase(runtime, plan, "post", POSTER)
    with runtime.actor(MAKER) as (connection, _, _):
        assert state(connection, runtime.tenant) == before


def test_same_post_under_lost_ack_concurrency_returns_one_business_effect(runtime: ReceiptRuntime) -> None:
    plan = phase(runtime, prepare(runtime, create_order(runtime)), "review", CHECKER)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: phase(runtime, plan, "post", POSTER), range(2)))
    assert results[0] == results[1]
    with runtime.actor(POSTER) as (connection, _, _):
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 3


@pytest.mark.parametrize("attack", ["allocation", "payload", "ack", "phase", "delete", "bare-sql-receipt"])
def test_raw_sql_cannot_forge_or_separate_cost_effects(runtime: ReceiptRuntime, attack: str) -> None:
    plan = prepare(runtime, create_order(runtime))
    with runtime.actor(MAKER) as (connection, _, _):
        before = state(connection, runtime.tenant)
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor(MAKER) as (connection, _, _):
            if attack == "allocation":
                connection.execute("UPDATE reconforge.landed_cost_allocations SET freight_minor=freight_minor+1 WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, plan["id"]))
            elif attack == "payload":
                connection.execute("UPDATE reconforge.landed_cost_plans SET payload=jsonb_set(payload,'{request,freight_minor}','1') WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
            elif attack == "ack":
                connection.execute("UPDATE reconforge.landed_cost_commands SET response_json=jsonb_set(response_json,'{amount_minor}','\"1\"') WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, plan["id"]))
            elif attack == "phase":
                connection.execute("UPDATE reconforge.landed_cost_plans SET phase=phase+1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
            elif attack == "delete":
                connection.execute("DELETE FROM reconforge.landed_cost_allocations WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, plan["id"]))
            else:
                connection.execute("UPDATE reconforge.procurement_partial_receipts SET stage=1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["allocations"][0]["receipt_id"]))
    with runtime.actor(MAKER) as (connection, _, _):
        assert state(connection, runtime.tenant) == before


def test_partial_quantity_cost_allocation_cannot_overreceive(runtime: ReceiptRuntime) -> None:
    view = create_order(runtime)
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        bad = replace(request(view), lines=(ProcurementLineQuantity(line_id=view["lines"][0]["id"], quantity="11"),))
        before = state(connection, runtime.tenant)
        with pytest.raises(FinancePostingError, match="capacity"):
            owner.prepare(bad, command_id="over-receive", actor=actor)
        assert state(connection, runtime.tenant) == before



@pytest.mark.parametrize("change", ["disabled", "revoked"])
def test_raw_command_insert_requires_current_persisted_authority(runtime: ReceiptRuntime, change: str) -> None:
    import psycopg
    plan = prepare(runtime, create_order(runtime))
    with pytest.raises(psycopg.errors.CheckViolation, match="current persisted scoped human authority"), runtime.actor(MAKER) as (connection, _, actor):
        if change == "disabled":
            connection.execute("UPDATE reconforge.identity_users SET disabled=true,disabled_at=clock_timestamp() WHERE tenant_id=%s AND id=%s", (runtime.tenant, actor.user_id))
        else:
            connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,revoked_at=clock_timestamp(),revoked_by='synthetic-reviewer',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='payables.settle'", (runtime.tenant,))
        connection.execute("""INSERT INTO reconforge.landed_cost_commands(tenant_id,workspace_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            SELECT tenant_id,workspace_id,plan_id,operation,'direct-revoked-command',actor_id,request_digest,request_json,response_json
            FROM reconforge.landed_cost_commands WHERE tenant_id=%s AND plan_id=%s AND operation='prepare'""", (runtime.tenant,plan["id"]))
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresLandedCostRepository(connection,runtime.tenant).get(plan["id"],actor=actor) == plan


def test_capitalized_receipt_cost_flows_through_original_fifo_cogs(runtime: ReceiptRuntime, receipt_database: tuple[str, str]) -> None:
    from tests.test_postgres_stock_sales import complete_stock_sale, create_stock_runtime
    plan = phase(runtime, phase(runtime, prepare(runtime, create_order(runtime)), "review", CHECKER), "post", POSTER)
    commercial = create_stock_runtime(receipt_database, base_runtime=runtime, seed_stock=False)
    sale = complete_stock_sale(commercial)
    assert sale["status"] == "Paid"
    with commercial.actor("poster") as (connection, _, actor):
        # Independent source oracle: 12706 minor over 10 EA; five consume exactly 6353.
        layers = connection.execute("""SELECT original_quantity_scaled,original_value_minor,remaining_quantity_scaled,remaining_value_minor
            FROM reconforge.inventory_cost_layers c JOIN reconforge.inventory_items i ON i.tenant_id=c.tenant_id AND i.id=c.item_id
            WHERE c.tenant_id=%s AND i.item_code='ITEM'""", (runtime.tenant,)).fetchall()
        assert [tuple(row) for row in layers] == [(10,12706,5,6353)]
        cogs = connection.execute("""SELECT sum((line->>'debit_minor')::numeric-(line->>'credit_minor')::numeric)
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') line
            JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=line->>'account_id'
            WHERE f.tenant_id=%s AND a.account_code='COGS'""", (runtime.tenant,)).fetchone()[0]
        assert cogs == 6353
        assert PostgresLandedCostRepository(connection,runtime.tenant).get(plan["id"],actor=actor) == plan


@pytest.mark.parametrize("change", ["cash-classification", "cash-code", "journal-code"])
def test_raw_master_mutation_cannot_detach_landed_financial_mapping(runtime: ReceiptRuntime, change: str) -> None:
    import psycopg

    from reconforge.infrastructure.postgres import PostgresTenantBoundary
    plan = prepare(runtime, create_order(runtime))
    # Actual tenant/workspace master authority; entity-selected UPDATE is filtered by RLS.
    with pytest.raises(psycopg.errors.CheckViolation), PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        if change == "journal-code":
            changed = connection.execute("UPDATE reconforge.finance_journals SET journal_code='ALTERED' WHERE tenant_id=%s AND journal_code='STOCK' RETURNING id", (runtime.tenant,)).fetchall()
        else:
            changed = connection.execute("UPDATE reconforge.finance_accounts SET " + ("account_type='Liability'" if change == "cash-classification" else "account_code='ALTERED-CASH'") + " WHERE tenant_id=%s AND account_code='CASH' RETURNING id", (runtime.tenant,)).fetchall()
        assert len(changed) == 1, "The actual native master row must be exercised."
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresLandedCostRepository(connection,runtime.tenant).get(plan["id"],actor=actor) == plan


def test_legacy_worker_evidence_needs_no_landed_owner_read(runtime: ReceiptRuntime) -> None:
    """Invoker audit/outbox closure ignores unrelated images, including updates."""
    from collections.abc import Iterator
    from contextlib import contextmanager
    from uuid import uuid4

    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres import set_local_tenant_scope
    from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository

    prepare(runtime, create_order(runtime))  # Owner data really exists in this tenant.
    role = "lc_legacy_worker_" + uuid4().hex[:12]
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS").format(sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
        for table in ("domain_audit_ledger_state", "domain_audit_events", "outbox_events"):
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(role)))

    @contextmanager
    def worker() -> Iterator[Any]:
        with psycopg.connect(runtime.admin_dsn) as connection:
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            set_local_tenant_scope(connection, runtime.tenant)
            assert connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False)
            for table in ("landed_cost_plans", "landed_cost_allocations", "landed_cost_reviews", "landed_cost_links", "landed_cost_commands"):
                assert connection.execute("SELECT has_table_privilege(current_user,%s,'SELECT')", ("reconforge." + table,)).fetchone() == (False,)
            yield connection

    def evidence(connection: Any, *, audit_override: dict[str, str] | None = None,
                 outbox_override: dict[str, str] | None = None) -> str:
        audit = {"object_type": "reconciliation_run", "object_id": "legacy-matcher", "action": "run_completed", **(audit_override or {})}
        PostgresAuditEventRepository(connection, runtime.tenant).append(actor_label="legacy-worker", **audit)
        event = {"event_id": "legacy-event-" + uuid4().hex, "event_type": "reconciliation.run_completed",
                 "aggregate_type": "reconciliation_run", "aggregate_id": "legacy-matcher", **(outbox_override or {})}
        connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES(%s,%s,%s,%s,%s,'{}'::jsonb)""", (runtime.tenant,event["event_id"],event["event_type"],event["aggregate_type"],event["aggregate_id"]))
        return event["event_id"]

    try:
        with worker() as connection:
            identifier = evidence(connection)
            changed = connection.execute("""UPDATE reconforge.outbox_events SET status='Claimed',claimed_by='legacy-worker',
                claimed_at=clock_timestamp()+interval '60 seconds',attempt_count=attempt_count+1,lease_generation=lease_generation+1
                WHERE tenant_id=%s AND event_id=%s RETURNING event_id""", (runtime.tenant,identifier)).fetchall()
            assert len(changed) == 1
        with worker() as connection:
            assert connection.execute("SELECT status,claimed_by,lease_generation FROM reconforge.outbox_events WHERE tenant_id=%s AND event_id=%s", (runtime.tenant,identifier)).fetchone() == ("Claimed", "legacy-worker", 1)
        # Each retained LC discriminator independently prevents the shortcut.
        for marker in ({"object_type": "landed_cost"}, {"object_id": "LC1-reserved"}, {"action": "landed_cost_prepared"}):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="landed_cost_plans"), worker() as connection:
                evidence(connection, audit_override=marker)
        for marker in ({"aggregate_type": "landed_cost"}, {"aggregate_id": "LC1-reserved"},
                       {"event_type": "landed_cost_prepared"}, {"event_id": "LCOUT-reserved"}):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="landed_cost_plans"), worker() as connection:
                evidence(connection, outbox_override=marker)
    finally:
        with psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_landed_outbox_identity_cannot_be_renamed_out_of_owner_closure(runtime: ReceiptRuntime) -> None:
    import psycopg

    plan = prepare(runtime, create_order(runtime))
    with pytest.raises(psycopg.errors.RaiseException, match="outbox event identity and payload are immutable"), runtime.actor(MAKER) as (connection, _, _):
        changed = connection.execute("""UPDATE reconforge.outbox_events SET aggregate_type='reconciliation_run',
            aggregate_id='legacy-matcher',event_type='reconciliation.run_completed' WHERE tenant_id=%s AND aggregate_type='landed_cost'
            AND aggregate_id=%s RETURNING event_id""", (runtime.tenant,plan["id"])).fetchall()
        assert len(changed) == 1
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresLandedCostRepository(connection,runtime.tenant).get(plan["id"],actor=actor) == plan
