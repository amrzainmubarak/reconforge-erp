"""Native exact reservation release, retained source evidence and SQL closure."""
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.procurement_partial import PartialQuantityPreparation, ProcurementPartialError
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
    posted = phase(runtime, phase(runtime, replacement, "review", CHECKER), "post", POSTER)
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
