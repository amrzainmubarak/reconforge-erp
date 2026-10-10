"""Native exact reservation release, retained source evidence and SQL closure."""
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload, validation_digest
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.procurement_partial import PartialQuantityPreparation, ProcurementPartialError
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot
from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
from reconforge.infrastructure.postgres_landed_cost_cancellation_schema import install_postgres_landed_cost_cancellation
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_landed_cost import phase, prepare, request, state
from tests.test_postgres_procurement_multiline import (
    CHECKER,
    MAKER,
    POSTER,
    action,
    create_multiline_runtime,
    create_order,
)
from tests.test_postgres_procurement_multiline import receipt_database as _base_receipt_database


@pytest.fixture(scope="module")
def receipt_database() -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    delegated = _base_receipt_database.__wrapped__()
    try:
        database = next(delegated)
        with psycopg.connect(database[0]) as admin:
            install_postgres_landed_cost_cancellation(admin)
            app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.landed_cost_cancellations TO {}").format(sql.Identifier(app_user)))
        yield database
    finally:
        delegated.close()


@pytest.fixture
def runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_multiline_runtime(receipt_database)


def cancel(runtime: ReceiptRuntime, plan: dict[str, Any], name: str = CHECKER, command: str = "cancel-landed") -> dict[str, Any]:
    with runtime.actor(name) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        kwargs = {"expected_plan_digest": plan["plan_digest"], "command_id": command, "reason": "Incorrect supplier freight source; replace before receipt", "actor": actor}
        result = owner.cancel(plan["id"], **kwargs)
        assert owner.cancel(plan["id"], **kwargs) == result
        return result


def all_state(runtime: ReceiptRuntime) -> str:
    with runtime.actor(MAKER) as (connection, _, _):
        records = connection.execute("SELECT to_jsonb(c) AS value FROM reconforge.landed_cost_cancellations c WHERE tenant_id=%s ORDER BY plan_id", (runtime.tenant,)).fetchall()
        return digest_payload({"base": state(connection, runtime.tenant), "cancellations": [row["value"] for row in records]})


@pytest.mark.parametrize("reviewed", [False, True])
def test_cancel_releases_exact_mixed_unit_capacity_and_preserves_acknowledgements(runtime: ReceiptRuntime, reviewed: bool) -> None:
    view = create_order(runtime)
    original = prepare(runtime, view)
    current = phase(runtime, original, "review", CHECKER) if reviewed else original
    retained = cancel(runtime, current, POSTER if reviewed else CHECKER)
    assert retained["status"] == "Cancelled" and retained["phase"] == int(reviewed)
    assert retained["allocations"] == current["allocations"]
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        assert owner.prepare(request(view), command_id="lc-prepare", actor=actor) == original
        assert owner.get(current["id"], actor=actor) == retained
        fresh = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
        assert [line["reserved_receipt_quantity"] for line in fresh["lines"]] == ["0", "0"]
        assert all(part["cancellation_plan_id"] == retained["id"] for part in fresh["receipts"])
        assert [line["received_quantity"] for line in fresh["lines"]] == ["0", "0"]
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0
        replacement = owner.prepare(request(fresh, "CORRECTED-LANDED"), command_id="replacement", actor=actor)
    posted = replacement
    for operation, name in (("review", CHECKER), ("post", POSTER)):
        with runtime.actor(name) as (connection, _, actor):
            posted = PostgresLandedCostRepository(connection, runtime.tenant).act(replacement["id"], operation,
                expected_plan_digest=replacement["plan_digest"], command_id="replacement-" + operation,
                reason="Independent corrected source review and receiving", actor=actor)
    assert posted["amount_minor"] == "1001"
    with runtime.actor(POSTER) as (connection, _, actor):
        final = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
        assert [(line["reserved_receipt_quantity"], line["received_quantity"]) for line in final["lines"]] == [("10", "10"), ("2.5", "2.5")]
        assert len(final["receipts"]) == 4 and final["totals"]["received_minor"] == "17000"
        # Independent integer oracle: rejected draft produces no inventory/GL.
        assert connection.execute("SELECT sum(original_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 18001
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 3
        assert PostgresLandedCostRepository(connection, runtime.tenant).get(retained["id"], actor=actor) == retained


@pytest.mark.parametrize("reviewed,name", [(False, MAKER), (True, MAKER), (True, CHECKER)])
def test_cancel_requires_independent_human(runtime: ReceiptRuntime, reviewed: bool, name: str) -> None:
    plan = prepare(runtime, create_order(runtime))
    if reviewed:
        plan = phase(runtime, plan, "review", CHECKER)
    before = all_state(runtime)
    with pytest.raises(ProcurementPartialError, match="independent" ):
        cancel(runtime, plan, name)
    assert all_state(runtime) == before


def test_posted_charge_cannot_cancel_or_release_inventory(runtime: ReceiptRuntime) -> None:
    plan = phase(runtime, phase(runtime, prepare(runtime, create_order(runtime)), "review", CHECKER), "post", POSTER)
    before = all_state(runtime)
    with pytest.raises(ProcurementPartialError, match="unreceived"):
        cancel(runtime, plan)
    assert all_state(runtime) == before


def test_cancelled_receipt_cannot_progress_via_owner_api_or_native_sql(runtime: ReceiptRuntime) -> None:
    import psycopg
    view = create_order(runtime)
    plan = prepare(runtime, view)
    cancel(runtime, plan)
    before = all_state(runtime)
    with pytest.raises(ProcurementPartialError, match="cancelled"):
        phase(runtime, plan, "review", CHECKER)
    with runtime.actor(MAKER) as (connection, _, actor):
        fresh = PostgresProcurementPartialRepository(connection, runtime.tenant).get(view["order"]["id"], actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation):
        action(runtime, fresh, "review-receipt", CHECKER, plan["allocations"][0]["receipt_id"])
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor(MAKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.landed_cost_plans SET phase=1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
    assert all_state(runtime) == before


@pytest.mark.parametrize("attack", ["delete", "change-reason", "change-ack", "change-source-phase"])
def test_cancelled_evidence_is_immutable_under_direct_sql(runtime: ReceiptRuntime, attack: str) -> None:
    import psycopg
    plan = prepare(runtime, create_order(runtime))
    cancel(runtime, plan)
    before = all_state(runtime)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor(CHECKER) as (connection, _, _):
        statements = {
            "delete": "DELETE FROM reconforge.landed_cost_cancellations WHERE tenant_id=%s AND plan_id=%s",
            "change-reason": "UPDATE reconforge.landed_cost_cancellations SET reason='rewritten' WHERE tenant_id=%s AND plan_id=%s",
            "change-ack": "UPDATE reconforge.landed_cost_cancellations SET response_json='{}' WHERE tenant_id=%s AND plan_id=%s",
            "change-source-phase": "UPDATE reconforge.landed_cost_cancellations SET source_phase=1 WHERE tenant_id=%s AND plan_id=%s",
        }
        connection.execute(statements[attack], (runtime.tenant, plan["id"]))
    assert all_state(runtime) == before


@pytest.mark.parametrize("attack", ["request", "ack", "missing-evidence", "maker", "revoked"])
def test_raw_cancellation_insert_cannot_forge_source_or_authority(runtime: ReceiptRuntime, attack: str) -> None:
    import psycopg
    plan = prepare(runtime, create_order(runtime))
    before = all_state(runtime)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor(CHECKER) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        audit, outbox = owner._event({**plan}, "landed_cost_cancelled", actor)
        request_json = {"operation": "cancel", "actor_id": actor.user_id, "request": {"plan_id": plan["id"], "expected_plan_digest": plan["plan_digest"], "reason": "Unreceived source rejected"}}
        projection = {"actor_id": actor.user_id, "reason": "Unreceived source rejected", "command_id": "raw-cancel", "audit_event_id": audit, "outbox_event_id": outbox}
        response = {**plan, "status": "Cancelled", "cancellation": projection}
        if attack == "request":
            request_json["request"]["expected_plan_digest"] = "0" * 64
        elif attack == "ack":
            response["amount_minor"] = "1"
        elif attack == "missing-evidence":
            audit = plan["audit_event_id"] if "audit_event_id" in plan else connection.execute("SELECT audit_event_id FROM reconforge.landed_cost_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"])).fetchone()[0]
        elif attack == "maker":
            projection["actor_id"] = MAKER
        else:
            connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,revoked_at=clock_timestamp(),revoked_by='synthetic',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='payables.approve'", (runtime.tenant,))
        from reconforge.domain.finance_posting import canonical_json
        connection.execute("""INSERT INTO reconforge.landed_cost_cancellations(tenant_id,plan_id,workspace_id,source_phase,
            actor_id,reason,command_id,request_digest,request_json,response_json,audit_event_id,outbox_event_id)
            VALUES(%s,%s,'work',0,%s,%s,'raw-cancel',%s,%s::jsonb,%s::jsonb,%s,%s)""", (runtime.tenant, plan["id"], projection["actor_id"],
            projection["reason"], digest_payload(request_json), canonical_json(request_json), canonical_json(response), audit, outbox))
    assert all_state(runtime) == before


def test_same_cancel_under_lost_ack_concurrency_has_one_retained_business_effect(runtime: ReceiptRuntime) -> None:
    plan = prepare(runtime, create_order(runtime))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cancel(runtime, plan), range(2)))
    assert results[0] == results[1]
    with runtime.actor(CHECKER) as (connection, _, _):
        assert connection.execute("SELECT count(*) FROM reconforge.landed_cost_cancellations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s AND action='landed_cost_cancelled'", (runtime.tenant,)).fetchone()[0] == 1


def test_post_cancel_race_commits_only_one_terminal_business_outcome(runtime: ReceiptRuntime) -> None:
    plan = phase(runtime, prepare(runtime, create_order(runtime)), "review", CHECKER)
    def attempt(operation: str) -> str:
        try:
            cancel(runtime, plan, POSTER) if operation == "cancel" else phase(runtime, plan, "post", POSTER)
            return operation
        except (FinancePostingError, ProcurementPartialError):
            return "denied"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ("cancel", "post")))
    assert outcomes.count("denied") == 1
    with runtime.actor(POSTER) as (connection, _, actor):
        final = PostgresLandedCostRepository(connection, runtime.tenant).get(plan["id"], actor=actor)
        assert final["status"] in ("Cancelled", "Posted")
        count = connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0]
        assert count == (0 if final["status"] == "Cancelled" else 3)


def test_cancel_failure_after_evidence_rolls_back_and_retry_rechecks_authority(runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    plan = prepare(runtime, create_order(runtime))
    before = all_state(runtime)
    original = PostgresLandedCostRepository._event
    def fail_after_event(self: PostgresLandedCostRepository, *args: Any, **kwargs: Any) -> tuple[str, str]:
        original(self, *args, **kwargs)
        raise RuntimeError("injected retained cancellation evidence failure")
    with monkeypatch.context() as patch:
        patch.setattr(PostgresLandedCostRepository, "_event", fail_after_event)
        with pytest.raises(RuntimeError, match="injected"):
            cancel(runtime, plan)
    assert all_state(runtime) == before
    cancelled = cancel(runtime, plan)
    from reconforge.infrastructure.postgres import PostgresTenantBoundary
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,revoked_at=clock_timestamp(),revoked_by='synthetic',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='payables.approve'", (runtime.tenant,))
    with pytest.raises((FinancePostingError, psycopg.Error)):
        cancel(runtime, plan)
    with runtime.actor(MAKER) as (connection, _, actor):
        assert PostgresLandedCostRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == cancelled


def test_zero_charge_allocation_cancellation_releases_every_line_for_plain_receipts(runtime: ReceiptRuntime) -> None:
    view = create_order(runtime)
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        plan = owner.prepare(replace(request(view), freight_minor=1, duty_minor=0), command_id="one-minor-charge", actor=actor)
        assert sorted(allocation["freight_minor"] for allocation in plan["allocations"]) == ["0", "1"]
    cancel(runtime, plan)
    with runtime.actor(MAKER) as (connection, _, actor):
        purchase = PostgresProcurementPartialRepository(connection, runtime.tenant)
        fresh = purchase.get(view["order"]["id"], actor=actor)
        assert [line["reserved_receipt_quantity"] for line in fresh["lines"]] == ["0", "0"]
        for line in fresh["lines"]:
            fresh = purchase.prepare_receipt_line(view["order"]["id"], line["id"], PartialQuantityPreparation(quantity=line["quantity_text"],
                posting_date="2026-10-03", period_id="period", reason="Replacement ordinary merchandise receipt"),
                expected_version=fresh["order"]["row_version"], command_id="plain-" + line["id"], actor=actor)
        assert [(line["reserved_receipt_quantity"], line["received_quantity"]) for line in fresh["lines"]] == [("10", "0"), ("2.5", "0")]
    for receipt in fresh["receipts"][2:]:
        fresh = action(runtime, fresh, "review-receipt", CHECKER, receipt["id"])
        fresh = action(runtime, fresh, "receive", POSTER, receipt["id"])
    with runtime.actor(POSTER) as (connection, _, _):
        assert connection.execute("SELECT sum(original_value_minor) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 17000
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 2


def test_ordinary_multiline_receipt_role_needs_no_landed_owner_privilege(runtime: ReceiptRuntime, receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql
    charged = prepare(runtime, create_order(runtime, "OWNED-CHARGED"))
    native = create_order(runtime, "ORDINARY-LEGACY")
    app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    tables = ("landed_cost_plans", "landed_cost_allocations", "landed_cost_reviews", "landed_cost_links", "landed_cost_commands", "landed_cost_cancellations")
    try:
        with psycopg.connect(runtime.admin_dsn) as admin:
            for table in tables:
                admin.execute(sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(app_user)))
        with runtime.actor(MAKER) as (connection, _, actor):
            assert not connection.execute("SELECT has_table_privilege(current_user,'reconforge.landed_cost_cancellations','SELECT')").fetchone()[0]
            purchase = PostgresProcurementPartialRepository(connection, runtime.tenant)
            read = purchase.get(native["order"]["id"], actor=actor)
            read = purchase.prepare_receipt_line(read["order"]["id"], read["lines"][0]["id"], PartialQuantityPreparation(quantity="10",
                posting_date="2026-10-03", period_id="period", reason="Ordinary native receipt with no LC grants"),
                expected_version=read["order"]["row_version"], command_id="ordinary-native", actor=actor)
        receipt_id = read["receipts"][0]["id"]
        read = action(runtime, read, "review-receipt", CHECKER, receipt_id)
        read = action(runtime, read, "receive", POSTER, receipt_id)
        assert read["receipts"][0]["stage"] == "Posted" and read["totals"]["received_minor"] == "12000"
        with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.actor(MAKER) as (connection, _, actor):
            PostgresProcurementPartialRepository(connection, runtime.tenant).get(charged["order_id"], actor=actor)
    finally:
        with psycopg.connect(runtime.admin_dsn) as admin:
            for table in tables:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(app_user)))


def assert_lost_native_charge_rollback(runtime: ReceiptRuntime, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    before = all_state(runtime)
    original = PostgresProcurementPartialRepository.prepare_receipt_line
    def lose_charge(self: PostgresProcurementPartialRepository, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_source_owner", None)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(PostgresProcurementPartialRepository, "prepare_receipt_line", lose_charge)
    with pytest.raises(psycopg.errors.CheckViolation, match="conserved bundle|capitalized"), runtime.actor(MAKER) as (connection, _, actor):
        PostgresLandedCostRepository(connection, runtime.tenant).prepare(request(source), command_id="faulty-native-cost", actor=actor)
    assert all_state(runtime) == before


def test_lost_native_charge_participant_cannot_prepare_uncapitalized_bundle(runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    """All original native rows/commands can be valid while the cost is wrong."""
    assert_lost_native_charge_rollback(runtime, create_order(runtime), monkeypatch)


def insert_memberless_owner(runtime: ReceiptRuntime, source: dict[str, Any], shape: str) -> None:
    """Raw SQL retains a correct native cash draft, digest, actor and exact ack."""
    from uuid import uuid4
    preparation = request(source)
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresLandedCostRepository(connection, runtime.tenant)
        owner.purchase._scope_transaction()
        parent = owner.purchase._order(preparation.order_id, lock=True)
        original = parent["request_json"]
        amount = preparation.freight_minor + preparation.duty_minor
        owner._authorize(parent, actor, "prepare", amount)
        identifier = "LC1-" + uuid4().hex
        mapping = connection.execute("""SELECT a.account_code FROM reconforge.inventory_valuation_policies p
            JOIN reconforge.finance_accounts a ON a.tenant_id=p.tenant_id AND a.id=p.receipt_clearing_account_id
            JOIN reconforge.procurement_partial_order_lines l ON l.tenant_id=p.tenant_id AND l.policy_id=p.id
            WHERE l.tenant_id=%s AND l.order_id=%s ORDER BY l.sequence LIMIT 1""", (runtime.tenant, parent["id"])).fetchone()
        paid = exact_minor_text(amount, 2)
        entry = owner.finance.finance.create_entry(entry_number=identifier, workspace=parent["workspace_id"],
            organization_code=original["organization_code"], entity_code=original["entity_code"], journal_code=original["journal_code"],
            posting_date=preparation.posting_date, period_id=preparation.period_id, description=preparation.reason,
            external_reference="LANDED-COST:" + identifier, actor_label=actor.username,
            lines=[{"account_code": mapping["account_code"], "debit": paid, "credit": "0", "description": preparation.reason},
                   {"account_code": original["cash_account_code"], "debit": "0", "credit": paid, "description": preparation.reason}])
        snapshot = posting_snapshot(connection, runtime.tenant, posting_entry(connection, runtime.tenant, entry["id"]))
        malformed = asdict(preparation)
        malformed.pop("lines")
        if shape != "missing":
            malformed["lines"] = None if shape == "null" else []
        payload = {"schema_version": "landed-cost-v1", "id": identifier, "request": malformed,
            "entry_id": entry["id"], "snapshot": snapshot, "validation_digest": validation_digest(snapshot),
            "preparer_actor_id": actor.user_id, **{key: parent[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}}
        if shape != "missing":
            payload["allocations"] = None if shape == "null" else []
        seal = digest_payload(payload)
        audit, outbox = owner._event({**payload, "plan_digest": seal}, "landed_cost_prepared", actor)
        connection.execute("""INSERT INTO reconforge.landed_cost_plans(tenant_id,id,order_id,workspace_id,organization_id,
            legal_entity_id,entry_id,amount_minor,phase,payload,plan_digest,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s,%s)""",
            (runtime.tenant, identifier, parent["id"], parent["workspace_id"], parent["organization_id"], parent["legal_entity_id"],
             entry["id"], amount, canonical_json(payload), seal, audit, outbox))
        command = {"operation": "prepare", "actor_id": actor.user_id, "request": malformed}
        connection.execute("""INSERT INTO reconforge.landed_cost_commands(tenant_id,workspace_id,plan_id,operation,command_id,
            actor_id,request_digest,request_json,response_json) VALUES(%s,%s,%s,'prepare',%s,%s,%s,%s::jsonb,reconforge.landed_cost_ack(%s,%s,0))""",
            (runtime.tenant, parent["workspace_id"], identifier, "memberless-" + identifier, actor.user_id,
             digest_payload(command), canonical_json(command), runtime.tenant, identifier))


@pytest.mark.parametrize("shape", ["missing", "null", "empty"])
def test_raw_sql_cannot_seal_charge_owner_without_receiving_members(runtime: ReceiptRuntime, shape: str) -> None:
    import psycopg
    source = create_order(runtime)
    before = all_state(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="Allocations must conserve"):
        insert_memberless_owner(runtime, source, shape)
    assert all_state(runtime) == before


def test_ordered_upgrade_refreshes_frozen_0123_owner_on_populated_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real 0125 downgrade/upgrade preserves source and rejects both old gaps."""
    import hashlib
    import os
    import subprocess
    import sys
    from pathlib import Path

    import psycopg
    from psycopg import sql

    isolated = _base_receipt_database.__wrapped__()
    try:
        database = next(isolated)
        runtime = create_multiline_runtime(database)
        retained = prepare(runtime, create_order(runtime, "RETAINED-0123"))
        source = create_order(runtime, "MIGRATED-FAULT-SOURCE")
        before = all_state(runtime)
        root = Path(__file__).resolve().parents[1]
        fixture = root / "tests/fixtures/landed_cost_owner_0123_69951414.sql"
        frozen = fixture.read_text(encoding="utf-8")
        assert hashlib.sha256(frozen.encode("utf-8")).hexdigest() == "ab5733882cc1c323fadf9bd29f7adf370c9cc262f9eeb650653153d31d05756f"
        assert "native_cost" not in frozen and "COALESCE(jsonb_array_length(allocations),0)" not in frozen
        environment = {**os.environ, "RECONFORGE_POSTGRES_DSN": runtime.admin_dsn}
        subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0124_pg_collection_cancellation"],
            cwd=root, env=environment, check=True, capture_output=True, text=True, timeout=180)
        with psycopg.connect(runtime.admin_dsn) as admin:
            assert admin.execute("SELECT to_regclass('reconforge.landed_cost_cancellations')").fetchone()[0] is None
            admin.execute(frozen)
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root, env=environment, check=True, capture_output=True, text=True, timeout=180)
        with psycopg.connect(runtime.admin_dsn) as admin:
            app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.landed_cost_cancellations TO {}").format(sql.Identifier(app_user)))
            original = admin.execute("SELECT pg_get_functiondef('reconforge.landed_cost_close_pre_cancel(text,text)'::regprocedure)").fetchone()[0]
            assert "native_cost" not in original and "COALESCE(jsonb_array_length(allocations),0)" not in original
        assert all_state(runtime) == before
        with runtime.actor(MAKER) as (connection, _, actor):
            assert PostgresLandedCostRepository(connection, runtime.tenant).get(retained["id"], actor=actor) == retained
        assert_lost_native_charge_rollback(runtime, source, monkeypatch)
        with pytest.raises(psycopg.errors.CheckViolation, match="Allocations must conserve"):
            insert_memberless_owner(runtime, source, "missing")
        assert all_state(runtime) == before
    finally:
        isolated.close()
