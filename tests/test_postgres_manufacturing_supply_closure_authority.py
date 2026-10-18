"""Focused native current-authority reuse against complete closure delegation."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.infrastructure.postgres_manufacturing_supply_closure import (
    install_postgres_manufacturing_supply_closure,
)
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
from tests import test_postgres_manufacturing_supply_read_authority as authority
from tests.test_postgres_manufacturing_execution import _actually_blocked
from tests.test_postgres_manufacturing_supply_plan import planning_runtime, seed_partial_stock

baseline_receipt_database = authority.baseline_receipt_database
original_manufacturing_database = authority.original_manufacturing_database
baseline_manufacturing_v2_database = authority.baseline_manufacturing_v2_database
base_supply_database = authority.supply_database


@pytest.fixture(scope="module")
def supply_database(base_supply_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg

    with psycopg.connect(base_supply_database[0]) as admin:
        install_postgres_manufacturing_supply_closure(admin)
    yield base_supply_database


fractional_supply = authority.fractional_supply


@pytest.mark.parametrize("revoked", ["permission", "scope"])
@pytest.mark.parametrize("operation", ["get", "receipt"])
def test_delegated_waiting_read_and_receipt_still_recheck_current_authority(
    supply_database: tuple[str, str], revoked: str, operation: str,
) -> None:
    authority.test_waiting_read_and_original_receipt_recheck_current_authority_after_source_lock(supply_database, revoked, operation)


def test_delegated_high_cap_original_replay_and_receipt(fractional_supply: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    authority.test_high_cap_original_command_replay_and_receipt_remain_immutable(fractional_supply, monkeypatch)


@pytest.mark.parametrize("permission", ["manufacturing_supply_plan.read", "finance_core.read"])
@pytest.mark.parametrize("operation", ["get", "list", "receipt"])
def test_delegated_original_unit_price_read_and_receipt_caps(
    fractional_supply: dict[str, Any], monkeypatch: pytest.MonkeyPatch, operation: str, permission: str,
) -> None:
    authority.test_fractional_quote_total_cannot_disclose_original_quote_unit_price(fractional_supply, monkeypatch, operation, permission)


def test_competing_approved_plans_recompute_exclusive_native_stock_after_actual_pool_wait(
    supply_database: tuple[str, str],
) -> None:
    system, request = planning_runtime(supply_database)
    seed_partial_stock(system)
    sources = []
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        for number in ("COMPETING-NET-A", "COMPETING-NET-B"):
            sources.append(owner.create(replace(request, material=replace(request.material, number=number)), command_id=number, actor=actor)["source"])
    pids: dict[str, int] = {}

    def approve_second() -> dict[str, Any]:
        # A distinct human avoids queuing authentication on the first actor's
        # identity row before the native pool waiter PID can be observed.
        with system.actor("poster") as (connection, _, actor):
            connection.execute("SET LOCAL statement_timeout='30s'")
            pids["second"] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            return PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(sources[1]["id"],
                expected_digest=sources[1]["source_digest"], command_id="competing-second-approve", reason="Exact net after current native pool wait", actor=actor)["source"]

    with ThreadPoolExecutor(max_workers=1) as workers:
        with system.actor("checker") as (connection, _, actor):
            holder_pid = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            first = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(sources[0]["id"],
                expected_digest=sources[0]["source_digest"], command_id="competing-first-approve", reason="Hold exclusive original native stock until commit", actor=actor)["source"]
            attempt = workers.submit(approve_second)
            _actually_blocked(system.admin_dsn, pids, "second", holder_pid)
        second = attempt.result(timeout=35)
    def coverage(source: dict[str, Any]) -> dict[str, tuple[int, int]]:
        return {row["item_code"]: (row["coverage"]["onhand_reserved_scaled"], row["coverage"]["shortage_quantity_scaled"]) for row in source["planned_requirements"]}
    assert coverage(first) == {"ITEM": (1, 1), "MATERIAL": (500, 2500)}
    assert coverage(second) == {"ITEM": (0, 2), "MATERIAL": (0, 3000)}
    assert len(first["stock_claims"]) == 2 and second["stock_claims"] == []
    with system.actor("checker") as (connection, _, _):
        for source in (first, second):
            connection.execute("SELECT reconforge.msp_close(%s,%s)", (system.tenant, source["id"]))
