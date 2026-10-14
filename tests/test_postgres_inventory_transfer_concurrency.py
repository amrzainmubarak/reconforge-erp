"""Canonical146 competing original claims, retained commands and atomic failures."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Queue
from threading import Event
from time import monotonic, sleep
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.test_postgres_inventory_transfer import (
    TABLES,
    baseline_receipt_database,
    native_business,
    phase,
    physical,
    request,
    transfer_database,
    transfer_runtime,
)

_ = (baseline_receipt_database, transfer_database)
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}


def _create(runtime: Any, number: str, quantity: str = "1", *, reverse: bool = False) -> dict[str, Any]:
    args = replace(request(number), quantity=quantity)
    if reverse:
        args = replace(args, from_location="SECOND/STOCK", to_location="MAIN/STOCK")
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresInventoryTransferRepository(connection, runtime.tenant).create(args, command_id=number + "-create", actor=actor)


def _cached(runtime: Any, person: str) -> tuple[Any, Any]:
    with runtime.actor(person) as (_, _, actor):
        principal = current_server_principal()
        assert principal is not None and principal.user.id == person and actor.user_id == person
        return actor, principal


def _worker(runtime: Any, cached: tuple[Any, Any], source: dict[str, Any], operation: str, command: str,
            started: Queue[int], held: Event | None = None, release: Event | None = None) -> dict[str, Any]:
    actor, principal = cached
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
        connection.execute("SET LOCAL statement_timeout='12s'")
        started.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
        result = PostgresInventoryTransferRepository(connection, runtime.tenant).act(source["id"], operation,
            expected_digest=source["source_digest"], expected_version=source["row_version"], command_id=command,
            reason="Exact original concurrent " + operation, actor=actor)
        if held is not None:
            held.set()
            assert release is not None and release.wait(10), "The test must release its own bounded transaction."
        return result


def _blocked(runtime: Any, waiter: int, holder: int) -> None:
    import psycopg

    deadline = monotonic() + 5
    with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
        while True:
            row = observer.execute("SELECT pg_blocking_pids(%s),wait_event_type FROM pg_stat_activity WHERE pid=%s", (waiter, waiter)).fetchone()
            if row is not None and holder in row[0] and row[1] == "Lock":
                return
            assert monotonic() < deadline, "The second genuine native command must wait on the first transaction."
            sleep(0.02)


def _originals(runtime: Any) -> bytes:
    with runtime.actor("poster") as (connection, _, _):
        assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {
            "rolsuper": False, "rolbypassrls": False,
        }
        return canonical_json(native_business(connection, runtime.tenant)).encode()


def test_two_distinct_reviewers_compete_for_actual_three_units_without_oversubscription(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    left, right = _create(runtime, "RACE-REVIEW-A", "2"), _create(runtime, "RACE-REVIEW-B", "2")
    original = _originals(runtime)
    checker, poster = _cached(runtime, "checker"), _cached(runtime, "poster")
    first_started, second_started, held, release = Queue(), Queue(), Event(), Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(_worker, runtime, checker, left["source"], "review", "competing-review-a", first_started, held, release)
        try:
            first_pid = first_started.get(timeout=5)
            assert held.wait(5), "The first independent reviewer must retain its actual two-unit claim."
            second = workers.submit(_worker, runtime, poster, right["source"], "review", "competing-review-b", second_started)
            _blocked(runtime, second_started.get(timeout=5), first_pid)
        finally:
            release.set()
        winner = first.result(timeout=15)
        with pytest.raises(FinancePostingError) as refused:
            second.result(timeout=15)
    assert refused.value.code == "inventory_transfer_capacity_conflict"
    with runtime.actor("poster") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert winner["source"]["phase"] == 1 and winner["source"]["claim"]["quantity_scaled"] == 2
        assert owner.get(right["source"]["id"], actor=actor) == right["source"]
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        assert dict(connection.execute("SELECT count(*) n,sum(quantity_scaled) q FROM reconforge.inventory_transfer_claims WHERE tenant_id=%s AND state='Active'",
            (runtime.tenant,)).fetchone()) == {"n": 1, "q": 2}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s AND command_id='competing-review-b'",
            (runtime.tenant,)).fetchone()["n"] == 0
    assert _originals(runtime) == original


def test_opposed_locations_post_under_one_original_pool_without_deadlock(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    opening = phase(runtime, phase(runtime, _create(runtime, "OPPOSED-OPENING", "2"), "review", "checker"), "post", "poster")
    left = phase(runtime, _create(runtime, "OPPOSED-A-B"), "review", "checker")
    right = phase(runtime, _create(runtime, "OPPOSED-B-A", reverse=True), "review", "checker")
    original = _originals(runtime)
    poster = _cached(runtime, "poster")
    first_started, second_started, held, release = Queue(), Queue(), Event(), Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(_worker, runtime, poster, left["source"], "post", "opposed-a-b-post", first_started, held, release)
        try:
            first_pid = first_started.get(timeout=5)
            assert held.wait(5)
            second = workers.submit(_worker, runtime, poster, right["source"], "post", "opposed-b-a-post", second_started)
            _blocked(runtime, second_started.get(timeout=5), first_pid)
        finally:
            release.set()
        forward, backward = first.result(timeout=15), second.result(timeout=15)
    with runtime.actor("poster") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert physical(connection, runtime) == {"MAIN/STOCK": 1, "SECOND/STOCK": 2}
        for result in (opening, forward, backward):
            source = result["source"]
            assert owner.get(source["id"], actor=actor) == source
            assert source["claim"]["state"] == "Posted" and source["release"]["target_movement_id"] == source["native_movement_id"]
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_releases WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 3
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_claims WHERE tenant_id=%s AND state='Active'", (runtime.tenant,)).fetchone()["n"] == 0
    assert _originals(runtime) == original


def test_same_exact_post_command_races_then_replays_one_native_business_effect(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    reviewed = phase(runtime, _create(runtime, "SAME-COMMAND"), "review", "checker")
    original, poster = _originals(runtime), _cached(runtime, "poster")
    first_started, second_started, held, release = Queue(), Queue(), Event(), Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(_worker, runtime, poster, reviewed["source"], "post", "same-original-post", first_started, held, release)
        try:
            first_pid = first_started.get(timeout=5)
            assert held.wait(5)
            second = workers.submit(_worker, runtime, poster, reviewed["source"], "post", "same-original-post", second_started)
            _blocked(runtime, second_started.get(timeout=5), first_pid)
        finally:
            release.set()
        posted, replayed = first.result(timeout=15), second.result(timeout=15)
    assert posted == replayed
    with runtime.actor("poster") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.act(reviewed["source"]["id"], "post", expected_digest=reviewed["source"]["source_digest"], expected_version=2,
            command_id="same-original-post", reason="Exact original concurrent post", actor=actor) == posted
        assert physical(connection, runtime) == {"MAIN/STOCK": 2, "SECOND/STOCK": 1}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s AND command_id='same-original-post'",
            (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_events WHERE tenant_id=%s AND operation='post'", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_releases WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s AND movement_type='Transfer' AND status='Posted'",
            (runtime.tenant,)).fetchone()["n"] == 1
    assert _originals(runtime) == original


def _rollback_rows(connection: Any, tenant: str) -> bytes:
    from psycopg import sql

    names = (*TABLES, "inventory_quantity_source_guards", "inventory_quantity_source_releases", "inventory_quantity_claim_gates",
        "inventory_movements", "inventory_movement_lines", "domain_audit_events", "outbox_events")
    rows = {name: [row["original"] for row in connection.execute(sql.SQL(
        "SELECT to_jsonb(t) original FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (tenant,))]
        for name in names}
    return canonical_json(rows).encode()


def test_failure_after_terminal_release_before_native_post_rolls_back_and_exact_retry_succeeds(
        transfer_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = transfer_runtime(transfer_database)
    reviewed = phase(runtime, _create(runtime, "RELEASE-FAILURE"), "review", "checker")
    original = _originals(runtime)
    with runtime.actor("poster") as (connection, _, actor):
        owner, source = PostgresInventoryTransferRepository(connection, runtime.tenant), reviewed["source"]
        before, visited = _rollback_rows(connection, runtime.tenant), []

        def after_release(identifier: str, **_: Any) -> None:
            assert identifier == source["native_movement_id"]
            state = connection.execute("SELECT state FROM reconforge.inventory_transfer_claims WHERE tenant_id=%s AND transfer_id=%s",
                (runtime.tenant, source["id"])).fetchone()["state"]
            release = connection.execute("SELECT target_movement_id,purpose FROM reconforge.inventory_transfer_releases WHERE tenant_id=%s AND transfer_id=%s",
                (runtime.tenant, source["id"])).fetchone()
            assert state == "Posted" and dict(release) == {"target_movement_id": identifier, "purpose": "Post"}
            assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s AND owner_namespace='IT1'",
                (runtime.tenant,)).fetchone()["n"] == 1
            assert connection.execute("SELECT status FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s",
                (runtime.tenant, identifier)).fetchone()["status"] == "Draft"
            visited.append(identifier)
            raise FinancePostingError("it1_test_injected_after_release", "Synthetic failure before native posting")

        with monkeypatch.context() as patch:
            patch.setattr(owner.inventory, "post_movement", after_release)
            with pytest.raises(FinancePostingError) as failure:
                owner.act(source["id"], "post", expected_digest=source["source_digest"], expected_version=2,
                    command_id="exact-release-retry", reason="Exact original failure retry", actor=actor)
        assert failure.value.code == "it1_test_injected_after_release" and visited == [source["native_movement_id"]]
        assert _rollback_rows(connection, runtime.tenant) == before
        assert owner.get(source["id"], actor=actor) == source
        posted = owner.act(source["id"], "post", expected_digest=source["source_digest"], expected_version=2,
            command_id="exact-release-retry", reason="Exact original failure retry", actor=actor)
        assert posted["source"]["claim"]["state"] == "Posted" and posted["source"]["phase"] == 2
        assert physical(connection, runtime) == {"MAIN/STOCK": 2, "SECOND/STOCK": 1}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s AND command_id='exact-release-retry'",
            (runtime.tenant,)).fetchone()["n"] == 1
    assert _originals(runtime) == original


@pytest.mark.parametrize(("operation", "person"), [("review", "maker"), ("post", "maker"), ("post", "checker")])
def test_native_current_three_human_separation_refuses_self_review_and_post(
        transfer_database: tuple[str, str], operation: str, person: str) -> None:
    runtime = transfer_runtime(transfer_database)
    source = _create(runtime, "SELF-" + operation + "-" + person)
    if operation == "post":
        source = phase(runtime, source, "review", "checker")
    original = _originals(runtime)
    with runtime.actor(person) as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        with pytest.raises(FinancePostingError) as refusal:
            owner.act(source["source"]["id"], operation, expected_digest=source["source"]["source_digest"],
                expected_version=source["source"]["row_version"], command_id="self-denied", reason="Synthetic self-governance refusal", actor=actor)
        assert refusal.value.code == "inventory_transfer_governance_conflict"
        assert owner.get(source["source"]["id"], actor=actor) == source["source"]
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s AND command_id='self-denied'", (runtime.tenant,)).fetchone()["n"] == 0
    assert _originals(runtime) == original
