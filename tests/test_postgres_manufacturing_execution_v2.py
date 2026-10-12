"""Actual nonowner ME2 stock/WIP, original expense claims and quality disposition."""
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from fractions import Fraction
from threading import Event
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import InventoryReceiptPostingError, ReceiptPreparation
from reconforge.domain.manufacturing_execution import OrderPreparation
from reconforge.domain.manufacturing_execution_v2 import (
    PERMISSIONS,
    ManufacturingOrderPreparation,
    RoutingPreparation,
    WorkcenterPreparation,
)
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.infrastructure.postgres_manufacturing_execution_v2_schema import (
    install_postgres_manufacturing_execution_v2_schema,
)
from tests.test_postgres_manufacturing_execution import (
    _actually_blocked,
    approved_bom,
    baseline_receipt_database,
    financial_oracle,
    runtime,
)
from tests.test_postgres_manufacturing_execution import manufacturing_database as original_manufacturing_database

_ = (original_manufacturing_database, baseline_receipt_database)
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "organization_code": "ORG", "entity_code": "ENTITY"}


@pytest.fixture(scope="module")
def manufacturing_v2_database(original_manufacturing_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    admin_dsn, app_dsn = original_manufacturing_database
    with psycopg.connect(admin_dsn) as connection:
        install_postgres_manufacturing_execution_v2_schema(connection)
        role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
    yield admin_dsn, app_dsn


def system(database: tuple[str, str]) -> Any:
    result = runtime(database)
    with PostgresTenantBoundary(result.factory).transaction(result.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identity.create_permission(tenant_id=result.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=result.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, result.tenant)
        for code, kind in (("LABOR", "Expense"), ("OVERHEAD", "Expense"), ("ACCRUAL", "Liability")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
    return result


def original_expense(result: Any, account: str, number: str, amount: str, *, source_type: str = "Manual") -> tuple[str, str]:
    with result.actor("maker") as (_, receipts, actor):
        draft = receipts.finance.finance.create_entry(entry_number=number, organization_code="ORG", entity_code="ENTITY",
            period_id="period", journal_code="STOCK", posting_date="2026-10-03", workspace="work", description="Original actual expense",
            actor_label=actor.username, source_type=source_type, lines=[{"account_code": account, "debit": amount}, {"account_code": "ACCRUAL", "credit": amount}])
    with result.actor("checker") as (_, receipts, actor):
        receipts.finance.finance.validate_entry(draft["id"], reason="Independent original expense", actor_label=actor.username)
        reviewed = receipts.finance.preview(draft["id"], actor=actor)
    with result.actor("poster") as (_, receipts, actor):
        effect = receipts.finance.post(draft["id"], command_id=number + "-post", expected_validation_digest=reviewed["validation_digest"], reason="Actual expense source", actor=actor)
        original = receipts.connection.execute("SELECT id FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s AND debit_minor>0",
            (result.tenant, draft["id"])).fetchone()
        return effect["id"], original["id"]


def owner_phase(result: Any, source: dict[str, Any], operation: str, kind: str = "order", *, name: str | None = None) -> dict[str, Any]:
    person = name or {"prepare": "maker", "approve": "checker", "review": "checker", "post": "poster", "cancel": "checker"}[operation]
    with result.actor(person) as (connection, _, actor):
        owner = PostgresManufacturingExecutionV2Repository(connection, result.tenant)
        method = {"order": owner.act_order, "production": owner.act_production, "inspection": owner.act_inspection, "definition": owner.approve_definition}[kind]
        parameters = {"expected_digest": source["source_digest"], "command_id": source["id"] + "-" + operation,
                      "reason": "Independent actual " + operation, "actor": actor}
        return method(source["id"], **parameters) if kind == "definition" else method(source["id"], operation, **parameters)


def order(result: Any) -> dict[str, Any]:
    bom = approved_bom(result)
    with result.actor("maker") as (connection, _, actor):
        center = PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_workcenter(
            WorkcenterPreparation("ASSEMBLY", 1, "Actual assembly and inspection", "2026-10-01", "2026-10-31", SCOPE, "Synthetic approved workcenter"), command_id="wc-create", actor=actor)
    center = owner_phase(result, center, "approve", "definition")
    with result.actor("maker") as (connection, _, actor):
        route = PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_routing(
            RoutingPreparation("PRODUCT-ROUTE", 1, bom["id"], "2026-10-01", "2026-10-31",
                [{"sequence": 1, "workcenter_id": center["id"], "name": "Assembly and functional check", "minutes_per_batch": 60}], SCOPE,
                "Actual effective original engineering sequence"), command_id="routing-create", actor=actor)
    route = owner_phase(result, route, "approve", "definition")
    labor, labor_line = original_expense(result, "LABOR", "LABOR-SOURCE", "20.00")
    overhead, overhead_line = original_expense(result, "OVERHEAD", "OH-SOURCE", "10.00")
    material = OrderPreparation(number="ME2-WORK", bom_version_id=bom["id"], output_quantity="10", component_location_code="MAIN/STOCK",
        finished_location_code="MAIN/STOCK", component_policy_code="FIFO", finished_policy_code="MFG", journal_code="STOCK", wip_account_code="WIP",
        scrap_account_code="SCRAP", period_id="period", posting_date="2026-10-04", **SCOPE, reason="Expense-backed inspected actual production")
    claims = [{"effect_id": labor, "line_id": labor_line, "kind": "Labor", "operation_sequence": 1, "minutes": 60, "rate_minor_per_hour": 600},
              {"effect_id": overhead, "line_id": overhead_line, "kind": "Overhead", "operation_sequence": 1, "minutes": 30, "rate_minor_per_hour": 600}]
    with result.actor("maker") as (connection, _, actor):
        return PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_order(
            ManufacturingOrderPreparation(material, route["id"], claims), command_id="me2-create", actor=actor)


def half_even(value: Fraction) -> int:
    whole, residual = divmod(value.numerator, value.denominator)
    return whole + int(residual * 2 > value.denominator or residual * 2 == value.denominator and whole % 2)


def export_native_proof(result: Any, stage: str) -> None:
    """Optional file-only export over the same real synthetic native cycle."""
    import json
    import os
    from pathlib import Path

    from tests.manufacturing_execution_v2_browser import manufacturing_execution_v2_proof

    destination = os.environ.get("RECONFORGE_ME2_NATIVE_PROOF_DIR")
    if destination:
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (stage + ".json")
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manufacturing_execution_v2_proof(result, actor_name="poster"), handle, sort_keys=True, indent=2)
            handle.write("\n")


def test_original_expense_backed_material_wip_quality_hold_then_actual_saleable_fg_and_abnormal_loss(manufacturing_v2_database: tuple[str, str]) -> None:
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    result = system(manufacturing_v2_database)
    source = order(result)
    with PostgresTenantBoundary(result.factory).transaction(result.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        identity.create_role(tenant_id=result.tenant, role_name="me2-post-only")
        for permission in PERMISSIONS["post"]:
            identity.grant_permission(tenant_id=result.tenant, role_name="me2-post-only", permission_name=permission)
        identity.create_user(tenant_id=result.tenant, user_id="restricted-poster", username="restricted-poster",
            password=result.password, role_name="me2-post-only")
        authority = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            authority.grant(tenant_id=result.tenant, grant_id="restricted-" + identifier, principal_type="user",
                principal_id="restricted-poster", scope_type=kind, scope_id=identifier, actor_id="poster")
    with result.actor("restricted-poster") as (_, _, actor):
        assert "manufacturing_execution_v2.approve" not in actor.permissions
    posted = owner_phase(result, owner_phase(result, owner_phase(result, source, "prepare"), "review"), "post", name="restricted-poster")
    total = half_even(Fraction(12000 * 2, 10)) + half_even(Fraction(3333 * 3000, 20000)) + 600 + 300
    assert posted["total_cost_minor"] == total == 3800
    assert financial_oracle(result)["WIP"] == 3800
    for index, (produced, accepted, rejected) in enumerate((("4", "3", "1"), ("6", "6", "0")), 1):
        with result.actor("maker") as (connection, _, actor):
            held = PostgresManufacturingExecutionV2Repository(connection, result.tenant).produce(source["id"], output_quantity=produced,
                operations=[{"sequence": 1, "minutes": 24 if index == 1 else 36, "evidence_reference": "SYN-RUN-" + str(index)}],
                period_id="period", posting_date=f"2026-10-0{4 + index}", command_id=f"produce-{index}", reason="Actual partial production awaiting inspection", actor=actor)
        held = owner_phase(result, owner_phase(result, held, "review", "production"), "post", "production", name="restricted-poster")
        export_native_proof(result, "held-" + str(index))
        with result.actor("poster") as (connection, _, actor):
            view = PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(source["id"], actor=actor)
            assert view["held_quantity_scaled"] == int(produced)
            # A posted quality hold creates zero native FG stock, even with real material/expense WIP.
            quantity = connection.execute("SELECT COALESCE(sum(original_quantity_scaled),0) qty FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s",
                (result.tenant, view["material"]["output_item_id"])).fetchone()["qty"]
            assert int(quantity) == (0 if index == 1 else 3)
        with result.actor("maker") as (connection, _, actor):
            inspection = PostgresManufacturingExecutionV2Repository(connection, result.tenant).inspect(held["id"], accepted_quantity=accepted,
                rejected_quantity=rejected, inspection_reference=f"SYN-QC-{index}", period_id="period", posting_date=f"2026-10-0{4 + index}",
                command_id=f"inspect-{index}", reason="Complete independent held tranche acceptance and rejection", actor=actor)
        inspection = owner_phase(result, inspection, "review", "inspection")
        if index == 1:
            cancelled = owner_phase(result, inspection, "cancel", "inspection")
            assert cancelled["phase"] == 3 and cancelled["receipt_effect"] is None and cancelled["loss_effect_id"] is None
            assert financial_oracle(result)["WIP"] == 3800
            import psycopg

            before_cancelled_attacks = business_snapshot(result)
            with result.actor("poster") as (connection, _, _):
                artifacts = cancelled["receipt_plan"]["artifacts"]
                for table, identifier in (("finance_entries", artifacts["finance_entry_id"]),
                        ("finance_posting_effects", artifacts["posting_effect_id"]), ("inventory_cost_layers", artifacts["cost_layer_id"]),
                        ("inventory_movements", artifacts["movement_id"])):
                    from psycopg import sql
                    assert connection.execute(sql.SQL("SELECT count(*) n FROM reconforge.{} WHERE tenant_id=%s AND id=%s").format(sql.Identifier(table)),
                        (result.tenant, identifier)).fetchone()["n"] == 0
            with pytest.raises(InventoryReceiptPostingError), result.actor("poster") as (_, receipts, actor):
                receipts.commit(cancelled["receipt_plan"]["plan_id"], command_id="detached-cancelled-commit",
                    expected_review_digest="0" * 64, reason="Cancelled inspection cannot post through public native IRP", actor=actor)
            with pytest.raises(psycopg.errors.CheckViolation), result.actor("poster") as (connection, _, actor):
                connection.execute("SELECT set_config('app.manufacturing_execution_v2_actor_id',%s,true)", (actor.user_id,))
                connection.execute("UPDATE reconforge.manufacturing_execution_v2_inspections SET phase=2 WHERE tenant_id=%s AND id=%s",
                    (result.tenant, cancelled["id"]))
            assert business_snapshot(result) == before_cancelled_attacks
            with result.actor("maker") as (connection, _, actor):
                inspection = PostgresManufacturingExecutionV2Repository(connection, result.tenant).inspect(held["id"], accepted_quantity=accepted,
                    rejected_quantity=rejected, inspection_reference="SYN-QC-REPLACEMENT", period_id="period", posting_date="2026-10-05",
                    command_id="inspect-replacement", reason="Original complete quality hold after reviewed cancellation", actor=actor)
            inspection = owner_phase(result, inspection, "review", "inspection")
        inspection = owner_phase(result, inspection, "post", "inspection", name="restricted-poster")
        assert inspection["phase"] == 2
    with result.actor("poster") as (connection, _, actor):
        final = PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(source["id"], actor=actor)
        assert (final["phase"], final["wip_minor"], final["held_quantity_scaled"]) == (4, 0, 0)
        assert final["material"]["execution_version"] == 2 and final["material"]["wip_minor"] == 0
    balances = financial_oracle(result)
    assert (balances["FG"], balances["SCRAP"], balances["WIP"], balances["LABOR"], balances["OVERHEAD"]) == (3420, 380, 0, 1400, 700)
    export_native_proof(result, "final")


def business_snapshot(result: Any) -> str:
    from psycopg import sql
    tables = ("manufacturing_execution_orders", "manufacturing_execution_requirements", "manufacturing_execution_reservations",
        "manufacturing_execution_v2_orders", "manufacturing_execution_v2_cost_claims", "manufacturing_execution_v2_cost_releases",
        "manufacturing_execution_v2_productions", "manufacturing_execution_v2_inspections", "manufacturing_execution_v2_commands",
        "manufacturing_execution_v2_events", "financial_effect_ownership_guards", "financial_effect_ownership_releases",
        "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects", "finance_posting_commands",
        "inventory_movements", "inventory_movement_lines", "inventory_cost_layers", "inventory_layer_consumptions",
        "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links", "inventory_receipt_commands")
    with result.actor("poster") as (connection, _, _):
        value = {table: [row["value"] for row in connection.execute(sql.SQL("SELECT to_jsonb(x) value FROM reconforge.{} x WHERE tenant_id=%s ORDER BY to_jsonb(x)::text").format(sql.Identifier(table)), (result.tenant,)).fetchall()] for table in tables}
    return digest_payload(value)


def clone_request(source: dict[str, Any], number: str, *, labor: int | None = None) -> ManufacturingOrderPreparation:
    raw = source["command_request"]
    material = OrderPreparation(**{key: value for key, value in raw["material"].items() if key != "schema_version"})
    from dataclasses import replace
    material = replace(material, number=number)
    claims = [{**value} for value in raw["claims"]]
    if labor is not None:
        claims = [{**value, "minutes": 60, "rate_minor_per_hour": labor} if value["kind"] == "Labor" else value for value in claims]
    return ManufacturingOrderPreparation(material, raw["routing_id"], claims)


def test_reviewed_unposted_cancellation_releases_claims_and_exact_original_expense_can_reverse(manufacturing_v2_database: tuple[str, str]) -> None:
    result = system(manufacturing_v2_database)
    source = order(result)
    with result.actor("poster") as (connection, _, _):
        before = [row["value"] for row in connection.execute("SELECT to_jsonb(x) value FROM reconforge.finance_posting_effects x WHERE tenant_id=%s ORDER BY id", (result.tenant,)).fetchall()]
    reviewed = owner_phase(result, owner_phase(result, source, "prepare"), "review")
    cancelled = owner_phase(result, reviewed, "cancel")
    assert cancelled["phase"] == 5
    with result.actor("checker") as (connection, receipts, actor):
        claims = connection.execute("SELECT state,id FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=%s", (result.tenant,)).fetchall()
        assert len(claims) == 2 and {claim["state"] for claim in claims} == {"Released"}
        assert connection.execute("SELECT count(*) n FROM reconforge.financial_effect_ownership_releases WHERE tenant_id=%s", (result.tenant,)).fetchone()["n"] == 2
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=%s AND state='Active'", (result.tenant,)).fetchone()["n"] == 0
        retained = [row["value"] for row in connection.execute("SELECT to_jsonb(x) value FROM reconforge.finance_posting_effects x WHERE tenant_id=%s ORDER BY id", (result.tenant,)).fetchall()]
        assert retained == before
        labor = next(claim for claim in source["claims"] if claim["kind"] == "Labor")
        inverse = receipts.finance.prepare_reversal(labor["effect_id"], command_id="cancel-released-inverse", entry_number="EXPENSE-RELEASED-INVERSE",
            period_id="period", posting_date="2026-10-08", reason="Released original expense remains independently reversible", actor=actor)
        assert inverse["entry_id"]
        assert PostgresManufacturingExecutionV2Repository(connection, result.tenant).act_order(source["id"], "cancel", expected_digest=source["source_digest"],
            command_id=source["id"] + "-cancel", reason="Independent actual cancel", actor=actor) == cancelled


def test_active_original_claim_refuses_native_reversal_and_direct_sql_source_mutation(manufacturing_v2_database: tuple[str, str]) -> None:
    import psycopg
    result = system(manufacturing_v2_database)
    source = order(result)
    before = business_snapshot(result)
    labor = next(claim for claim in source["claims"] if claim["kind"] == "Labor")
    with pytest.raises(FinancePostingError), result.actor("checker") as (_, receipts, actor):
        receipts.finance.prepare_reversal(labor["effect_id"], command_id="claimed-original-inverse", entry_number="CLAIMED-ORIGINAL-INVERSE",
            period_id="period", posting_date="2026-10-08", reason="Cannot detach original active production expense", actor=actor)
    assert business_snapshot(result) == before
    for statement, parameters in [
        ("UPDATE reconforge.manufacturing_execution_v2_cost_claims SET amount_minor=amount_minor+1 WHERE tenant_id=%s", (result.tenant,)),
        ("DELETE FROM reconforge.financial_effect_ownership_guards WHERE tenant_id=%s", (result.tenant,)),
        ("UPDATE reconforge.manufacturing_execution_v2_orders SET phase=3,total_cost_minor=3800 WHERE tenant_id=%s", (result.tenant,)),
    ]:
        with pytest.raises(psycopg.Error), result.actor("poster") as (connection, _, actor):
            connection.execute("SELECT set_config('app.manufacturing_execution_v2_actor_id',%s,true)", (actor.user_id,))
            connection.execute(statement, parameters)
        assert business_snapshot(result) == before
    prepared = owner_phase(result, source, "prepare")
    before = business_snapshot(result)
    with pytest.raises(psycopg.Error), result.actor("maker") as (connection, _, _):
        connection.execute("DELETE FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s", (result.tenant, prepared["cost_entry"]["entry_id"]))
    assert business_snapshot(result) == before


def test_two_current_orders_cannot_overclaim_one_original_expense_under_concurrency(manufacturing_v2_database: tuple[str, str]) -> None:
    result = system(manufacturing_v2_database)
    source = order(result)  #600 of original2000 already claimed.

    def attempt(index: int) -> bool:
        try:
            with result.actor("maker") as (connection, _, actor):
                PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_order(clone_request(source, f"CONCURRENT-{index}", labor=800),
                    command_id=f"concurrent-{index}", actor=actor)
            return True
        except FinancePostingError:
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(attempt, (1, 2)))
    assert outcomes.count(True) == outcomes.count(False) == 1
    with result.actor("poster") as (connection, _, _):
        labor = next(claim for claim in source["claims"] if claim["kind"] == "Labor")
        actual = connection.execute("SELECT sum(amount_minor) total FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=%s AND effect_id=%s AND state<>'Released'", (result.tenant, labor["effect_id"])).fetchone()["total"]
        assert int(actual) == 1400
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_v2_orders WHERE tenant_id=%s", (result.tenant,)).fetchone()["n"] == 2
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s", (result.tenant,)).fetchone()["n"] == 2


def test_late_abnormal_loss_failure_rolls_back_completed_fg_participant_then_exact_retry(manufacturing_v2_database: tuple[str, str], monkeypatch: Any) -> None:
    result = system(manufacturing_v2_database)
    source = order(result)
    owner_phase(result, owner_phase(result, owner_phase(result, source, "prepare"), "review"), "post")
    with result.actor("maker") as (connection, _, actor):
        production = PostgresManufacturingExecutionV2Repository(connection, result.tenant).produce(source["id"], output_quantity="4",
            operations=[{"sequence": 1, "minutes": 24, "evidence_reference": "SYN-LATE-FAILURE"}], period_id="period", posting_date="2026-10-05",
            command_id="late-produce", reason="Actual held production", actor=actor)
    production = owner_phase(result, owner_phase(result, production, "review", "production"), "post", "production")
    with result.actor("maker") as (connection, _, actor):
        inspection = PostgresManufacturingExecutionV2Repository(connection, result.tenant).inspect(production["id"], accepted_quantity="3", rejected_quantity="1",
            inspection_reference="SYN-LATE-QC", period_id="period", posting_date="2026-10-05", command_id="late-inspect", reason="Actual complete quality decision", actor=actor)
    inspection = owner_phase(result, inspection, "review", "inspection")
    before = business_snapshot(result)

    def fail_loss(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Synthetic failure after actual native FG before abnormal-loss publication")

    with pytest.raises(RuntimeError, match="Synthetic failure"), result.actor("poster") as (connection, _, actor):
        owner = PostgresManufacturingExecutionV2Repository(connection, result.tenant)
        monkeypatch.setattr(owner, "_post", fail_loss)
        owner.act_inspection(inspection["id"], "post", expected_digest=inspection["source_digest"], command_id=inspection["id"] + "-post", reason="Independent actual post", actor=actor)
    assert business_snapshot(result) == before
    posted = owner_phase(result, inspection, "post", "inspection")
    with result.actor("poster") as (connection, _, actor):
        replay = PostgresManufacturingExecutionV2Repository(connection, result.tenant).act_inspection(inspection["id"], "post", expected_digest=inspection["source_digest"],
            command_id=inspection["id"] + "-post", reason="Independent actual post", actor=actor)
        assert canonical_json(replay) == canonical_json(posted)
    assert financial_oracle(result)["WIP"] == 2280


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("claim_first", [False, True])
def test_actual_claim_and_original_expense_posted_inverse_serialize_without_stale_snapshot_admission(
    manufacturing_v2_database: tuple[str, str], isolation: str, claim_first: bool,
) -> None:
    import psycopg

    from reconforge.infrastructure.postgres import set_local_tenant_scope
    from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository
    from reconforge.platform.common import current_server_principal, server_principal_context

    result = system(manufacturing_v2_database)
    source = order(result)
    owner_phase(result, source, "cancel")
    labor = next(value for value in source["claims"] if value["kind"] == "Labor")
    with result.actor("checker") as (_, receipts, actor):
        inverse = receipts.finance.prepare_reversal(labor["effect_id"], command_id="source-inverse-prepare",
            entry_number="ORIGINAL-COST-INVERSE", period_id="period", posting_date="2026-10-08",
            reason="Actual source inverse racing a newly reserved production claim", actor=actor)
    with result.actor("maker") as (_, receipts, actor):
        receipts.finance.finance.validate_entry(inverse["entry_id"], reason="Independent native inverse review", actor_label=actor.username)
        reviewed = receipts.finance.preview(inverse["entry_id"], actor=actor)
    ready, continue_command = Event(), Event()
    pids: dict[str, int] = {}

    def command(connection: Any, receipts: Any, actor: Any, claiming: bool) -> Any:
        if claiming:
            return PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_order(
                clone_request(source, "RACED-SOURCE-CLAIM"), command_id="raced-source-claim", actor=actor)
        return receipts.finance.post(inverse["entry_id"], command_id="raced-source-inverse-post",
            expected_validation_digest=reviewed["validation_digest"], reason="Actual independently posted original inverse", actor=actor)

    def follower() -> Any:
        with result.actor("poster" if claim_first else "maker") as (_, _, actor):
            principal = current_server_principal()
        assert principal is not None
        with closing(result.factory.connect()) as connection, connection.transaction(), server_principal_context(principal):
            # Begin a fresh transaction after the real password authentication;
            # never rollback inside ReceiptRuntime's explicit transaction context.
            statement = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" if isolation == "REPEATABLE READ" else "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
            connection.execute(statement)
            set_local_tenant_scope(connection, result.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity")
            connection.execute("SELECT version FROM reconforge.financial_effect_claim_gates WHERE tenant_id=%s AND source_effect_id=%s",
                (result.tenant, labor["effect_id"])).fetchone()
            pids["follower"] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            ready.set()
            assert continue_command.wait(20)
            if isolation == "REPEATABLE READ":
                # Public financial mutations already require READ COMMITTED.
                # Exercise the additional native directory fence itself under an
                # actual stale RR snapshot; its version UPDATE must serialize.
                guard = "SELECT reconforge.refuse_claimed_financial_effect(%s,%s)" if claim_first else "SELECT reconforge.touch_financial_effect_claim_gate(%s,%s)"
                return connection.execute(guard, (result.tenant, labor["effect_id"])).fetchone()
            receipts = PostgresInventoryReceiptPostingRepository(connection, result.tenant)
            return command(connection, receipts, actor, not claim_first)

    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(follower)
        if not ready.wait(20):
            future.result(timeout=1)  # Retain the actual early failure rather than mask it with a readiness assertion.
            raise AssertionError("The actual authenticated follower failed to establish its source snapshot")
        try:
            with result.actor("maker" if claim_first else "poster") as (connection, receipts, actor):
                holder_pid = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
                winner = command(connection, receipts, actor, claim_first)
                assert winner["id"]
                continue_command.set()
                _actually_blocked(result.admin_dsn, pids, "follower", holder_pid)
        finally:
            continue_command.set()
        with pytest.raises((FinancePostingError, psycopg.errors.CheckViolation, psycopg.errors.SerializationFailure)) as refused:
            future.result(timeout=90)
    if isolation == "REPEATABLE READ":
        assert isinstance(refused.value, psycopg.errors.SerializationFailure)
    with result.actor("checker") as (connection, _, actor):
        active = connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=%s AND effect_id=%s AND state<>'Released'",
            (result.tenant, labor["effect_id"])).fetchone()["n"]
        reversed_count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND reverses_effect_id=%s",
            (result.tenant, labor["effect_id"])).fetchone()["n"]
        assert (active, reversed_count) == ((1, 0) if claim_first else (0, 1))
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_v2_orders WHERE tenant_id=%s", (result.tenant,)).fetchone()["n"] == (2 if claim_first else 1)
        # Both retained cancelled history and the winning current source still close.
        PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(source["id"], actor=actor)
        if claim_first:
            PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(winner["id"], actor=actor)


def test_old_prepare_ack_rechecks_persisted_scope_after_actual_command_wait(manufacturing_v2_database: tuple[str, str]) -> None:
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
    result = system(manufacturing_v2_database)
    source = order(result)
    prepared = owner_phase(result, source, "prepare")
    before = business_snapshot(result)
    pids: dict[str, int] = {}

    def replay() -> Any:
        with result.actor("maker") as (connection, _, actor):
            pids["retry"] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            return PostgresManufacturingExecutionV2Repository(connection, result.tenant).act_order(source["id"], "prepare",
                expected_digest=source["source_digest"], command_id=source["id"] + "-prepare", reason="Independent actual prepare", actor=actor)

    assert replay() == prepared
    with ThreadPoolExecutor(max_workers=1) as workers:
        with PostgresTenantBoundary(result.factory).transaction(result.tenant) as holder:
            holder_pid = holder.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            holder.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (canonical_json([result.tenant, "work", "manufacturing-execution-v2", source["id"] + "-prepare"]),))
            future = workers.submit(replay)
            _actually_blocked(result.admin_dsn, pids, "retry", holder_pid)
            with PostgresTenantBoundary(result.factory).transaction(result.tenant) as connection:
                PostgresScopeAuthorityRepository(connection).revoke(tenant_id=result.tenant, grant_id="me1-maker-entity",
                    actor_id="poster", reason="Current manufacturing grant withdrawn while lost-response command blocks")
        with pytest.raises(FinancePostingError, match="persisted.*scope"):
            future.result(timeout=60)
    assert business_snapshot(result) == before


def test_reserved_order_and_held_names_cannot_become_standalone_fg_receipts_or_extra_wip_journals(manufacturing_v2_database: tuple[str, str]) -> None:
    import psycopg
    result = system(manufacturing_v2_database)
    source = order(result)
    owner_phase(result, owner_phase(result, owner_phase(result, source, "prepare"), "review"), "post")
    with result.actor("maker") as (connection, _, actor):
        production = PostgresManufacturingExecutionV2Repository(connection, result.tenant).produce(source["id"], output_quantity="4",
            operations=[{"sequence": 1, "minutes": 24, "evidence_reference": "SYN-NO-DETACHED-FG"}], period_id="period", posting_date="2026-10-05",
            command_id="reserved-produce", reason="Actual production requires inspection", actor=actor)
    production = owner_phase(result, owner_phase(result, production, "review", "production"), "post", "production")
    before = business_snapshot(result)
    for reserved in (source["id"], production["id"], source["routing_id"]):
        with pytest.raises((InventoryReceiptPostingError, psycopg.Error)), result.actor("maker") as (_, receipts, actor):
            receipts.prepare_receipt(ReceiptPreparation(receipt_number=reserved, posting_date="2026-10-05", period_id="period", item_code="PRODUCT",
                location_code="MAIN/STOCK", quantity="4", total_value_minor=1520, policy_code="MFG", organization_code="ORG", entity_code="ENTITY", workspace="work",
                reason="Cannot relabel uninspected production as standalone FG"), command_id="detached-" + reserved, actor=actor)
        assert business_snapshot(result) == before
    with pytest.raises(psycopg.Error), result.actor("maker") as (connection, receipts, actor):
        receipts.finance.finance.create_entry(entry_number="EXTRA-UNBACKED-PRODUCTION", organization_code="ORG", entity_code="ENTITY", period_id="period",
            journal_code="STOCK", posting_date="2026-10-05", description="A generic journal cannot attach unbacked extra source WIP", external_reference=source["id"],
            workspace="work", actor_label=actor.username, lines=[{"account_code": "WIP", "debit": "9.00"}, {"account_code": "LABOR", "credit": "9.00"}])
    assert business_snapshot(result) == before
    with result.actor("poster") as (connection, _, actor):
        parent = PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(source["id"], actor=actor)
        assert parent["wip_minor"] == 3800 and parent["held_quantity_scaled"] == 4


def test_direct_sql_forged_production_birth_cannot_mask_original_payload_identity(manufacturing_v2_database: tuple[str, str]) -> None:
    from uuid import uuid4

    import psycopg

    result = system(manufacturing_v2_database)
    source = order(result)
    owner_phase(result, owner_phase(result, owner_phase(result, source, "prepare"), "review"), "post")
    with result.actor("maker") as (connection, _, actor):
        held = PostgresManufacturingExecutionV2Repository(connection, result.tenant).produce(source["id"], output_quantity="4",
            operations=[{"sequence": 1, "minutes": 24, "evidence_reference": "SYN-BIRTH-IDENTITY"}], period_id="period", posting_date="2026-10-05",
            command_id="identity-produce", reason="Exact production source identity", actor=actor)
        payload = connection.execute("SELECT payload FROM reconforge.manufacturing_execution_v2_productions WHERE tenant_id=%s AND id=%s",
            (result.tenant, held["id"])).fetchone()["payload"]
    before = business_snapshot(result)
    for field in ("id", "order_id", "workspace_id", "organization_id", "legal_entity_id"):
        with result.actor("maker") as (connection, _, actor):
            identifier = "ME2P-" + uuid4().hex.upper()
            forged = {**payload, "id": identifier, field: "FOREIGN-SOURCE"}
            connection.execute("SELECT set_config('app.manufacturing_execution_v2_actor_id',%s,true)", (actor.user_id,))
            with pytest.raises(psycopg.errors.CheckViolation, match="payload identity"), connection.transaction():
                # Assert the INSERT itself fails, before history could merely
                # reject an orphan at transaction commit or uniqueness can mask it.
                connection.execute("""INSERT INTO reconforge.manufacturing_execution_v2_productions
                    (tenant_id,id,order_id,workspace_id,organization_id,legal_entity_id,payload,source_digest)
                    VALUES(%s,%s,%s,'work','org','entity',%s::jsonb,%s)""",
                    (result.tenant, identifier, source["id"], canonical_json(forged), digest_payload(forged)))
        assert business_snapshot(result) == before


def test_cost_claim_rejects_generated_expense_and_allocation_before_original_expense_date(manufacturing_v2_database: tuple[str, str]) -> None:
    from dataclasses import replace

    result = system(manufacturing_v2_database)
    source = order(result)
    with pytest.raises(FinancePostingError, match="Only Manual entries"):
        # The existing native public poster itself refuses this unowned
        # Generated source; there is no posted expense eligible for ME2.
        original_expense(result, "LABOR", "UNOWNED-GENERATED-EXPENSE", "20.00", source_type="Generated")
    before = business_snapshot(result)
    backdated = clone_request(source, "EXPENSE-BACKDATED-REFUSED")
    with pytest.raises(FinancePostingError, match="original posted native Manual"), result.actor("maker") as (connection, _, actor):
        PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_order(
            ManufacturingOrderPreparation(replace(backdated.material, posting_date="2026-10-02"), backdated.routing_id, backdated.claims),
            command_id="backdated-claim", actor=actor)
    assert business_snapshot(result) == before
