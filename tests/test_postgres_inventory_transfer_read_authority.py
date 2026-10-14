"""Actual current authority after native waits and immutable delivery custody."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from time import monotonic, sleep

import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.test_postgres_inventory_transfer import (
    add_approved_receipt,
    baseline_receipt_database,
    consume_original,
    native_business,
    request,
    transfer_database,
    transfer_runtime,
)

_ = (baseline_receipt_database, transfer_database)


@pytest.mark.parametrize("permission", ["inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"])
def test_actual_complete_single_item_multilayer_consumption_document_requires_whole_original_amount(transfer_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch, permission: str) -> None:
    import json
    import os
    from pathlib import Path

    import reconforge.infrastructure.postgres_operational_finance as core
    from tests.inventory_transfer_browser import inventory_transfer_proof

    runtime = transfer_runtime(transfer_database)
    add_approved_receipt(runtime, "SECOND-COMPLETE-COST-ORIGINAL")
    consumed = consume_original(runtime, "WHOLE-ORIGINAL-CONSUMPTION", quantity="5")
    with runtime.actor("maker") as (connection, _, actor):
        document = connection.execute("SELECT total_value_minor FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND id=%s", (runtime.tenant, consumed["id"])).fetchone()
        assert document["total_value_minor"] == 6000
        created = PostgresInventoryTransferRepository(connection, runtime.tenant).create(request(), command_id="multilayer-whole-create", actor=actor)
        cost = created["source"]["cost_snapshot"]
        assert cost["remaining_value_minor"] == 1200 and len(cost["sources"]) == 2
        assert all(source["layer"]["original_value_minor"] == 3600 for source in cost["sources"])
        assert sum(history["value_minor"] for source in cost["sources"] for history in source["consumptions"]) == 6000
        original = canonical_json(native_business(connection, runtime.tenant))
    maximum = "60"
    observed: list[Decimal] = []

    def bounded(principal, **context):
        if context["required_permission"] == permission and context.get("amount") is not None:
            observed.append(context["amount"])
            return evaluate_principal_access(principal, maximum_amount=Decimal(maximum), **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(core, "evaluate_principal_access", bounded)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(created["source"]["id"], actor=actor) == created["source"]
        assert owner.create(request(), command_id="multilayer-whole-create", actor=actor) == created
    if directory := os.environ.get("RECONFORGE_IT1_NATIVE_PROOF_DIR"):
        with (Path(directory) / ("multilayer-original-" + permission + ".json")).open("x", encoding="utf-8") as target:
            json.dump(inventory_transfer_proof(runtime, actor_name="poster"), target, indent=2, sort_keys=True, allow_nan=False)
            target.write("\n")
    maximum = "36"
    for operation in ("get", "list", "evidence", "replay", "receipt", "new-response"):
        with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
            owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
            if operation == "list":
                owner.list_transfers(request().scope, actor=actor)
            elif operation == "replay":
                owner.create(request(), command_id="multilayer-whole-create", actor=actor)
            elif operation == "receipt":
                owner.command_receipt(created["source"]["id"], "multilayer-whole-create", created, actor=actor)
            elif operation == "new-response":
                owner.create(request("REFUSED-MULTILAYER-WHOLE"), command_id="refuse-multilayer-whole", actor=actor)
            else:
                getattr(owner, operation)(created["source"]["id"], actor=actor)
        assert "denied" in refused.value.code
    assert observed and set(observed) == {Decimal("60.00")}
    with runtime.actor("maker") as (connection, _, _):
        assert canonical_json(native_business(connection, runtime.tenant)) == original
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_actual_first_read_permission_withdrawn_during_identity_wait_refuses_original(transfer_database: tuple[str, str]) -> None:
    import psycopg

    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        source = PostgresInventoryTransferRepository(connection, runtime.tenant).create(request(), command_id="queued-read-create", actor=actor)["source"]
        cached_actor, cached_principal = actor, current_server_principal()
    started: Queue[int] = Queue()

    def reader() -> str:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection, server_principal_context(cached_principal):
            connection.execute("SET LOCAL statement_timeout='8s'")
            started.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            try:
                PostgresInventoryTransferRepository(connection, runtime.tenant).get(source["id"], actor=cached_actor)
            except FinancePostingError as exc:
                assert "denied" in exc.code
                return exc.code
            pytest.fail("A permission withdrawn during the actual identity wait must refuse the original financial read.")

    with psycopg.connect(runtime.admin_dsn) as revoker, ThreadPoolExecutor(max_workers=1) as workers:
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.execute("SELECT id FROM reconforge.identity_users WHERE tenant_id=%s AND id='maker' FOR UPDATE", (runtime.tenant,))
        future = workers.submit(reader)
        try:
            pid = started.get(timeout=5)
            deadline = monotonic() + 5
            with psycopg.connect(runtime.admin_dsn) as probe:
                while revoker_pid not in probe.execute("SELECT pg_blocking_pids(%s)", (pid,)).fetchone()[0]:
                    assert monotonic() < deadline, "Actual reader must wait on the current human identity lock."
                    sleep(0.02)
            revoker.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
                revoked_at=now(),revoked_by='poster',revocation_reason_code='security_response'
                WHERE tenant_id=%s AND permission_name='finance_core.read'""", (runtime.tenant,))
        finally:
            revoker.commit()
        assert "denied" in future.result(timeout=8)
    with psycopg.connect(runtime.admin_dsn) as audit:
        assert audit.execute("SELECT phase,row_version,source_digest FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s AND id=%s",
            (runtime.tenant, source["id"])).fetchone() == (0, 1, source["source_digest"])


def test_actual_native_and_original_receipt_outbox_delivery_preserves_get_and_retained_replay(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        created = owner.create(request(), command_id="delivery-create", actor=actor)
        retained = canonical_json(created)
    with runtime.actor("poster") as (connection, _, _):
        outbox = PostgresOutboxRepository(connection)
        claimed = outbox.claim_pending(tenant_id=runtime.tenant, worker_id="it1-original-delivery", limit=100)
        assert len(claimed) >= 4 and any(event.aggregate_type == "inventory_movement" for event in claimed)
        for event in claimed:
            outbox.mark_published(tenant_id=runtime.tenant, event_id=event.id, worker_id="it1-original-delivery", lease_generation=event.lease_generation)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(created["source"]["id"], actor=actor) == created["source"]
        replay = owner.create(request(), command_id="delivery-create", actor=actor)
        assert canonical_json(replay) == retained
        assert owner.command_receipt(created["source"]["id"], "delivery-create", replay, actor=actor)["request_json"]["actor_id"] == actor.user_id


@pytest.mark.parametrize("permission", ["inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"])
def test_actual_whole_original_usd36_authority_cap20_refusal_cap36_original_reads_and_replay(transfer_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch, permission: str) -> None:
    import reconforge.infrastructure.postgres_operational_finance as core

    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        created = owner.create(request(), command_id="whole-value-create", actor=actor)
        original = canonical_json(native_business(connection, runtime.tenant))
    maximum = "36"
    observed: list[Decimal] = []

    def bounded(principal, **context):
        if context["required_permission"] == permission and context.get("amount") is not None:
            observed.append(context["amount"])
            return evaluate_principal_access(principal, maximum_amount=Decimal(maximum), **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(core, "evaluate_principal_access", bounded)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(created["source"]["id"], actor=actor) == created["source"]
        assert owner.list_transfers(request().scope, actor=actor)["transfers"] == [created["source"]]
        assert owner.evidence(created["source"]["id"], actor=actor)["source"] == created["source"]
        assert owner.create(request(), command_id="whole-value-create", actor=actor) == created
        assert owner.command_receipt(created["source"]["id"], "whole-value-create", created, actor=actor)["actor_id"] == actor.user_id
    assert observed and set(observed) == {Decimal("36.00")}
    maximum = "20"
    for operation in ("get", "list", "evidence", "replay", "receipt", "new-response"):
        with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
            owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
            if operation == "list":
                owner.list_transfers(request().scope, actor=actor)
            elif operation == "replay":
                owner.create(request(), command_id="whole-value-create", actor=actor)
            elif operation == "new-response":
                owner.create(request("CAP-REFUSED"), command_id="whole-value-refused", actor=actor)
            elif operation == "receipt":
                owner.command_receipt(created["source"]["id"], "whole-value-create", created, actor=actor)
            else:
                getattr(owner, operation)(created["source"]["id"], actor=actor)
        assert "denied" in refused.value.code
    with runtime.actor("maker") as (connection, _, _):
        assert canonical_json(native_business(connection, runtime.tenant)) == original
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
