"""Real API source-to-GL proof, exact independent hashes and current authority."""
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository
from reconforge.infrastructure.postgres_identity_administration import PostgresIdentityAdministrationRepository
from tests.test_postgres_fixed_assets import (
    acquire,
    acquisition,
    asset_runtime,
    finance_database,
    finish,
    isolated_postgres_migration_dsn,
    operation,
    pytestmark,
    receipt_database,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_finance_api import client_for

__all__ = ["asset_runtime", "finance_database", "isolated_postgres_migration_dsn", "pytestmark", "receipt_database"]


def retained(runtime: ReceiptRuntime) -> list[int]:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
        return [connection.execute("SELECT count(*) AS count FROM reconforge.fixed_asset_commands").fetchone()["count"],
                connection.execute("SELECT count(*) AS count FROM reconforge.finance_posting_effects").fetchone()["count"],
                connection.execute("SELECT count(*) AS count FROM reconforge.fixed_asset_links").fetchone()["count"]]


def verify(proof: dict[str, Any], plan: dict[str, Any]) -> None:
    assert proof["schema_version"] == "fixed-asset-native-evidence-v1"
    assert proof["plan"]["id"] == plan["id"]
    for field, digest in (("canonical_asset_json", proof["asset_definition"]["asset_digest"]),
                          ("canonical_plan_json", plan["plan_digest"]), ("canonical_snapshot_json", plan["validation_digest"])):
        assert hashlib.sha256(proof[field].encode()).hexdigest() == digest
    snapshot = json.loads(proof["canonical_snapshot_json"])
    assert snapshot == plan["snapshot"]
    assert proof["totals"] == {side + "_minor": str(sum(line[side + "_minor"] for line in snapshot["lines"])) for side in ("debit", "credit")}
    assert proof["totals"]["debit_minor"] == proof["totals"]["credit_minor"]
    assert proof["plan"]["asset_digest"] == proof["asset_definition"]["asset_digest"]


def test_actual_api_prepared_reviewed_posted_large_asset_evidence_is_read_only(
    asset_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    runtime = asset_runtime
    plan = acquire(runtime, replace(acquisition(), cost_minor=9007199254740993))
    with client_for(runtime, receipt_database, tmp_path, "maker", step_up=False) as (client, headers):
        before = retained(runtime)
        response = client.get("/api/v1/fixed-assets/plans/" + plan["id"] + "/evidence", headers=headers)
        assert response.status_code == 200, response.text
        proof = response.json()["evidence"]
        verify(proof, plan)
        assert proof["native_effect"] is None and len(proof["phases"]) == 1
        assert proof["asset_definition"]["cost_minor"] == "9007199254740993"
        assert retained(runtime) == before
    with runtime.actor("checker") as (connection, _, actor):
        reviewed = PostgresFixedAssetsRepository(connection, runtime.tenant).review(plan["id"], actor=actor,
            expected_plan_digest=plan["plan_digest"], command_id="review-proof", reason="Independent proof review")
        assert len(PostgresFixedAssetsRepository(connection, runtime.tenant).plan_evidence(plan["id"], actor=actor)["phases"]) == 2
    with runtime.actor("poster") as (connection, _, actor):
        posted = PostgresFixedAssetsRepository(connection, runtime.tenant).post(reviewed["id"], actor=actor,
            expected_plan_digest=reviewed["plan_digest"], command_id="post-proof", reason="Independent proof posting")
    with client_for(runtime, receipt_database, tmp_path, "poster", step_up=False) as (client, headers):
        before = retained(runtime)
        response = client.get("/api/v1/fixed-assets/plans/" + plan["id"] + "/evidence", headers=headers)
        assert response.status_code == 200, response.text
        proof = response.json()["evidence"]
        verify(proof, posted)
        assert proof["native_effect"]["id"] == posted["posting_effect_id"]
        assert [phase["actor_id"] for phase in proof["phases"]] == ["maker", "checker", "poster", "poster"]
        assert len(set(phase["audit_event_id"] for phase in proof["phases"])) == 4
        assert len(set(phase["outbox_event_id"] for phase in proof["phases"])) == 4
        assert proof["native_effect"]["validation_digest"] == proof["plan"]["validation_digest"]
        assert retained(runtime) == before
        assert client.get("/api/v1/fixed-assets/plans/" + plan["id"] + "/evidence", headers={**headers, "X-ReconForge-Legal-Entity": "foreign"}).status_code in {403, 404}
        with runtime.actor("maker") as (connection, _, _):
            version = connection.execute("SELECT lifecycle_version FROM reconforge.identity_users WHERE tenant_id=%s AND id='poster'", (runtime.tenant,)).fetchone()["lifecycle_version"]
            PostgresIdentityAdministrationRepository(connection, runtime.tenant).set_user_disabled(
                actor_user_id="maker", user_id="poster", disabled=True, expected_lifecycle_version=version, as_of=datetime.now(UTC).replace(microsecond=0))
        denied = client.get("/api/v1/fixed-assets/plans/" + plan["id"] + "/evidence", headers=headers)
        assert denied.status_code in {401, 403}, denied.text
        assert "canonical_snapshot_json" not in denied.text


def test_depreciation_and_disposal_proofs_bind_the_original_native_equations(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    plan = finish(runtime, acquire(runtime))
    depreciation = finish(runtime, operation(runtime, plan["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    disposal = finish(runtime, operation(runtime, plan["asset_id"], kind="dispose", date="2026-11-02", period="nov", proceeds=7500))
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        for operation_plan, turnover in ((plan, 10101), (depreciation, 3033), (disposal, 10533)):
            proof = repository.plan_evidence(operation_plan["id"], actor=actor)
            verify(proof, operation_plan)
            assert proof["totals"]["debit_minor"] == str(turnover)
            assert proof["native_effect"]["entry_id"] == operation_plan["entry_id"]


def test_small_depreciation_does_not_disclose_large_original_asset_under_current_amount_policy(
    asset_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access

    runtime = asset_runtime
    initial = finish(runtime, acquire(runtime))
    depreciation = finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    disposal = finish(runtime, operation(runtime, initial["asset_id"], kind="dispose", date="2026-11-02", period="nov", proceeds=25000))
    observed: list[Decimal | None] = []
    ceiling = Decimal("40.00")

    def policy(principal: Any, **context: Any) -> Any:
        observed.append(context.get("amount"))
        # A page's coarse scope authorization has no individual source amount.
        if context.get("amount") is None:
            return evaluate_principal_access(principal, **context)
        return evaluate_principal_access(principal, maximum_amount=ceiling, **context)

    monkeypatch.setattr(authority, "evaluate_principal_access", policy)
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        assert repository.get_plan(depreciation["id"], actor=actor)["amount_minor"] == 3033
        for read in (
            lambda: repository.plan_evidence(depreciation["id"], actor=actor),
            lambda: repository.get(initial["asset_id"], actor=actor),
            lambda: repository.list_assets({"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}, actor=actor),
        ):
            with pytest.raises(FinancePostingError, match="authorization"):
                read()
        assert Decimal("101.01") in observed and Decimal("30.33") in observed
        ceiling = Decimal("200.00")
        assert repository.plan_evidence(depreciation["id"], actor=actor)["asset_definition"]["cost_minor"] == 10101
        # Allowed acquisition basis must not admit a larger historical disposal.
        for read in (
            lambda: repository.get(initial["asset_id"], actor=actor),
            lambda: repository.get_plan(disposal["id"], actor=actor),
            lambda: repository.plan_evidence(disposal["id"], actor=actor),
        ):
            with pytest.raises(FinancePostingError, match="authorization"):
                read()
        assert Decimal("280.33") in observed
        ceiling = Decimal("300.00")
        assert repository.get(initial["asset_id"], actor=actor)["plans"][-1]["id"] == disposal["id"]


def test_detail_refresh_and_native_evidence_serialize_without_lock_inversion(
    asset_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force the browser's detail/proof overlap; neither read may deadlock."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    import psycopg

    runtime = asset_runtime
    posted = finish(runtime, acquire(runtime))
    before = retained(runtime)
    asset_locked, proof_ready, release_detail = Event(), Event(), Event()
    pids: dict[str, int] = {}
    original_asset = PostgresFixedAssetsRepository._asset

    def pause_detail(repository: PostgresFixedAssetsRepository, identifier: str) -> dict[str, Any]:
        asset = original_asset(repository, identifier)
        if repository.connection.info.backend_pid == pids.get("detail") and not asset_locked.is_set():
            asset_locked.set()
            assert release_detail.wait(15), "Bounded detail lock release was not delivered."
        return asset

    monkeypatch.setattr(PostgresFixedAssetsRepository, "_asset", pause_detail)

    def read_detail() -> dict[str, Any]:
        with runtime.actor("poster") as (connection, _, actor):
            pids["detail"] = connection.info.backend_pid
            connection.execute("SET LOCAL statement_timeout='10s'")
            assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {"rolsuper": False, "rolbypassrls": False}
            return PostgresFixedAssetsRepository(connection, runtime.tenant).get(posted["asset_id"], actor=actor)

    def read_proof() -> dict[str, Any]:
        with runtime.actor("poster") as (connection, _, actor):
            pids["proof"] = connection.info.backend_pid
            connection.execute("SET LOCAL statement_timeout='10s'")
            proof_ready.set()
            return PostgresFixedAssetsRepository(connection, runtime.tenant).plan_evidence(posted["id"], actor=actor)

    with ThreadPoolExecutor(max_workers=2) as executor:
        detail = executor.submit(read_detail)
        try:
            assert asset_locked.wait(15), "Detail did not acquire the source asset lock."
            proof = executor.submit(read_proof)
            assert proof_ready.wait(15), "Proof reader did not start."
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as observer:
                deadline = monotonic() + 15
                while monotonic() < deadline:
                    blockers = observer.execute("SELECT pg_blocking_pids(%s)", (pids["proof"],)).fetchone()[0]
                    if pids["detail"] in blockers:
                        break
                    sleep(.01)
                else:
                    pytest.fail("Proof did not wait on the held source lock; overlap was not exercised.")
        finally:
            release_detail.set()
        actual_detail, actual_proof = detail.result(timeout=20), proof.result(timeout=20)
    assert actual_detail["plans"][-1]["id"] == posted["id"]
    assert actual_detail["status"] == "Active" and actual_detail["carrying_minor"] == 10101
    verify(actual_proof, posted)
    assert actual_proof["native_effect"]["id"] == posted["posting_effect_id"]
    assert retained(runtime) == before
