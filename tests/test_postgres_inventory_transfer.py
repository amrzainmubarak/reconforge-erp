"""Restricted-role IT1 originals; finite Root quantity/native hooks qualify separately."""
from collections.abc import Iterator
from typing import Any

import pytest

from reconforge.domain.finance_posting import canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation
from reconforge.domain.inventory_transfer import PERMISSIONS, TransferPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from reconforge.infrastructure.postgres_inventory_transfer_schema import DOWNGRADE_SQL, OWNER_SQL, TABLES_SQL
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database as baseline_receipt_database

_ = baseline_receipt_database
TABLES = ("inventory_transfer_sources", "inventory_transfer_claims", "inventory_transfer_releases", "inventory_transfer_events", "inventory_transfer_commands")


@pytest.fixture(scope="module")
def transfer_database(baseline_receipt_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql

    with psycopg.connect(baseline_receipt_database[0]) as admin:
        admin.execute(TABLES_SQL)
        admin.execute(OWNER_SQL)
        with admin.transaction(force_rollback=True):
            admin.execute(DOWNGRADE_SQL)
            assert admin.execute("SELECT to_regclass('reconforge.inventory_transfer_sources')").fetchone()[0] is None
            admin.execute(TABLES_SQL)
            admin.execute(OWNER_SQL)
        role = psycopg.conninfo.conninfo_to_dict(baseline_receipt_database[1])["user"]
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
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


def test_populated_original_refuses_destructive_owned_inverse(transfer_database: tuple[str, str]) -> None:
    import psycopg

    runtime = transfer_runtime(transfer_database)
    with runtime.actor("maker") as (connection, _, actor):
        PostgresInventoryTransferRepository(connection, runtime.tenant).create(request(), command_id="it1-inverse-refusal-create", actor=actor)
    with psycopg.connect(transfer_database[0]) as admin:
        count = admin.execute("SELECT count(*) FROM reconforge.inventory_transfer_sources").fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation, match="Populated"), admin.transaction():
            admin.execute(DOWNGRADE_SQL)
        assert admin.execute("SELECT count(*) FROM reconforge.inventory_transfer_sources").fetchone()[0] == count
