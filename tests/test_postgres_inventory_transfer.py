"""Restricted-role IT1 originals; finite Root quantity/native hooks qualify separately."""
from collections.abc import Iterator
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation
from reconforge.domain.inventory_transfer import PERMISSIONS, TransferInversePreparation, TransferPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_inventory_valuation_reversal import PostgresInventoryValuationReversalRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database as baseline_receipt_database

_ = baseline_receipt_database
TABLES = ("inventory_transfer_sources", "inventory_transfer_claims", "inventory_transfer_releases", "inventory_transfer_events", "inventory_transfer_commands")


@pytest.fixture(scope="module")
def transfer_database(baseline_receipt_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg

    with psycopg.connect(baseline_receipt_database[0]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0147_pg_customer_partial_returns"
        assert admin.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity", (list(TABLES),)).fetchone()[0] == 5
    yield baseline_receipt_database


def transfer_runtime(database: tuple[str, str]) -> ReceiptRuntime:
    runtime = create_receipt_runtime(database)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                authority.grant(tenant_id=runtime.tenant, grant_id=f"it1-{person}-{identifier}", principal_type="user",
                    principal_id=person, scope_type=kind, scope_id=identifier, actor_id=person)
        inventory = PostgresInventoryCoreRepository(connection, runtime.tenant)
        inventory.upsert_warehouse(warehouse_code="SECOND", name="Independent second warehouse", organization_code="ORG", entity_code="ENTITY", workspace="work")
        inventory.upsert_location(warehouse_code="SECOND", location_code="STOCK", name="Destination stock", organization_code="ORG", workspace="work")
    original = ReceiptPreparation(receipt_number="TRANSFER-OPENING", posting_date="2026-10-03", period_id="period", item_code="ITEM",
        location_code="MAIN/STOCK", quantity="3", total_value_minor=3600, policy_code="FIFO", organization_code="ORG", entity_code="ENTITY",
        workspace="work", reason="Actual approved opening stock for same-entity transfer")
    with runtime.actor("maker") as (_, owner, actor):
        plan = owner.prepare_receipt(original, command_id="it1-opening-prepare", actor=actor)
    with runtime.actor("checker") as (_, owner, actor):
        review = owner.review(plan["plan_id"], command_id="it1-opening-review", expected_plan_digest=plan["plan_digest"], reason="Independent exact opening review", actor=actor)
    with runtime.actor("poster") as (_, owner, actor):
        owner.commit(plan["plan_id"], command_id="it1-opening-post", expected_review_digest=review["review_digest"], reason="Actual original posted opening", actor=actor)
    return runtime


def request(number: str = "TRANSFER-1") -> TransferPreparation:
    return TransferPreparation(number, "ITEM", "1", "MAIN/STOCK", "SECOND/STOCK", "period", "2026-10-14",
        "Move one original approved unit", {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"})


def native_business(connection: Any, tenant: str) -> dict[str, Any]:
    from psycopg import sql
    tables = ("inventory_cost_layers", "inventory_layer_consumptions", "inventory_valuation_documents", "inventory_valuation_lines",
        "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links", "finance_entries", "finance_entry_lines", "finance_posting_effects")
    return {name: [row["original"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) original FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (tenant,))] for name in tables}


def test_real_original_approved_cost_draft_and_immutable_command_replay(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        before = canonical_json(native_business(connection, runtime.tenant))
        result = owner.create(request(), command_id="it1-create", actor=actor)
        source = result["source"]
        assert source["phase"] == 0 and source["row_version"] == 1 and source["claim"] is None
        assert source["cost_snapshot"]["remaining_quantity_scaled"] == 3 and source["cost_snapshot"]["remaining_value_minor"] == 3600
        original = source["cost_snapshot"]["sources"][0]
        assert original["layer"]["original_value_minor"] == original["valuation_document"]["total_value_minor"] == 3600
        assert original["finance_entry"]["total_debit_minor"] == original["finance_entry"]["total_credit_minor"] == 3600
        assert result["native_response"]["head"]["status"] == "Draft"
        assert owner.create(request(), command_id="it1-create", actor=actor) == result
        ack = owner.command_receipt(source["id"], "it1-create", result, actor=actor)
        assert ack["actor_id"] == actor.user_id and ack["request_digest"] == digest_payload(ack["request_json"])
        assert before == canonical_json(native_business(connection, runtime.tenant))
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
    with runtime.actor("checker") as (connection, _, actor):
        assert PostgresInventoryTransferRepository(connection, runtime.tenant).get(source["id"], actor=actor) == source
        assert PostgresInventoryTransferRepository(connection, runtime.tenant).list_transfers(request().scope, actor=actor)["transfers"] == [source]


def test_populated_original_refuses_destructive_canonical_inverse(transfer_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    from pathlib import Path

    import psycopg

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0146_postgres_inventory_transfer.py"
    spec = importlib.util.spec_from_file_location("owned_test_canonical_transfer", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        PostgresInventoryTransferRepository(connection, runtime.tenant).create(request(), command_id="it1-inverse-refusal-create", actor=actor)
    with psycopg.connect(transfer_database[0]) as admin:
        count = admin.execute("SELECT count(*) FROM reconforge.inventory_transfer_sources").fetchone()[0]
        with monkeypatch.context() as patch:
            patch.setattr(migration.op, "execute", lambda query: admin.execute(str(query)))
            with pytest.raises(psycopg.errors.CheckViolation, match="Retained transfer"), admin.transaction():
                migration.downgrade()
        assert admin.execute("SELECT count(*) FROM reconforge.inventory_transfer_sources").fetchone()[0] == count


def phase(runtime: ReceiptRuntime, result: dict[str, Any], operation: str, person: str) -> dict[str, Any]:
    source = result["source"]
    with runtime.actor(person) as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        return owner.act(source["id"], operation, expected_digest=source["source_digest"], expected_version=source["row_version"],
            command_id=source["id"] + "-" + operation, reason="Independent actual " + operation, actor=actor)


def physical(connection: Any, runtime: ReceiptRuntime) -> dict[str, int]:
    rows = connection.execute("""SELECT location.location_code,w.warehouse_code,COALESCE(sum(
        CASE WHEN l.to_location_id=location.id THEN l.quantity_scaled ELSE 0 END
        -CASE WHEN l.from_location_id=location.id THEN l.quantity_scaled ELSE 0 END) FILTER(WHERE m.status='Posted'),0) quantity
        FROM reconforge.inventory_locations location JOIN reconforge.inventory_warehouses w ON w.tenant_id=location.tenant_id AND w.id=location.warehouse_id
        LEFT JOIN reconforge.inventory_movement_lines l ON l.tenant_id=location.tenant_id AND(location.id=l.from_location_id OR location.id=l.to_location_id)
        LEFT JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id WHERE location.tenant_id=%s
        GROUP BY w.warehouse_code,location.location_code ORDER BY w.warehouse_code,location.location_code""", (runtime.tenant,))
    return {row["warehouse_code"] + "/" + row["location_code"]: int(row["quantity"]) for row in rows}


def test_actual_canonical146_forward_and_independent_child_inverse_preserve_fifo_gl_and_original_ack(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        original_financial = canonical_json(native_business(connection, runtime.tenant))
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        created = PostgresInventoryTransferRepository(connection, runtime.tenant).create(request(), command_id="actual-forward-create", actor=actor)
    reviewed = phase(runtime, created, "review", "checker")
    with runtime.actor("checker") as (connection, _, actor):
        guard = connection.execute("SELECT * FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s AND owner_namespace='IT1'", (runtime.tenant,)).fetchone()
        assert guard["quantity_scaled"] == 1 and guard["owner_claim_id"] == reviewed["source"]["claim"]["id"]
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
    posted = phase(runtime, reviewed, "post", "poster")
    source = posted["source"]
    with runtime.actor("poster") as (connection, _, actor):
        assert physical(connection, runtime) == {"MAIN/STOCK": 2, "SECOND/STOCK": 1}
        assert canonical_json(native_business(connection, runtime.tenant)) == original_financial
        assert source["phase"] == 2 and source["row_version"] == 3 and source["claim"]["state"] == "Posted"
        assert source["release"]["target_movement_id"] == source["native_movement_id"]
        assert PostgresInventoryTransferRepository(connection, runtime.tenant).act(source["id"], "post", expected_digest=source["source_digest"], expected_version=2,
            command_id=source["id"] + "-post", reason="Independent actual post", actor=actor) == posted
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.create(request(), command_id="actual-forward-create", actor=actor) == created
        child = owner.create_inverse(TransferInversePreparation(source["id"], source["source_digest"], source["row_version"],
            "TRANSFER-INVERSE", "period", "2026-10-14", "Independent physical compensation"), command_id="actual-inverse-create", actor=actor)
    child = phase(runtime, child, "review", "checker")
    child = phase(runtime, child, "post", "poster")
    with runtime.actor("poster") as (connection, _, actor):
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        assert canonical_json(native_business(connection, runtime.tenant)) == original_financial
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(source["id"], actor=actor) == source
        assert child["source"]["original"]["id"] == source["id"] and child["source"]["phase"] == 2
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s AND owner_namespace='IT1'", (runtime.tenant,)).fetchone()["n"] == 2
    from tests.inventory_transfer_browser import export_inventory_transfer_proof

    export_inventory_transfer_proof(runtime)


def test_actual_reviewed_and_unreviewed_cancel_retain_native_draft_and_release_only_original_claim(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        original_financial = canonical_json(native_business(connection, runtime.tenant))
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        draft = owner.create(request("CANCEL-DRAFT"), command_id="cancel-draft-create", actor=actor)
        reviewed = owner.create(request("CANCEL-REVIEWED"), command_id="cancel-reviewed-create", actor=actor)
    reviewed = phase(runtime, reviewed, "review", "checker")
    cancelled_draft = phase(runtime, draft, "cancel", "checker")
    cancelled_reviewed = phase(runtime, reviewed, "cancel", "checker")
    with runtime.actor("checker") as (connection, _, actor):
        assert cancelled_draft["source"]["row_version"] == 2 and cancelled_draft["source"]["claim"] is None
        assert cancelled_reviewed["source"]["row_version"] == 3 and cancelled_reviewed["source"]["claim"]["state"] == "Released"
        assert cancelled_reviewed["source"]["release"]["purpose"] == "Cancel" and cancelled_reviewed["source"]["release"]["target_movement_id"] is None
        assert all(result["native_response"]["head"]["status"] == "Draft" for result in (cancelled_draft, cancelled_reviewed))
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        assert canonical_json(native_business(connection, runtime.tenant)) == original_financial


def add_approved_receipt(runtime: ReceiptRuntime, number: str, *, item_code: str = "ITEM") -> None:
    original = ReceiptPreparation(receipt_number=number, posting_date="2026-10-04", period_id="period", item_code=item_code,
        location_code="MAIN/STOCK", quantity="3", total_value_minor=3600, policy_code="FIFO", organization_code="ORG", entity_code="ENTITY",
        workspace="work", reason="Additional original approved receipt with independent human custody")
    with runtime.actor("maker") as (_, owner, actor):
        plan = owner.prepare_receipt(original, command_id=number + "-prepare", actor=actor)
    with runtime.actor("checker") as (_, owner, actor):
        review = owner.review(plan["plan_id"], command_id=number + "-review", expected_plan_digest=plan["plan_digest"], reason="Independent complete added source review", actor=actor)
    with runtime.actor("poster") as (_, owner, actor):
        owner.commit(plan["plan_id"], command_id=number + "-post", expected_review_digest=review["review_digest"], reason="Actual additional posted original", actor=actor)


def consume_original(runtime: ReceiptRuntime, number: str, *, quantity: str = "1") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        movement = PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(movement_number=number,
            movement_type="Delivery", organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-10",
            description="Actual original FIFO withdrawal", workspace="work", actor_label=actor.user_id,
            lines=[{"item_code": "ITEM", "quantity": quantity, "from_location": "MAIN/STOCK"}])
    with runtime.actor("poster") as (connection, _, actor):
        PostgresInventoryCoreRepository(connection, runtime.tenant).post_movement(movement["id"], reason="Independent ordinary source withdrawal", actor_label=actor.user_id)
    with runtime.actor("maker") as (connection, _, actor):
        document = PostgresInventoryValuationRepository(connection, runtime.tenant).create_document(valuation_number=number + "-FIFO",
            movement_id=movement["id"], policy_code="FIFO", actor_label=actor.user_id)
    with runtime.actor("checker") as (connection, _, actor):
        PostgresInventoryValuationRepository(connection, runtime.tenant).approve_document(document["id"], reason="Independent exact native FIFO consumption", actor_label=actor.user_id)
    return document


def test_real_consumption_residuals_historical_subset_and_native_byte_membership(transfer_database: tuple[str, str]) -> None:
    from copy import deepcopy

    import psycopg

    runtime = transfer_runtime(transfer_database)
    consume_original(runtime, "ORIGINAL-CONSUMPTION-1")
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        result = owner.create(request(), command_id="consumption-source-create", actor=actor)
        cost = result["source"]["cost_snapshot"]
        assert cost["remaining_quantity_scaled"] == 2 and cost["remaining_value_minor"] == 2400
        original = cost["sources"][0]
        assert len(original["consumptions"]) == 1 and original["consumptions"][0]["quantity_scaled"] == 1 and original["consumptions"][0]["value_minor"] == 1200
        assert original["receipt_native"]["lines"][0]["quantity_scaled"] == 3 and original["valuation_input"]["total_cost_minor"] == 3600
        forged = deepcopy(cost)
        forged["sources"][0]["consumptions"][0].update(quantity_scaled=2, value_minor=2400)
        forged["sources"][0]["layer"].update(remaining_quantity_scaled=1, remaining_value_minor=1200)
        # The forged facts conserve internally, yet do not belong to the native
        # immutable original. Refusal must come from independent row membership.
        with pytest.raises(psycopg.errors.CheckViolation, match="historical consumption"), connection.transaction():
            connection.execute("SELECT reconforge.it1_cost_originals(%s,%s::jsonb)", (runtime.tenant, canonical_json(forged)))
        duplicated = deepcopy(cost)
        duplicated["sources"][0]["consumptions"] *= 2
        duplicated["sources"][0]["layer"].update(remaining_quantity_scaled=1, remaining_value_minor=1200)
        duplicated.update(remaining_quantity_scaled=1, remaining_value_minor=1200)
        with pytest.raises(psycopg.errors.CheckViolation, match="duplicate"), connection.transaction():
            connection.execute("SELECT reconforge.it1_cost_originals(%s,%s::jsonb)", (runtime.tenant, canonical_json(duplicated)))
    consume_original(runtime, "ORIGINAL-CONSUMPTION-2")
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(result["source"]["id"], actor=actor) == result["source"]
        assert owner.create(request(), command_id="consumption-source-create", actor=actor) == result
        layer = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        assert dict(layer) == {"remaining_quantity_scaled": 1, "remaining_value_minor": 1200}


def test_actual_restored_fifo_correction_class_refuses_new_transfer_cost_adoption(transfer_database: tuple[str, str]) -> None:
    import psycopg

    runtime = transfer_runtime(transfer_database)
    consumed = consume_original(runtime, "ORIGINAL-CONSUMPTION")
    with runtime.actor("maker") as (connection, _, actor):
        movement = PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(movement_number="RESTORE-ORIGINAL-CONSUMPTION",
            movement_type="Receipt", organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-11",
            description="Actual approved compensating native FIFO correction", workspace="work", actor_label=actor.user_id,
            lines=[{"item_code": "ITEM", "quantity": "1", "to_location": "MAIN/STOCK"}])
    with runtime.actor("poster") as (connection, _, actor):
        PostgresInventoryCoreRepository(connection, runtime.tenant).post_movement(movement["id"], reason="Independent compensating physical source", actor_label=actor.user_id)
    with runtime.actor("maker") as (connection, _, actor):
        inverse = PostgresInventoryValuationReversalRepository(connection, runtime.tenant).create_reversal(reversal_number="RESTORE-FIFO",
            original_valuation_document_id=consumed["id"], reversal_movement_id=movement["id"], actor_label=actor.user_id)
    with runtime.actor("checker") as (connection, _, actor):
        PostgresInventoryValuationReversalRepository(connection, runtime.tenant).approve_reversal(inverse["id"], reason="Restore exact immutable original FIFO consumption", actor_label=actor.user_id)
    with runtime.actor("maker") as (connection, _, actor):
        before = canonical_json(native_business(connection, runtime.tenant))
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=%s AND effect_type='Restore'", (runtime.tenant,)).fetchone()["n"] == 1
        with pytest.raises(FinancePostingError) as refused, connection.transaction():
            PostgresInventoryTransferRepository(connection, runtime.tenant).create(request(), command_id="refuse-unsupported-correction", actor=actor)
        assert refused.value.code == "operational_state_conflict"
        assert isinstance(refused.value.__cause__, psycopg.errors.CheckViolation) and "correction owners" in str(refused.value.__cause__)
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert before == canonical_json(native_business(connection, runtime.tenant))


@pytest.mark.parametrize("balanced_offset", [False, True])
def test_actual_unvalued_manual_destination_receipt_cannot_reserve_as_approved_original_stock(transfer_database: tuple[str, str], balanced_offset: bool) -> None:
    """Approved commodity FIFO at A does not prove an unsupported new receipt at B."""
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        receipt = PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(movement_number="UNVALUED-DESTINATION",
            movement_type="Receipt", source_type="Manual", organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-14",
            workspace="work", description="Actual unsupported physical input without approved cost", actor_label=actor.user_id,
            lines=[{"item_code": "ITEM", "quantity": "1", "to_location": "SECOND/STOCK"}])
    with runtime.actor("poster") as (connection, _, actor):
        PostgresInventoryCoreRepository(connection, runtime.tenant).post_movement(receipt["id"], reason="Actual independent legacy manual stock input", actor_label=actor.user_id)
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 1}
        originals = canonical_json(native_business(connection, runtime.tenant))
    if balanced_offset:
        with runtime.actor("maker") as (connection, _, actor):
            delivery = PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(movement_number="UNVALUED-OFFSET",
                movement_type="Delivery", source_type="Manual", organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-14",
                workspace="work", description="Actual unvalued offset leaves equal aggregate quantities", actor_label=actor.user_id,
                lines=[{"item_code": "ITEM", "quantity": "1", "from_location": "MAIN/STOCK"}])
        with runtime.actor("poster") as (connection, _, actor):
            PostgresInventoryCoreRepository(connection, runtime.tenant).post_movement(delivery["id"], reason="Actual independent unvalued offset", actor_label=actor.user_id)
            assert physical(connection, runtime) == {"MAIN/STOCK": 2, "SECOND/STOCK": 1}
            assert sum(physical(connection, runtime).values()) == connection.execute("SELECT remaining_quantity_scaled FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["remaining_quantity_scaled"] == 3
    unsupported = TransferPreparation("UNSUPPORTED-B-ORIGIN", "ITEM", "1", "SECOND/STOCK", "MAIN/STOCK", "period", "2026-10-14",
        "Cannot claim unsupported original stock as approved IRP input", request().scope)
    created = None
    try:
        with runtime.actor("maker") as (connection, _, actor):
            created = PostgresInventoryTransferRepository(connection, runtime.tenant).create(unsupported, command_id="unsupported-physical-create", actor=actor)
    except FinancePostingError as refused:
        assert "conflict" in refused.code
    if created is not None:
        try:
            phase(runtime, created, "review", "checker")
        except FinancePostingError as refused:
            assert "conflict" in refused.code
        else:
            import json
            import os
            from pathlib import Path

            from tests.inventory_transfer_browser import inventory_transfer_proof

            if directory := os.environ.get("RECONFORGE_IT1_NATIVE_PROOF_DIR"):
                with (Path(directory) / "unsupported-physical-original-populations.json").open("x", encoding="utf-8") as original:
                    json.dump(inventory_transfer_proof(runtime, actor_name="poster"), original, indent=2, sort_keys=True, allow_nan=False)
                    original.write("\n")
            pytest.fail("An unsupported unvalued native receipt was incorrectly reserved as approved original stock.")
    with runtime.actor("poster") as (connection, _, _):
        assert physical(connection, runtime) == {"MAIN/STOCK": 2 if balanced_offset else 3, "SECOND/STOCK": 1}
        assert canonical_json(native_business(connection, runtime.tenant)) == originals
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_claims WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_actual_prior_it1_relocation_supports_independent_new_forward_source_without_warehouse_cost_allocation(transfer_database: tuple[str, str]) -> None:
    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        original = canonical_json(native_business(connection, runtime.tenant))
        first = PostgresInventoryTransferRepository(connection, runtime.tenant).create(request("PRIOR-APPROVED-RELOCATION"), command_id="prior-governed-create", actor=actor)
    first = phase(runtime, phase(runtime, first, "review", "checker"), "post", "poster")
    second_request = TransferPreparation("NEW-FORWARD-FROM-B", "ITEM", "1", "SECOND/STOCK", "MAIN/STOCK", "period", "2026-10-14",
        "New independent forward source over original governed relocation", request().scope)
    with runtime.actor("maker") as (connection, _, actor):
        second = PostgresInventoryTransferRepository(connection, runtime.tenant).create(second_request, command_id="new-forward-b-create", actor=actor)
        assert second["source"]["original"] is None
    second = phase(runtime, phase(runtime, second, "review", "checker"), "post", "poster")
    with runtime.actor("poster") as (connection, _, actor):
        assert physical(connection, runtime) == {"MAIN/STOCK": 3, "SECOND/STOCK": 0}
        assert canonical_json(native_business(connection, runtime.tenant)) == original
        assert second["source"]["cost_snapshot"]["sources"][0]["layer"]["id"] == first["source"]["cost_snapshot"]["sources"][0]["layer"]["id"]


def test_actual_multi_item_native_consumption_refuses_new_adoption_preserving_historical_original(transfer_database: tuple[str, str]) -> None:
    import psycopg

    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        historical = owner.create(request("BEFORE-MULTI-ITEM-ISSUE"), command_id="before-multi-item", actor=actor)
        PostgresInventoryCoreRepository(connection, runtime.tenant).upsert_item(item_code="ITEM2", name="Independent second source commodity",
            organization_code="ORG", uom_code="EA", inventory_account_code="INVENTORY", workspace="work")
    add_approved_receipt(runtime, "OTHER-ITEM-COMPLETE-COST", item_code="ITEM2")
    with runtime.actor("maker") as (connection, _, actor):
        movement = PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(movement_number="MULTI-ITEM-OUTBOUND",
            movement_type="Delivery", organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-10",
            description="Actual supported Core two-item issue outside first IT1 source class", workspace="work", actor_label=actor.user_id,
            lines=[{"item_code": code, "quantity": "1", "from_location": "MAIN/STOCK"} for code in ("ITEM", "ITEM2")])
    with runtime.actor("poster") as (connection, _, actor):
        PostgresInventoryCoreRepository(connection, runtime.tenant).post_movement(movement["id"], reason="Independent original two-item physical issue", actor_label=actor.user_id)
    with runtime.actor("maker") as (connection, _, actor):
        document = PostgresInventoryValuationRepository(connection, runtime.tenant).create_document(valuation_number="MULTI-ITEM-FIFO",
            movement_id=movement["id"], policy_code="FIFO", actor_label=actor.user_id)
    with runtime.actor("checker") as (connection, _, actor):
        PostgresInventoryValuationRepository(connection, runtime.tenant).approve_document(document["id"], reason="Independent complete two-item FIFO issue", actor_label=actor.user_id)
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresInventoryTransferRepository(connection, runtime.tenant)
        assert owner.get(historical["source"]["id"], actor=actor) == historical["source"]
        assert owner.create(request("BEFORE-MULTI-ITEM-ISSUE"), command_id="before-multi-item", actor=actor) == historical
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_valuation_lines WHERE tenant_id=%s AND valuation_document_id=%s", (runtime.tenant, document["id"])).fetchone()["n"] == 2
        before = canonical_json(native_business(connection, runtime.tenant))
        with pytest.raises(FinancePostingError) as refused, connection.transaction():
            owner.create(request("UNSUPPORTED-MULTI-ITEM-ORIGIN"), command_id="refuse-multi-item-origin", actor=actor)
        assert refused.value.code == "operational_state_conflict"
        assert isinstance(refused.value.__cause__, psycopg.errors.CheckViolation) and "one complete" in str(refused.value.__cause__)
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_transfer_sources WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert canonical_json(native_business(connection, runtime.tenant)) == before
