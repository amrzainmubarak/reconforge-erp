"""Original native source cycles and adversarial restore validation of delegation."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_manufacturing_supply_closure import (
    DOWNGRADE_SQL,
    install_postgres_manufacturing_supply_closure,
)
from tests import test_postgres_manufacturing_supply_plan as original
from tests.manufacturing_supply_browser import manufacturing_supply_proof

baseline_receipt_database = original.baseline_receipt_database
original_manufacturing_database = original.original_manufacturing_database
baseline_manufacturing_v2_database = original.baseline_manufacturing_v2_database
supply_database = original.supply_database


@pytest.fixture(scope="module")
def delegated_supply_database(supply_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg

    with psycopg.connect(supply_database[0]) as connection:
        install_postgres_manufacturing_supply_closure(connection)
    yield supply_database


def test_original_full_onhand_handoff_and_immutable_replay(delegated_supply_database: tuple[str, str]) -> None:
    original.test_complete_original_onhand_custody_atomic_native_handoff_without_procurement(delegated_supply_database)


def test_original_blind_native_withdrawal_refusal_and_cancel_release(delegated_supply_database: tuple[str, str]) -> None:
    original.test_exclusive_partial_onhand_refuses_ordinary_posted_withdrawal_without_private_planner_select_then_cancel_releases(
        delegated_supply_database,
    )


@pytest.mark.parametrize("signature,call,delimiter", [
    ("pp_verify_order(text,text)", "PERFORM reconforge.pc_close(t,i);", "$pc$"),
    ("inventory_quantity_check_capacity(text,text,text,text,text)", "PERFORM reconforge.inventory_quantity_free_fifo(t,w,e,i);", "$quantity$"),
])
@pytest.mark.parametrize("drift", ["commented", "early-return", "definer", "search-path"])
def test_changed_native_delegate_refuses_before_either_owned_function_replacement(
    delegated_supply_database: tuple[str, str], signature: str, call: str, delimiter: str, drift: str,
) -> None:
    import psycopg

    with psycopg.connect(delegated_supply_database[0]) as admin:
        originals = [admin.execute("SELECT pg_get_functiondef(%s::regprocedure)", ("reconforge." + name,)).fetchone()[0]
            for name in ("msp_close(text,text)", "msp_purchase_close(text,text)")]
        definition = admin.execute("SELECT pg_get_functiondef(%s::regprocedure)", ("reconforge." + signature,)).fetchone()[0]
        if drift == "commented":
            changed = definition.replace(call, "/* " + call + " */ NULL;", 1)
        elif drift == "early-return":
            changed = definition.replace("BEGIN", "BEGIN RETURN;", 1)
        elif drift == "definer":
            changed = definition.replace("LANGUAGE plpgsql", "LANGUAGE plpgsql SECURITY DEFINER", 1)
        else:
            changed = definition.replace("SET search_path TO 'pg_catalog'", "SET search_path TO 'public'", 1)
        assert changed != definition
        with pytest.raises(psycopg.errors.CheckViolation, match="delegate"), admin.transaction():
            admin.execute(changed)
            install_postgres_manufacturing_supply_closure(admin)
        assert originals == [admin.execute("SELECT pg_get_functiondef(%s::regprocedure)", ("reconforge." + name,)).fetchone()[0]
            for name in ("msp_close(text,text)", "msp_purchase_close(text,text)")]


def test_original_partial_receipts_ap_budget_wip_qc_fg_and_restore_counterexamples(
    delegated_supply_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    from psycopg import sql

    captured: list[Any] = []
    create_runtime = original.planning_runtime

    def capture(database: tuple[str, str]) -> tuple[Any, Any]:
        system, request = create_runtime(database)
        captured.append(system)
        return system, request

    with monkeypatch.context() as patch:
        patch.setattr(original, "planning_runtime", capture)
        original.test_actual_partial_stock_shortage_partial_receipt_ap_budget_atomic_me2_wip_qc_fg_gl_cycle(delegated_supply_database)
    assert len(captured) == 1
    system = captured[0]
    before = manufacturing_supply_proof(system, actor_name="poster")
    source = before["populations"]["manufacturing_supply_plans"][0]
    plan_id = source["id"]
    with system.actor("poster") as (connection, _, _), connection.transaction(force_rollback=True):
        for version in range(1, source["row_version"] + 1):
            connection.execute("SELECT reconforge.msp_evidence(%s,%s,%s)", (system.tenant, plan_id, version))
        connection.execute("SELECT reconforge.msp_close(%s,%s)", (system.tenant, plan_id))

    tamper = (
        "UPDATE reconforge.manufacturing_supply_commands SET response_json=jsonb_set(response_json,'{source,phase}','3') WHERE tenant_id=%s AND operation='handoff'",
        "UPDATE reconforge.manufacturing_supply_commands SET actor_id='wrong-original-human' WHERE tenant_id=%s AND operation='handoff'",
        "DELETE FROM reconforge.manufacturing_supply_commands WHERE tenant_id=%s AND operation='handoff'",
        "UPDATE reconforge.domain_audit_events SET metadata_json=metadata_json||jsonb_build_object('reason','altered-original-reason') WHERE tenant_id=%s AND action='manufacturing_supply_plan.handoff'",
        "UPDATE reconforge.manufacturing_execution_v2_commands SET response_json=jsonb_build_object('foreign_native_response',TRUE) WHERE tenant_id=%s AND operation='create'",
        "DELETE FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s",
        "UPDATE reconforge.inventory_units_of_measure SET decimal_places=2 WHERE tenant_id=%s AND uom_code='KG'",
    )
    role = psycopg.conninfo.conninfo_to_dict(delegated_supply_database[1])["user"]
    for statement in tamper:
        with psycopg.connect(system.admin_dsn) as admin, pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
            # A restore operator loads adversarial originals without writer
            # triggers, then the ordinary role runs the complete real closure.
            admin.execute("SET LOCAL session_replication_role='replica'")
            cursor = admin.execute(statement, (system.tenant,))
            assert cursor.rowcount > 0
            admin.execute("SET LOCAL session_replication_role='origin'")
            set_local_tenant_scope(admin, system.tenant, "org", workspace_id="work", legal_entity_id="entity")
            admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            admin.execute("SELECT reconforge.msp_close(%s,%s)", (system.tenant, plan_id))
        assert manufacturing_supply_proof(system, actor_name="poster")["populations"] == before["populations"]

    # The inverse changes functions alone and accepts retained business history.
    with psycopg.connect(system.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
    with system.actor("poster") as (connection, _, _), connection.transaction(force_rollback=True):
        connection.execute("SELECT reconforge.msp_close(%s,%s)", (system.tenant, plan_id))
    assert manufacturing_supply_proof(system, actor_name="poster")["populations"] == before["populations"]
    with psycopg.connect(system.admin_dsn) as admin:
        install_postgres_manufacturing_supply_closure(admin)
