"""Independent persisted human identity for advisory NCR disposition; no stock claim."""
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.domain.manufacturing_quality_rework import NonConformanceReport
from reconforge.infrastructure.sqlite_manufacturing_quality import SqliteManufacturingQualityRepository
from tests.test_postgres_inventory_receipt_posting import receipt_database  # noqa: F401

PASSWORD = "Synthetic-Quality-Authority-2026!"
BASE = "/api/v1/manufacturing/quality/ncrs"


def _payload(identifier: str, inspector: str) -> dict[str, object]:
    return {"ncr_id": identifier, "lot_id": "SYNTHETIC-LOT", "work_order_id": "SYNTHETIC-WO",
            "defect_code": "SYNTHETIC-DEFECT", "defect_severity": "major", "inspector_id": inspector,
            "quarantined_quantity_scaled": 1000}


@pytest.fixture
def local_quality(tmp_path: Path):
    path = tmp_path / "quality.sqlite"
    run_migrations(path)
    with connect(path) as connection:
        auth = LocalAuthService(connection)
        creator = auth.init_admin(username="original-inspector", password=PASSWORD)
        reviewer = auth.create_user(username="independent-reviewer", password=PASSWORD, role="admin")
        role = connection.execute("SELECT id FROM roles WHERE name='admin'").fetchone()[0]
        for permission in ("manufacturing_execution.read", "manufacturing_execution.manage"):
            connection.execute("INSERT OR IGNORE INTO permissions(name,description) VALUES(?,?)", (permission, "Synthetic quality authority grant"))
            connection.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_name) VALUES(?,?)", (role, permission))
        connection.commit()
        SqliteManufacturingQualityRepository(connection).create_ncr("default", NonConformanceReport(
            "LEGACY", "SYNTHETIC-LOT", "SYNTHETIC-WO", "SYNTHETIC-DEFECT", "major", creator.username, 1000,
        ))
    with TestClient(create_api_app(path), raise_server_exceptions=False) as client:
        def login(username: str) -> dict[str, str]:
            response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
            assert response.status_code == 200, response.text
            return {"Authorization": "Bearer " + response.json()["access_token"]}
        yield path, client, creator, reviewer, login


def test_author_rename_does_not_enable_self_disposition_or_legacy_claim(local_quality) -> None:
    path, client, creator, _reviewer, login = local_quality
    maker = login(creator.username)
    for identifier in ("NCR-STABLE", "NCR-ALIAS"):
        created = client.post(BASE, headers=maker, json=_payload(identifier, creator.username))
        assert created.status_code == 200, created.text
        assert created.json()["status"] == "recorded" and created.json()["inventory_effect"] == "not_posted"
    with connect(path) as connection:
        connection.execute("UPDATE users SET username='renamed-inspector' WHERE id=?", (creator.id,))
        connection.commit()
        alias = LocalAuthService(connection).create_user(username=creator.username, password=PASSWORD, role="admin")
        assert alias.id != creator.id
    disposition = {"disposition": "rework", "notes": "Independent synthetic disposition"}
    denied = client.post(BASE + "/NCR-STABLE/disposition", headers=maker, json=disposition)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "quality_self_disposition_denied"
    legacy = client.post(BASE + "/LEGACY/disposition", headers=login("independent-reviewer"), json=disposition)
    assert legacy.status_code == 403, legacy.text
    assert legacy.json()["error"]["code"] == "quality_actor_authority_missing"
    accepted = client.post(BASE + "/NCR-STABLE/disposition", headers=login("independent-reviewer"), json=disposition)
    assert accepted.status_code == 200 and accepted.json()["inventory_effect"] == "not_posted", accepted.text
    assert accepted.json()["disposition_by_user_id"] == _reviewer.id
    alias_review = client.post(BASE + "/NCR-ALIAS/disposition", headers=login(creator.username), json=disposition)
    assert alias_review.status_code == 200, alias_review.text
    with connect(path) as connection:
        assert [tuple(row) for row in connection.execute("SELECT ncr_id,quarantined_quantity_scaled FROM quality_ncrs ORDER BY ncr_id")] == [
            ("LEGACY", 1000), ("NCR-ALIAS", 1000), ("NCR-STABLE", 1000),
        ]


def test_forged_inspector_cannot_create_quality_source(local_quality) -> None:
    path, client, creator, reviewer, login = local_quality
    refused = client.post(BASE, headers=login(creator.username), json=_payload("FORGED", reviewer.id))
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "inspector_identity_denied"
    with connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM quality_ncrs WHERE ncr_id='FORGED'").fetchone()[0] == 0


def test_concurrent_rework_allocations_cannot_consume_one_recorded_quantity_twice(local_quality) -> None:
    path, client, creator, reviewer, login = local_quality
    created = client.post(BASE, headers=login(creator.username), json=_payload("NCR-QUANTITY", creator.username))
    assert created.status_code == 200, created.text
    headers = login(reviewer.username)
    reviewed = client.post(BASE + "/NCR-QUANTITY/disposition", headers=headers,
                           json={"disposition": "rework", "notes": "Independent synthetic quantity review"})
    assert reviewed.status_code == 200, reviewed.text

    def allocate(identifier: str):
        return client.post("/api/v1/manufacturing/quality/rework-orders", headers=headers, json={
            "rework_order_id": identifier, "parent_work_order_id": "SYNTHETIC-WO", "ncr_id": "NCR-QUANTITY",
            "item_id": "SYNTHETIC-ITEM", "rework_quantity_scaled": 600, "rework_cost_center": "SYNTHETIC-COST",
            "rework_routing_steps": [{"step_number": 1, "work_center_id": "SYNTHETIC-CENTER",
                                       "operation_description": "Synthetic advisory rework", "estimated_minutes": 1}],
        })
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(allocate, ("REWORK-A", "REWORK-B")))
    assert sorted(response.status_code for response in responses) == [200, 409], [response.text for response in responses]
    refused = next(response for response in responses if response.status_code == 409)
    assert refused.json()["error"]["code"] == "rework_quantity_exceeded"
    with connect(path) as connection:
        assert connection.execute("SELECT sum(rework_quantity_scaled),count(*) FROM quality_rework_orders WHERE ncr_id='NCR-QUANTITY'").fetchone()[:] == (600, 1)


def test_creation_authority_failure_rolls_back_business_and_audit_then_safe_retry(local_quality) -> None:
    path, client, creator, _reviewer, login = local_quality
    with connect(path) as connection:
        connection.execute("""CREATE TRIGGER injected_quality_authority_failure BEFORE INSERT ON quality_ncr_actor_authorities
        WHEN NEW.ncr_id='ROLLBACK' BEGIN SELECT RAISE(ABORT,'Synthetic authority persistence failure'); END""")
        connection.commit()
    headers = login(creator.username)
    payload = _payload("ROLLBACK", creator.username)
    failed = client.post(BASE, headers=headers, json=payload)
    assert failed.status_code == 500, failed.text
    with connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM quality_ncrs WHERE ncr_id='ROLLBACK'").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM quality_ncr_actor_authorities WHERE ncr_id='ROLLBACK'").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM audit_events WHERE object_type='quality.ncr' AND object_id='ROLLBACK'").fetchone()[0] == 0
        connection.execute("DROP TRIGGER injected_quality_authority_failure")
        connection.commit()
    retried = client.post(BASE, headers=headers, json=payload)
    assert retried.status_code == 200, retried.text
    duplicate = client.post(BASE, headers=headers, json={**payload, "quarantined_quantity_scaled": 9000})
    assert duplicate.status_code == 409, duplicate.text
    with connect(path) as connection:
        assert connection.execute("SELECT quarantined_quantity_scaled FROM quality_ncrs WHERE ncr_id='ROLLBACK'").fetchone()[0] == 1000
        row = connection.execute("SELECT user_id,authority_kind FROM quality_ncr_actor_authorities WHERE ncr_id='ROLLBACK'").fetchone()
        assert tuple(row) == (creator.id, "creator")
        for statement in (
            "UPDATE quality_ncr_actor_authorities SET user_id='forged' WHERE ncr_id='ROLLBACK'",
            "DELETE FROM quality_ncr_actor_authorities WHERE ncr_id='ROLLBACK'",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(statement)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
                    reason="Owned native PostgreSQL required for quality authority; review2026-10-26")
def test_native_quality_identity_rename_scope_and_immutable_authority(receipt_database, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    import psycopg

    from reconforge.infrastructure.postgres import PostgresTenantBoundary
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
    from reconforge.infrastructure.postgres_manufacturing_quality import PostgresManufacturingQualityRepository
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
    from tests.test_postgres_enterprise_migrations import migrate
    from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime

    runtime = create_receipt_runtime(receipt_database)
    empty = migrate(runtime.admin_dsn, "downgrade", "0156_pg_hcm_leave_entity")
    assert empty.returncode == 0, empty.stderr
    upgraded = migrate(runtime.admin_dsn, "upgrade", "0157_pg_quality_actor_authority")
    assert upgraded.returncode == 0, upgraded.stderr
    from psycopg import sql
    app_user = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    with psycopg.connect(runtime.admin_dsn) as connection:
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.quality_ncr_actor_authorities TO {}").format(sql.Identifier(app_user)))
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("manufacturing_execution.read", "manufacturing_execution.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        for identifier, username in (("qa-creator-id", "qa-original-name"), ("qa-reviewer-id", "qa-reviewer-name")):
            identity.create_user(tenant_id=runtime.tenant, user_id=identifier, username=username,
                                 password=runtime.password, role_name="receipt-operator")
            for kind, scope_id in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                PostgresScopeAuthorityRepository(connection).grant(
                    tenant_id=runtime.tenant, grant_id=identifier + kind, principal_type="user", principal_id=identifier,
                    scope_type=kind, scope_id=scope_id, actor_id="maker",
                )
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants",
                         postgres_dsn=receipt_database[1], postgres_require_tls=False, secure_transport=True)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        scope = {"X-ReconForge-Tenant": runtime.tenant, "X-ReconForge-Workspace": "work",
                 "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity"}
        def login(username: str):
            result = client.post("/api/v1/auth/login", headers=scope, json={"username": username, "password": runtime.password})
            assert result.status_code == 200, result.text
            headers = {**scope, "Authorization": "Bearer " + result.json()["access_token"]}
            assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
            return headers
        maker = login("qa-original-name")
        created = client.post(BASE, headers=maker, json=_payload("NATIVE-NCR", "qa-creator-id"))
        assert created.status_code == 200 and created.json()["inventory_effect"] == "not_posted", created.text
        with psycopg.connect(runtime.admin_dsn) as connection:
            connection.execute("UPDATE reconforge.identity_users SET username='qa-renamed' WHERE tenant_id=%s AND id='qa-creator-id'", (runtime.tenant,))
        decision = {"disposition": "rework", "notes": "Independent native source review"}
        denied = client.post(BASE + "/NATIVE-NCR/disposition", headers=maker, json=decision)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "quality_self_disposition_denied", denied.text
        actual_append = PostgresManufacturingQualityRepository._append_authority
        def injected_append(repository, workspace, ncr, kind, user_id, label):
            actual_append(repository, workspace, ncr, kind, user_id, label)
            if ncr.ncr_id == "NATIVE-ROLLBACK":
                raise RuntimeError("Synthetic failure after actual native authority and audit writes")
        with monkeypatch.context() as fault:
            fault.setattr(PostgresManufacturingQualityRepository, "_append_authority", injected_append)
            failed = client.post(BASE, headers=maker, json=_payload("NATIVE-ROLLBACK", "qa-creator-id"))
        assert failed.status_code == 500, failed.text
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.quality_ncrs WHERE ncr_id='NATIVE-ROLLBACK'").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NATIVE-ROLLBACK'").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.domain_audit_events WHERE object_type='quality.ncr' AND object_id='NATIVE-ROLLBACK'").fetchone()[0] == 0
        retried = client.post(BASE, headers=maker, json=_payload("NATIVE-ROLLBACK", "qa-creator-id"))
        assert retried.status_code == 200, retried.text
        reviewer_headers = login("qa-reviewer-name")
        reviewed = client.post(BASE + "/NATIVE-NCR/disposition", headers=reviewer_headers, json=decision)
        assert reviewed.status_code == 200 and reviewed.json()["disposition_by_user_id"] == "qa-reviewer-id", reviewed.text
        def allocate(identifier: str):
            return client.post("/api/v1/manufacturing/quality/rework-orders", headers=reviewer_headers, json={
                "rework_order_id": identifier, "parent_work_order_id": "SYNTHETIC-WO", "ncr_id": "NATIVE-NCR",
                "item_id": "SYNTHETIC-ITEM", "rework_quantity_scaled": 600, "rework_cost_center": "SYNTHETIC-COST",
                "rework_routing_steps": [{"step_number": 1, "work_center_id": "SYNTHETIC-CENTER",
                                           "operation_description": "Native advisory allocation", "estimated_minutes": 1}],
            })
        with ThreadPoolExecutor(max_workers=2) as pool:
            allocations = list(pool.map(allocate, ("NATIVE-REWORK-A", "NATIVE-REWORK-B")))
        assert sorted(value.status_code for value in allocations) == [200, 409], [value.text for value in allocations]
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        assert tuple(connection.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='reconforge.quality_ncr_actor_authorities'::regclass").fetchone()) == (True, True)
        before = [tuple(row) for row in connection.execute("SELECT authority_kind,user_id FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NATIVE-NCR' ORDER BY authority_kind").fetchall()]
        assert before == [("creator", "qa-creator-id"), ("reviewer", "qa-reviewer-id")]
        assert connection.execute("SELECT quarantined_quantity_scaled FROM reconforge.quality_ncrs WHERE ncr_id='NATIVE-NCR'").fetchone()[0] == 1000
        assert tuple(connection.execute("SELECT sum(rework_quantity_scaled),count(*) FROM reconforge.quality_rework_orders WHERE ncr_id='NATIVE-NCR'").fetchone()) == (600, 1)
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 0
        for statement in ("UPDATE reconforge.quality_ncr_actor_authorities SET user_id='poster' WHERE ncr_id='NATIVE-NCR'",
                          "DELETE FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NATIVE-NCR'"):
            with pytest.raises(psycopg.Error, match="immutable"), connection.transaction():
                connection.execute(statement)
        assert [tuple(row) for row in connection.execute("SELECT authority_kind,user_id FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NATIVE-NCR' ORDER BY authority_kind").fetchall()] == before
    for tenant, workspace in ((runtime.tenant, "sibling"), ("foreign-tenant", "work")):
        with PostgresTenantBoundary(runtime.factory).transaction(tenant, workspace_id=workspace) as connection:
            assert connection.execute("SELECT ncr_id FROM reconforge.quality_ncr_actor_authorities").fetchall() == []
    refused = migrate(runtime.admin_dsn, "downgrade", "0156_pg_hcm_leave_entity")
    assert refused.returncode != 0 and "Populated NCR authority prevents downgrade" in refused.stderr
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        assert [tuple(row) for row in connection.execute("SELECT authority_kind,user_id FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NATIVE-NCR' ORDER BY authority_kind").fetchall()] == before
