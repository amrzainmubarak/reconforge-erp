"""Real nonowner PostgreSQL AP command replay and backing-source affinity."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from reconforge.application.payables import PurchaseOrderLineInput, SupplierInvoiceLineInput
from reconforge.infrastructure.postgres import (
    PostgresRuntimePooledConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.io.persisted import encode_financial_idempotency_response
from reconforge.platform.common import PlatformError
from tests.test_alembic_postgres import isolated_postgres_migration_dsn
from tests.test_postgres_finance_scope import _wait_for_lock

__all__ = ["isolated_postgres_migration_dsn"]
SCOPE = {"workspace_id": "shared", "organization_id": "org_a", "legal_entity_id": "entity_a"}


@pytest.fixture
def ap_database(isolated_postgres_migration_dsn: str):
    import psycopg
    from alembic.config import Config

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    command.upgrade(Config(str(Path("alembic.ini").resolve())), "head")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(
            psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role)
        )
        admin.execute(psycopg.sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role))
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES('ap_replay','Synthetic AP')")
        admin.execute(
            "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES('ap_replay','shared','Shared'),('ap_replay','other','Other')"
        )
        admin.execute(
            "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('ap_replay','EGP','Synthetic',2)"
        )
        for letter in ("a", "b"):
            admin.execute(
                "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES('ap_replay',%s,%s,%s,'EGP','shared')",
                (f"org_{letter}", f"ORG_{letter.upper()}", letter),
            )
            admin.execute(
                "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES('ap_replay','shared',%s)",
                (f"org_{letter}",),
            )
            admin.execute(
                "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES('ap_replay',%s,%s,%s,%s,'EGP')",
                (f"entity_{letter}", f"org_{letter}", letter.upper(), letter),
            )
    factory = PostgresRuntimePooledConnectionFactory(
        PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False), max_size=3
    )
    boundary = PostgresTenantBoundary(factory)
    try:
        with boundary.transaction("ap_replay", **SCOPE) as connection:
            PostgresPayablesRepository(connection, "ap_replay").upsert_supplier(
                supplier_code="SUP",
                name="Synthetic supplier",
                currency_code="EGP",
                workspace="Shared",
                organization_code="ORG_A",
                entity_code="A",
            )
        yield {"admin": isolated_postgres_migration_dsn, "boundary": boundary, "factory": factory}
    finally:
        factory.close()


def command_for(
    repository: PostgresPayablesRepository, operation: str, suffix: str = "1"
) -> tuple[Any, dict[str, Any]]:
    po = dict(
        po_number=f"PO-{suffix}",
        supplier_code="SUP",
        order_date="2026-07-28",
        currency_code="EGP",
        lines=[PurchaseOrderLineInput(item_code="ITEM", ordered_quantity="10", unit_price_minor=1200)],
        workspace="Shared",
        organization_code="ORG_A",
        entity_code="A",
        actor_label="maker",
    )
    if operation == "purchase_order":
        return repository.create_purchase_order, {**po, "idempotency_key": f"key-{suffix}"}
    order = repository.create_purchase_order(**po)
    repository.submit_purchase_order(order["id"], expected_version=1, actor_label="maker")
    order = repository.approve_purchase_order(order["id"], expected_version=2, actor_label="checker")
    line_id = order["lines"][0]["id"]
    if operation == "goods_receipt":
        return repository.post_receipt, dict(
            receipt_number=f"GR-{suffix}",
            purchase_order_id=order["id"],
            receipt_date="2026-07-28",
            quantities={line_id: "2"},
            workspace="Shared",
            idempotency_key=f"key-{suffix}",
            actor_label="receiver",
        )
    return repository.create_supplier_invoice, dict(
        invoice_number=f"INV-{suffix}",
        supplier_code="SUP",
        invoice_date="2026-07-28",
        currency_code="EGP",
        total_minor=2400,
        lines=[
            SupplierInvoiceLineInput(
                purchase_order_line_id=line_id, invoiced_quantity="2", unit_price_minor=1200, line_total_minor=2400
            )
        ],
        purchase_order_id=order["id"],
        workspace="Shared",
        organization_code="ORG_A",
        entity_code="A",
        idempotency_key=f"key-{suffix}",
        actor_label="maker",
    )


@pytest.mark.parametrize("operation", ["purchase_order", "goods_receipt", "supplier_invoice"])
def test_live_ap_jsonb_exact_replay(ap_database: dict[str, Any], operation: str) -> None:
    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repository, operation)
        first = command(**payload)
        assert command(**payload) == first


def _stored(connection: Any, operation: str) -> dict[str, Any]:
    return connection.execute(
        "SELECT response_json FROM reconforge.ap_idempotency_keys WHERE scope=%s AND idempotency_key='key-1'",
        (f"{operation}:shared",),
    ).fetchone()[0]


def _write_stored(connection: Any, operation: str, value: dict[str, Any]) -> None:
    connection.execute(
        "UPDATE reconforge.ap_idempotency_keys SET response_json=%s::jsonb WHERE scope=%s AND idempotency_key='key-1'",
        (encode_financial_idempotency_response(value).text, f"{operation}:shared"),
    )


@pytest.mark.parametrize("operation", ["purchase_order", "goods_receipt", "supplier_invoice"])
def test_live_ap_replay_returns_current_source_and_reads_verified_legacy(
    ap_database: dict[str, Any], operation: str
) -> None:
    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repository, operation)
        original = command(**payload)
        current = original
        if operation == "purchase_order":
            repository.submit_purchase_order(original["id"], expected_version=1, actor_label="maker")
            current = repository.approve_purchase_order(original["id"], expected_version=2, actor_label="checker")
        elif operation == "supplier_invoice":
            current = repository.submit_supplier_invoice(original["id"], expected_version=1, actor_label="maker")
        before = tuple(
            connection.execute(
                "SELECT (SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events)"
            ).fetchone()
        )
        assert command(**payload) == current
        _write_stored(connection, operation, original)
        assert command(**payload) == current
        assert (
            tuple(
                connection.execute(
                    "SELECT (SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events)"
                ).fetchone()
            )
            == before
        )
        assert current["id"] == original["id"]


@pytest.mark.parametrize("operation", ["purchase_order", "goods_receipt", "supplier_invoice"])
def test_live_ap_replay_binds_all_creation_inputs(ap_database: dict[str, Any], operation: str) -> None:
    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repository, operation)
        original = command(**payload)
        changes: list[dict[str, Any]] = [{"actor_label": "other-maker"}]
        if operation == "purchase_order":
            changes += [
                {"po_number": "OTHER"},
                {"order_date": "2026-07-29"},
                {"expected_date": "2026-08-01"},
                {"lines": [replace(payload["lines"][0], ordered_quantity="9")]},
                {"lines": [replace(payload["lines"][0], unit_price_minor=1300)]},
                {"lines": [replace(payload["lines"][0], tax_minor=1)]},
                {"lines": [replace(payload["lines"][0], description="changed")]},
            ]
        elif operation == "goods_receipt":
            changes += [
                {"receipt_number": "OTHER"},
                {"receipt_date": "2026-07-29"},
                {"quantities": {line_id: "3" for line_id in payload["quantities"]}},
            ]
        else:
            changes += [
                {"invoice_number": "OTHER"},
                {"invoice_date": "2026-07-29"},
                {"due_date": "2026-08-01"},
                {"total_minor": 2401, "tax_minor": 1},
                {
                    "total_minor": 2600,
                    "lines": [replace(payload["lines"][0], unit_price_minor=1300, line_total_minor=2600)],
                },
                {"lines": [replace(payload["lines"][0], invoiced_quantity="3")]},
                {"lines": [replace(payload["lines"][0], description="changed")]},
            ]
        before = tuple(
            connection.execute(
                "SELECT (SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events)"
            ).fetchone()
        )
        for legacy in (False, True):
            if legacy:
                _write_stored(connection, operation, original)
            for change in changes:
                with pytest.raises(PlatformError):
                    command(**{**payload, **change})
        assert command(**payload) == original
        assert (
            tuple(
                connection.execute(
                    "SELECT (SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events)"
                ).fetchone()
            )
            == before
        )


@pytest.mark.parametrize("operation", ["purchase_order", "goods_receipt", "supplier_invoice"])
def test_live_ap_replay_denies_forged_response_source_scope_and_version(
    ap_database: dict[str, Any], operation: str
) -> None:
    import copy

    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repository, operation)
        original = command(**payload)
        envelope = _stored(connection, operation)
        other_command, other_payload = command_for(repository, operation, "2")
        other = other_command(**other_payload)
        corruptions = [
            {**envelope, "schema_version": 2},
            {**envelope, "schema_version": True},
            {**envelope, "request_digest": "0" * 64},
            {**envelope, "response": other},
            {**envelope, "response": {**original, "id": "absent-source"}},
            {**envelope, "response": {**original, "workspace_id": "other"}},
            {**envelope, "response": {**original, "unknown": "unverified"}},
            {**original, "id": "absent-source"},
            other,
        ]
        if "row_version" in original:
            corruptions += [{**envelope, "response": {**original, "row_version": 2}}, {**original, "row_version": True}]
        altered = copy.deepcopy(original)
        altered["lines"][0]["created_at"] = "2020-01-01T00:00:00+00:00"
        corruptions.append({**envelope, "response": altered})
        for value in corruptions:
            _write_stored(connection, operation, value)
            with pytest.raises(PlatformError):
                command(**payload)
        _write_stored(connection, operation, envelope)
        assert command(**payload) == original


@pytest.mark.parametrize("operation", ["purchase_order", "goods_receipt", "supplier_invoice"])
def test_live_ap_replay_rechecks_current_sibling_scope(ap_database: dict[str, Any], operation: str) -> None:
    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repository, operation)
        original = command(**payload)
    with ap_database["boundary"].transaction(
        "ap_replay", workspace_id="shared", organization_id="org_b", legal_entity_id="entity_b"
    ) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        method = {
            "purchase_order": repository.create_purchase_order,
            "goods_receipt": repository.post_receipt,
            "supplier_invoice": repository.create_supplier_invoice,
        }[operation]
        with pytest.raises(PlatformError):
            method(**payload)
        assert connection.execute("SELECT count(*) FROM reconforge.ap_idempotency_keys").fetchone()[0] == 1
    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        method = {
            "purchase_order": repository.create_purchase_order,
            "goods_receipt": repository.post_receipt,
            "supplier_invoice": repository.create_supplier_invoice,
        }[operation]
        assert method(**payload) == original


def test_live_ap_receipt_request_binds_canonical_parent_hierarchy(ap_database: dict[str, Any]) -> None:
    import psycopg

    with ap_database["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repository = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repository, "goods_receipt")
        command(**payload)
    # A privileged synthetic mutation simulates later parent reattribution.
    # New replay receipts must preserve the hierarchy captured by the command.
    with psycopg.connect(ap_database["admin"]) as admin:
        admin.execute(
            "UPDATE reconforge.ap_purchase_orders SET organization_id='org_b',legal_entity_id='entity_b' WHERE id=%s",
            (payload["purchase_order_id"],),
        )
    with ap_database["boundary"].transaction(
        "ap_replay", workspace_id="shared", organization_id="org_b", legal_entity_id="entity_b"
    ) as connection, pytest.raises(PlatformError, match="different request"):
        PostgresPayablesRepository(connection, "ap_replay").post_receipt(**payload)


@pytest.mark.parametrize("operation,inactive_parent", [
    ("purchase_order", "supplier"), ("purchase_order", "organization"),
    ("purchase_order", "entity"), ("purchase_order", "branch"),
    ("supplier_invoice", "supplier"), ("supplier_invoice", "organization"),
    ("supplier_invoice", "entity"),
])
def test_live_exact_replay_survives_inactive_parent_but_new_write_does_not(
    ap_database: dict[str, Any], operation: str, inactive_parent: str,
) -> None:
    import psycopg

    db = ap_database
    if inactive_parent == "branch":
        with psycopg.connect(db["admin"]) as admin:
            admin.execute("INSERT INTO reconforge.branches(tenant_id,id,organization_id,legal_entity_id,branch_code,name) VALUES('ap_replay','branch_a','org_a','entity_a','BRANCH','Synthetic branch')")
    with db["boundary"].transaction("ap_replay", **SCOPE) as connection:
        repo = PostgresPayablesRepository(connection, "ap_replay")
        command, payload = command_for(repo, operation)
        if inactive_parent == "branch":
            payload["branch_code"] = "BRANCH"
        original = command(**payload)
    mutations = {
        "supplier": "UPDATE reconforge.ap_suppliers SET status='Suspended' WHERE tenant_id='ap_replay' AND supplier_code='SUP'",
        "organization": "UPDATE reconforge.organizations SET active=FALSE WHERE tenant_id='ap_replay' AND id='org_a'",
        "entity": "UPDATE reconforge.legal_entities SET active=FALSE WHERE tenant_id='ap_replay' AND id='entity_a'",
        "branch": "UPDATE reconforge.branches SET active=FALSE WHERE tenant_id='ap_replay' AND id='branch_a'",
    }
    with psycopg.connect(db["admin"]) as admin:
        admin.execute(mutations[inactive_parent])
        before = tuple(admin.execute("SELECT (SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events),(SELECT count(*) FROM reconforge.ap_idempotency_keys),(SELECT count(*) FROM reconforge.ap_purchase_orders),(SELECT count(*) FROM reconforge.ap_supplier_invoices)").fetchone())
    with db["boundary"].transaction("ap_replay", **SCOPE) as connection:
        command = _method(PostgresPayablesRepository(connection, "ap_replay"), operation)
        assert command(**payload) == original
        _write_stored(connection, operation, original)
        assert command(**payload) == original
        number = "po_number" if operation == "purchase_order" else "invoice_number"
        for key in ("fresh-key", ""):
            with pytest.raises(PlatformError, match="active"):
                command(**{**payload, number: "NEW-DOCUMENT", "idempotency_key": key})
    with psycopg.connect(db["admin"]) as admin:
        after = tuple(admin.execute("SELECT (SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events),(SELECT count(*) FROM reconforge.ap_idempotency_keys),(SELECT count(*) FROM reconforge.ap_purchase_orders),(SELECT count(*) FROM reconforge.ap_supplier_invoices)").fetchone())
    assert after == before


def _method(repository: PostgresPayablesRepository, operation: str) -> Any:
    return {
        "purchase_order": repository.create_purchase_order,
        "goods_receipt": repository.post_receipt,
        "supplier_invoice": repository.create_supplier_invoice,
    }[operation]


@pytest.mark.parametrize("operation", ["purchase_order", "goods_receipt", "supplier_invoice"])
def test_live_ap_concurrent_same_command_waits_and_returns_one_effect(
    ap_database: dict[str, Any], operation: str
) -> None:

    boundary = ap_database["boundary"]
    with boundary.transaction("ap_replay", **SCOPE) as connection:
        _, payload = command_for(PostgresPayablesRepository(connection, "ap_replay"), operation)
    ready: Queue[int] = Queue()

    def retry() -> dict[str, Any]:
        with boundary.transaction("ap_replay", **SCOPE) as connection:
            ready.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
            return _method(PostgresPayablesRepository(connection, "ap_replay"), operation)(**payload)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with boundary.transaction("ap_replay", **SCOPE) as connection:
            first = _method(PostgresPayablesRepository(connection, "ap_replay"), operation)(**payload)
            future = pool.submit(retry)
            _wait_for_lock(ap_database["admin"], ready.get(timeout=10))
        assert future.result(timeout=15) == first
    with boundary.transaction("ap_replay", **SCOPE) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.ap_idempotency_keys WHERE scope=%s", (f"{operation}:shared",)
            ).fetchone()[0]
            == 1
        )


def test_live_password_http_ap_replay_is_current_exact_and_scoped(ap_database: dict[str, Any], tmp_path: Path) -> None:
    import psycopg
    from fastapi.testclient import TestClient

    from reconforge.api import create_api_app
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    db = ap_database
    password = "Synthetic-AP-replay-password-2026!"
    permissions = {"payables.read", "payables.manage", "payables.approve"}
    with db["boundary"].transaction("ap_replay") as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in permissions:
            identity.create_permission(tenant_id="ap_replay", permission_name=permission)
        for actor in ("api-maker", "api-checker"):
            identity.create_role(tenant_id="ap_replay", role_name=actor)
            for permission in permissions:
                identity.grant_permission(tenant_id="ap_replay", role_name=actor, permission_name=permission)
            identity.create_user(
                tenant_id="ap_replay", user_id=actor, username=actor, password=password, role_name=actor
            )
            for kind, identifier in (
                ("workspace", "shared"),
                ("organization", "org_a"),
                ("organization", "org_b"),
                ("legal_entity", "entity_a"),
                ("legal_entity", "entity_b"),
            ):
                PostgresScopeAuthorityRepository(connection).grant(
                    tenant_id="ap_replay",
                    grant_id=f"{actor}-{identifier}",
                    principal_type="user",
                    principal_id=actor,
                    scope_type=kind,
                    scope_id=identifier,
                    actor_id=actor,
                )
    params = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(db["admin"])["dbname"]
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn=psycopg.conninfo.make_conninfo(**params),
        postgres_require_tls=False,
        secure_transport=True,
    )
    with TestClient(app, base_url="https://testserver") as client:
        headers = {}
        for actor in ("api-maker", "api-checker"):
            response = client.post(
                "/api/v1/auth/login",
                headers={"X-ReconForge-Tenant": "ap_replay"},
                json={"username": actor, "password": password},
            )
            assert response.status_code == 200, response.text
            headers[actor] = {
                "X-ReconForge-Tenant": "ap_replay",
                "X-ReconForge-Workspace": "shared",
                "X-ReconForge-Organization": "org_a",
                "X-ReconForge-Legal-Entity": "entity_a",
                "Authorization": "Bearer " + response.json()["access_token"],
            }
            assert (
                client.post("/api/v1/auth/step-up", headers=headers[actor], json={"password": password}).status_code
                == 200
            )
        maker, checker = headers["api-maker"], headers["api-checker"]
        po = {
            "po_number": "HTTP-PO",
            "supplier_code": "SUP",
            "order_date": "2026-07-28",
            "currency_code": "EGP",
            "lines": [{"item_code": "ITEM", "ordered_quantity": "10", "unit_price_minor": 1200}],
            "idempotency_key": "http-po",
        }
        response = client.post("/api/v1/payables/purchase-orders", headers=maker, json=po)
        assert response.status_code == 200, response.text
        order = response.json()
        assert (
            client.post(
                f"/api/v1/payables/purchase-orders/{order['id']}/submit", headers=maker, json={"expected_version": 1}
            ).status_code
            == 200
        )
        response = client.post(
            f"/api/v1/payables/purchase-orders/{order['id']}/approve", headers=checker, json={"expected_version": 2}
        )
        assert response.status_code == 200, response.text
        approved = response.json()
        replay = client.post("/api/v1/payables/purchase-orders", headers=maker, json=po)
        assert replay.status_code == 200 and replay.json() == approved, replay.text
        line_id = order["lines"][0]["id"]
        receipt = {
            "receipt_number": "HTTP-GR",
            "purchase_order_id": order["id"],
            "receipt_date": "2026-07-28",
            "quantities": {line_id: "2"},
            "idempotency_key": "http-gr",
        }
        invoice = {
            "invoice_number": "HTTP-INV",
            "supplier_code": "SUP",
            "invoice_date": "2026-07-28",
            "currency_code": "EGP",
            "total_minor": 2400,
            "purchase_order_id": order["id"],
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "invoiced_quantity": "2",
                    "unit_price_minor": 1200,
                    "line_total_minor": 2400,
                }
            ],
            "idempotency_key": "http-inv",
        }
        for route, payload in (("receipts", receipt), ("invoices", invoice)):
            first = client.post(f"/api/v1/payables/{route}", headers=maker, json=payload)
            assert first.status_code == 200, first.text
            replay = client.post(f"/api/v1/payables/{route}", headers=maker, json=payload)
            assert replay.status_code == 200 and replay.json() == first.json(), replay.text
        changed = client.post(
            "/api/v1/payables/receipts", headers=maker, json={**receipt, "quantities": {line_id: "3"}}
        )
        assert changed.status_code == 400, changed.text
        sibling = {**maker, "X-ReconForge-Organization": "org_b", "X-ReconForge-Legal-Entity": "entity_b"}
        for route, payload in (("purchase-orders", po), ("receipts", receipt), ("invoices", invoice)):
            denied = client.post(f"/api/v1/payables/{route}", headers=sibling, json=payload)
            assert denied.status_code == 400, denied.text
        expected_current = {"purchase-orders": approved, "invoices": first.json()}
        with psycopg.connect(db["admin"]) as admin:
            admin.execute("UPDATE reconforge.ap_suppliers SET status='Suspended' WHERE tenant_id='ap_replay' AND supplier_code='SUP'")
            before = tuple(admin.execute("SELECT (SELECT count(*) FROM reconforge.domain_audit_events WHERE object_type IN ('ap_purchase_order','ap_supplier_invoice','ap_goods_receipt')),(SELECT count(*) FROM reconforge.outbox_events)").fetchone())
        for route, payload, number in (("purchase-orders", po, "po_number"), ("invoices", invoice, "invoice_number")):
            replay = client.post(f"/api/v1/payables/{route}", headers=maker, json=payload)
            assert replay.status_code == 200 and replay.json() == expected_current[route], replay.text
            denied = client.post(f"/api/v1/payables/{route}", headers=maker, json={**payload, number: "FRESH-DOCUMENT", "idempotency_key": "fresh-document"})
            assert denied.status_code == 400, denied.text
        with psycopg.connect(db["admin"]) as admin:
            after = tuple(admin.execute("SELECT (SELECT count(*) FROM reconforge.domain_audit_events WHERE object_type IN ('ap_purchase_order','ap_supplier_invoice','ap_goods_receipt')),(SELECT count(*) FROM reconforge.outbox_events)").fetchone())
        assert after == before
