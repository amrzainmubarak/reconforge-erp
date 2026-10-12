"""AD1 whole-original and ME2 claims share one actual serialized Core gate."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from queue import Queue
from threading import Event
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.manufacturing_execution import OrderPreparation
from reconforge.domain.manufacturing_execution_v2 import (
    ManufacturingOrderPreparation,
    RoutingPreparation,
    WorkcenterPreparation,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_accrual_deferral import PostgresAccrualDeferralRepository
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.test_postgres_accrual_deferral import (
    ScheduleRuntime,
    accrual_deferral_database,
    configure_runtime,
    paid_original,
    preparation,
    publish,
    pytestmark,
    receipt_database,
)
from tests.test_postgres_manufacturing_execution import _actually_blocked, approved_bom
from tests.test_postgres_manufacturing_execution_v2 import SCOPE, owner_phase, system

__all__ = ["accrual_deferral_database", "pytestmark", "receipt_database"]


def shared_runtime(database: tuple[str, str]) -> tuple[ScheduleRuntime, dict[str, Any], ManufacturingOrderPreparation]:
    # The existing manufacturing fixture posts two genuine reviewed native
    # inventory receipts; it does not manufacture stock or expense balances.
    rt = configure_runtime(system(database))
    original = paid_original(rt)
    bom = approved_bom(rt.base)
    with rt.actor("maker") as (connection, _, actor):
        center = PostgresManufacturingExecutionV2Repository(connection, rt.base.tenant).create_workcenter(
            WorkcenterPreparation("AD1-ME2-SHARED", 1, "Approved shared original workcenter", "2026-10-01", "2026-10-31", SCOPE,
                "Synthetic genuine native ownership proof"), command_id="shared-center", actor=actor)
    center = owner_phase(rt.base, center, "approve", "definition")
    with rt.actor("maker") as (connection, _, actor):
        route = PostgresManufacturingExecutionV2Repository(connection, rt.base.tenant).create_routing(
            RoutingPreparation("AD1-ME2-ROUTE", 1, bom["id"], "2026-10-01", "2026-10-31",
                [{"sequence": 1, "workcenter_id": center["id"], "name": "Original approved operation", "minutes_per_batch": 60}], SCOPE,
                "Genuine routing for one original expense claim"), command_id="shared-routing", actor=actor)
        line_id = connection.execute("SELECT id FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s AND debit_minor>0",
            (rt.base.tenant, original["entry_id"])).fetchone()["id"]
    route = owner_phase(rt.base, route, "approve", "definition")
    material = OrderPreparation(number="ME2-SHARED-ORIGINAL", bom_version_id=bom["id"], output_quantity="10",
        component_location_code="MAIN/STOCK", finished_location_code="MAIN/STOCK", component_policy_code="FIFO", finished_policy_code="MFG",
        journal_code="STOCK", wip_account_code="WIP", scrap_account_code="SCRAP", period_id="period", posting_date="2026-10-04", **SCOPE,
        reason="Native material source with one immutable original paid expense")
    request = ManufacturingOrderPreparation(material, route["id"], [{"effect_id": original["id"], "line_id": line_id,
        "kind": "Labor", "operation_sequence": 1, "minutes": 60, "rate_minor_per_hour": 500}])
    return rt, original, request


def claim(rt: ScheduleRuntime, original: dict[str, Any], request: ManufacturingOrderPreparation,
          connection: Any, actor: Any, *, ad1: bool) -> dict[str, Any]:
    if ad1:
        return PostgresAccrualDeferralRepository(connection, rt.base.tenant).prepare_source(
            replace(preparation("attach_paid_expense"), original_effect_id=original["id"]), command_id="shared-ad1", actor=actor)
    return PostgresManufacturingExecutionV2Repository(connection, rt.base.tenant).create_order(request, command_id="shared-me2", actor=actor)


def directory(rt: ScheduleRuntime, effect_id: str) -> list[dict[str, Any]]:
    with rt.actor("maker") as (connection, repository, _):
        rows = [dict(row) for row in connection.execute("""SELECT g.owner_namespace,g.id FROM reconforge.financial_effect_ownership_guards g
            WHERE g.tenant_id=%s AND g.source_effect_id=%s AND NOT EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_releases r
             WHERE r.tenant_id=g.tenant_id AND r.guard_id=g.id) ORDER BY g.id""", (rt.base.tenant, effect_id))]
        assert len(repository.owner.posting._get_effect(effect_id)["snapshot"]["lines"]) == 2
        return rows


@pytest.mark.parametrize("ad1_first", [True, False])
def test_whole_original_claim_is_exclusive_in_both_directions_and_cancel_releases_same_directory(
    accrual_deferral_database: tuple[str, str], ad1_first: bool,
) -> None:
    import psycopg

    rt, original, request = shared_runtime(accrual_deferral_database)
    with rt.actor("maker") as (connection, _, actor):
        winner = claim(rt, original, request, connection, actor, ad1=ad1_first)
    first_directory = directory(rt, original["id"])
    assert len(first_directory) == 1 and first_directory[0]["owner_namespace"] == ("AD1" if ad1_first else "ME2")
    with pytest.raises((FinancePostingError, psycopg.errors.CheckViolation)), rt.actor("maker") as (connection, _, actor):
        claim(rt, original, request, connection, actor, ad1=not ad1_first)
    assert directory(rt, original["id"]) == first_directory
    if ad1_first:
        with rt.actor("maker") as (_, repository, actor):
            cancel = repository.prepare_cancellation(winner["source_id"], reason="Original attachment cancelled before financial consumption",
                command_id="shared-ad1-cancel", actor=actor)
        publish(rt, cancel, "shared-ad1-cancel")
    else:
        owner_phase(rt.base, winner, "cancel")
    assert directory(rt, original["id"]) == []
    with rt.actor("maker") as (connection, repository, actor):
        claim(rt, original, request, connection, actor, ad1=not ad1_first)
        assert repository.owner.posting._get_effect(original["id"]) == original
        # Both operations only reserve a source at this stage; the one paid
        # cash original and two original inventory receipts remain unchanged.
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (rt.base.tenant,)).fetchone()["n"] == 3
        assert connection.execute("SELECT count(*) AS n FROM reconforge.financial_effect_ownership_releases WHERE tenant_id=%s", (rt.base.tenant,)).fetchone()["n"] == 1
    active = directory(rt, original["id"])
    assert len(active) == 1 and active[0]["owner_namespace"] == ("ME2" if ad1_first else "AD1")


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("ad1_first", [True, False])
def test_actual_shared_gate_lock_wait_has_one_owner_and_rr_stale_snapshot_serialization(
    accrual_deferral_database: tuple[str, str], isolation: str, ad1_first: bool,
) -> None:
    import psycopg

    rt, original, request = shared_runtime(accrual_deferral_database)
    with rt.actor("maker") as (connection, _, retained_actor):
        connection.execute("SELECT reconforge.touch_financial_effect_claim_gate(%s,%s)", (rt.base.tenant, original["id"]))
        principal = current_server_principal()
    assert principal is not None
    ready, proceed = Event(), Event()
    pid: Queue[int] = Queue()

    def follower() -> Any:
        try:
            with closing(rt.base.factory.connect()) as connection, connection.transaction(), server_principal_context(principal):
                statement = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" if isolation == "REPEATABLE READ" else "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
                connection.execute(statement)
                set_local_tenant_scope(connection, rt.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity")
                assert connection.execute("SELECT version FROM reconforge.financial_effect_claim_gates WHERE tenant_id=%s AND source_effect_id=%s",
                    (rt.base.tenant, original["id"])).fetchone() is not None
                pid.put(connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
                ready.set()
                assert proceed.wait(20)
                if isolation == "REPEATABLE READ":
                    # Public financial mutations require RC. This exercises
                    # the existing native version fence under an actual RR
                    # snapshot without pretending public RR support.
                    return connection.execute("SELECT reconforge.touch_financial_effect_claim_gate(%s,%s)", (rt.base.tenant, original["id"])).fetchone()
                return claim(rt, original, request, connection, retained_actor, ad1=not ad1_first)
        except (FinancePostingError, psycopg.Error) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=1) as workers:
        with rt.actor("maker") as (connection, _, actor):
            claim(rt, original, request, connection, actor, ad1=ad1_first)
            holder_pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            pending = workers.submit(follower)
            assert ready.wait(20)
            follower_pid = pid.get(timeout=1)
            proceed.set()
            _actually_blocked(rt.base.admin_dsn, {"follower": follower_pid}, "follower", holder_pid)
        refused = pending.result(timeout=30)
    if isolation == "REPEATABLE READ":
        assert isinstance(refused, psycopg.errors.SerializationFailure)
    else:
        assert isinstance(refused, (FinancePostingError, psycopg.errors.CheckViolation))
    active = directory(rt, original["id"])
    assert len(active) == 1 and active[0]["owner_namespace"] == ("AD1" if ad1_first else "ME2")
    with rt.actor("maker") as (_, repository, _):
        assert repository.owner.posting._get_effect(original["id"]) == original
