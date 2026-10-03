"""Real HTTP and nonowner SQL enforce the selected master-data authority."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes.master_data import _server_id
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_finance_scope import (
    _entry,
    _scope,
)
from tests.test_postgres_finance_scope import (
    finance_database as _finance_database,
)
from tests.test_postgres_finance_scope import (
    isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn,
)

finance_database = _finance_database
isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn
TENANT = "finance_scope"
ORG = _server_id("org", TENANT, "ORG_HTTP")
ENTITY = _server_id("entity", TENANT, ORG, "HTTP_A1")
PASSWORD = "Synthetic-authority-review-2026!"
NARROW_HEADERS = {"X-ReconForge-Tenant": TENANT, "X-ReconForge-Workspace": "shared", "X-ReconForge-Organization": ORG, "X-ReconForge-Legal-Entity": ENTITY}


@pytest.fixture
def authority_api(finance_database: Any, tmp_path: Path):
    import psycopg

    db = finance_database
    with db["boundary"].transaction(TENANT) as connection:
        connection.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,%s,'ORG_HTTP','Synthetic HTTP','EGP','shared')", (TENANT, ORG))
        for code in ("HTTP_A1", "HTTP_A2"):
            connection.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,%s,%s,%s,%s,'EGP')", (TENANT, _server_id("entity", TENANT, ORG, code), ORG, code, code))
        identity = PostgresIdentityRepository(connection)
        for permission in ("master_data.read", "master_data.manage"):
            identity.create_permission(tenant_id=TENANT, permission_name=permission)
        for user, permissions in (("manager", ("master_data.read", "master_data.manage")), ("reader", ("master_data.read",))):
            identity.create_role(tenant_id=TENANT, role_name=user)
            for permission in permissions:
                identity.grant_permission(tenant_id=TENANT, role_name=user, permission_name=permission)
            identity.create_user(tenant_id=TENANT, user_id=user, username=user, password=PASSWORD, role_name=user)
            for scope_type, scope_id in (("workspace", "shared"), ("organization", ORG), ("legal_entity", ENTITY)):
                PostgresScopeAuthorityRepository(connection).grant(tenant_id=TENANT, grant_id=f"{user}-{scope_type}", principal_type="user", principal_id=user, scope_type=scope_type, scope_id=scope_id, actor_id=user)
    params = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(db["admin"])["dbname"]
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tenant_root, postgres_dsn=psycopg.conninfo.make_conninfo(**params), postgres_require_tls=False, policy_cache_enabled=True)
    with TestClient(app) as client:
        headers = {}
        for user in ("manager", "reader"):
            login = client.post("/api/v1/auth/login", headers={"X-ReconForge-Tenant": TENANT}, json={"username": user, "password": PASSWORD})
            assert login.status_code == 200, login.text
            headers[user] = {**NARROW_HEADERS, "Authorization": f"Bearer {login.json()['access_token']}"}
        yield db, client, headers


def _persisted(db: Any) -> tuple[Any, ...]:
    import psycopg

    with psycopg.connect(db["admin"]) as connection:
        return tuple(connection.execute("""SELECT
          (SELECT active FROM reconforge.organizations WHERE tenant_id=%s AND id=%s),
          (SELECT active FROM reconforge.currencies WHERE tenant_id=%s AND code='EGP'),
          (SELECT status FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id='period'),
          (SELECT count(*) FROM reconforge.audit_events WHERE tenant_id=%s AND resource_type IN ('currency','organization','fiscal_period')),
          (SELECT count(*) FROM reconforge.outbox_events WHERE tenant_id=%s AND event_type LIKE 'master_data.%%')
        """, (TENANT, ORG, TENANT, TENANT, TENANT, TENANT)).fetchone())


@pytest.mark.parametrize("resource,entity", [("organizations", True), ("currencies", True), ("currencies", False), ("periods/period/status", True), ("periods/period/status", False)])
def test_live_http_shared_mutation_rejected_without_business_evidence(authority_api: Any, resource: str, entity: bool) -> None:
    db, client, headers = authority_api
    selected = dict(headers["manager"])
    if not entity:
        selected.pop("X-ReconForge-Legal-Entity")
    payload = {
        "organizations": {"organization_code": "ORG_HTTP", "name": "Denied shared edit", "base_currency": "EGP", "active": False},
        "currencies": {"code": "EGP", "name": "Denied shared edit", "minor_units": 2, "active": False},
        "periods/period/status": {"status": "Soft Closed", "reason": "Denied shared edit"},
    }[resource]
    before = _persisted(db)
    response = client.post(f"/api/v1/master-data/{resource}", headers=selected, json=payload)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "master_data_authority_denied"
    assert _persisted(db) == before


def test_live_http_authorized_controls_and_entity_local_update(authority_api: Any) -> None:
    db, client, headers = authority_api
    currency = {"code": "EGP", "name": "Synthetic", "minor_units": 2, "active": True}
    assert client.post("/api/v1/master-data/currencies", headers=headers["reader"], json=currency).status_code == 403
    sibling = {**headers["manager"], "X-ReconForge-Legal-Entity": _server_id("entity", TENANT, ORG, "HTTP_A2")}
    assert client.post("/api/v1/master-data/currencies", headers=sibling, json=currency).status_code == 403
    org_headers = {key: value for key, value in headers["manager"].items() if key != "X-ReconForge-Legal-Entity"}
    organization = client.post("/api/v1/master-data/organizations", headers=org_headers, json={"organization_code": "ORG_HTTP", "name": "Authorized org", "base_currency": "EGP", "active": True})
    assert organization.status_code == 200, organization.text
    workspace_headers = {key: value for key, value in org_headers.items() if key != "X-ReconForge-Organization"}
    assert client.post("/api/v1/master-data/currencies", headers=workspace_headers, json=currency).status_code == 200
    assert client.post("/api/v1/master-data/periods/period/status", headers=workspace_headers, json={"status": "Soft Closed", "reason": "Authorized workspace"}).status_code == 200
    entity = client.post("/api/v1/master-data/entities", headers=headers["manager"], json={"organization_code": "ORG_HTTP", "entity_code": "HTTP_A1", "name": "Authorized entity", "currency_code": "EGP"})
    assert entity.status_code == 200, entity.text
    assert entity.json()["entity"]["name"] == "Authorized entity"
    injected = client.post("/api/v1/master-data/currencies", headers=headers["manager"], json={**currency, "object_type": "master_data.entity", "action": "read"})
    assert injected.status_code == 422
    missing_workspace = {key: value for key, value in workspace_headers.items() if key != "X-ReconForge-Workspace"}
    assert client.post("/api/v1/master-data/currencies", headers=missing_workspace, json=currency).status_code == 400
    # Cached broader allowed decisions must not authorize the same actor's narrower mutation.
    denied = client.post("/api/v1/master-data/currencies", headers=headers["manager"], json={**currency, "active": False})
    assert denied.status_code == 403
    assert _persisted(db)[:3] == (True, True, "Soft Closed")


def test_live_sql_mutation_guard_preserves_scope_and_reference_locks(finance_database: Any) -> None:
    import psycopg

    db = finance_database
    statements = (
        "UPDATE reconforge.currencies SET name=name WHERE code='EGP'",
        "DELETE FROM reconforge.currencies WHERE code='EGP'",
        "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('finance_scope','USD','Synthetic',2)",
        "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('finance_scope','EGP','Synthetic',2) ON CONFLICT(tenant_id,code) DO UPDATE SET name=EXCLUDED.name",
        "UPDATE reconforge.organizations SET active=false WHERE id='org_a'",
        "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,application_workspace_id) VALUES('finance_scope','org_a','ORG_A','Synthetic','shared') ON CONFLICT(tenant_id,id) DO UPDATE SET name=EXCLUDED.name",
        "UPDATE reconforge.fiscal_periods SET status='Soft Closed' WHERE id='period'",
        "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES('finance_scope','newperiod','Synthetic','2027-01-01','2027-01-31',2027,1,'shared')",
    )
    with db["boundary"].transaction(TENANT, organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        before = _scope(connection)
        for statement in statements:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(statement)
            assert _scope(connection) == before
        assert connection.execute("SELECT id FROM reconforge.organizations WHERE id='org_a' FOR SHARE").fetchone() is not None
        assert connection.execute("SELECT id FROM reconforge.fiscal_periods WHERE id='period' FOR SHARE").fetchone() is not None
        finance = PostgresFinanceCoreRepository(connection, TENANT)
        draft = _entry(finance, "AUTHORITY-POSITIVE")
        assert finance.validate_entry(draft["id"], reason="Synthetic independent review", actor_label="checker")["status"] == "Validated"
        assert _scope(connection) == before
    with db["boundary"].transaction(TENANT) as connection:
        assert _scope(connection)[1:] == ("", "", "", "")
        repository = PostgresMasterDataRepository(connection)
        assert repository.upsert_currency(tenant_id=TENANT, code="USD", name="Tenant setup", minor_units=2)["code"] == "USD"
        # Unreferenced parents prove DELETE is denied by the new authority guard,
        # independently of the existing Finance history/FK deletion protections.
        connection.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,application_workspace_id) VALUES('finance_scope','org-delete','ORG_DELETE','Synthetic','shared')")
        connection.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES('finance_scope','entity-delete','org-delete','DELETE','Synthetic','EGP')")
        connection.execute("INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES('finance_scope','period-delete','Delete synthetic','2028-01-01','2028-01-31',2028,1,'shared')")
    with db["boundary"].transaction(TENANT, organization_id="org-delete", workspace_id="shared", legal_entity_id="entity-delete") as connection:
        for statement in ("DELETE FROM reconforge.organizations WHERE id='org-delete'", "DELETE FROM reconforge.fiscal_periods WHERE id='period-delete'", "DELETE FROM reconforge.currencies WHERE code='USD'"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="selected authority"), connection.transaction():
                connection.execute(statement)


def test_live_sql_org_selection_blocks_shared_currency_and_period_but_allows_organization(finance_database: Any) -> None:
    import psycopg

    with finance_database["boundary"].transaction(TENANT, organization_id="org_a", workspace_id="shared") as connection:
        assert connection.execute("UPDATE reconforge.organizations SET name=name WHERE id='org_a'").rowcount == 1
        for table in ("currencies", "fiscal_periods"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(psycopg.sql.SQL("UPDATE reconforge.{} SET name=name").format(psycopg.sql.Identifier(table)))
    with finance_database["boundary"].transaction(TENANT, workspace_id="shared") as connection:
        assert connection.execute("UPDATE reconforge.currencies SET name=name").rowcount == 1
        assert connection.execute("UPDATE reconforge.fiscal_periods SET name=name WHERE id='period'").rowcount == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT set_config('app.entity_id','entity_a1',true)")
            connection.execute("UPDATE reconforge.organizations SET name=name WHERE id='org_a'")


def test_live_authority_migration_downgrade_reupgrade_preserves_rows(finance_database: Any) -> None:
    import psycopg

    from alembic import command

    db = finance_database
    command.downgrade(db["config"], "0095_pg_finance_scope")
    with db["boundary"].transaction(TENANT, organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        assert connection.execute("UPDATE reconforge.organizations SET name=name WHERE id='org_a'").rowcount == 1
    command.upgrade(db["config"], "head")
    with db["boundary"].transaction(TENANT, organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        assert connection.execute("SELECT count(*) FROM reconforge.finance_entries").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("UPDATE reconforge.organizations SET name=name WHERE id='org_a'")


@pytest.mark.parametrize("installer", ["master", "finance"])
def test_live_current_installer_restores_authority_without_migration_head(finance_database: Any, installer: str) -> None:
    import psycopg

    from alembic import command
    from reconforge.infrastructure.postgres_finance_core import install_postgres_finance_core_schema
    from reconforge.infrastructure.postgres_master_data_application import (
        install_postgres_master_data_application_schema,
    )

    db = finance_database
    command.downgrade(db["config"], "0095_pg_finance_scope")
    with psycopg.connect(db["admin"]) as admin:
        (install_postgres_master_data_application_schema if installer == "master" else install_postgres_finance_core_schema)(admin)
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0095_pg_finance_scope"
    with db["boundary"].transaction(TENANT, organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
        assert connection.execute("SELECT id FROM reconforge.organizations WHERE id='org_a' FOR SHARE").fetchone() is not None
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("UPDATE reconforge.organizations SET name=name WHERE id='org_a'")


def test_master_authority_migration_is_frozen() -> None:
    from reconforge.infrastructure.postgres_master_data_authority import POSTGRES_MASTER_DATA_AUTHORITY_SCHEMA_SQL

    path = Path("alembic/versions/0096_postgres_master_data_authority.py")
    spec = importlib.util.spec_from_file_location("master_authority_revision", path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.UPGRADE_SQL == POSTGRES_MASTER_DATA_AUTHORITY_SCHEMA_SQL
    assert revision.down_revision == "0095_pg_finance_scope"
