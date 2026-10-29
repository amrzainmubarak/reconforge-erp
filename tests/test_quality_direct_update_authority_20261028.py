"""Native regression for direct NCR disposition authority.

These cases require a separately provisioned synthetic PostgreSQL database.
The fixture leaves its synthetic records intact for migration/restore review.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_manufacturing_quality import PostgresManufacturingQualityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN") or not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="Requires separately provisioned synthetic PostgreSQL; AMR-QUALITY-ENTITY-SOURCE-20261027; review 2026-11-28",
)
BASE = "/api/v1/manufacturing/quality"


@pytest.fixture
def scoped_quality(tmp_path: Path):
    admin_dsn = os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"]
    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    runtime = create_receipt_runtime((admin_dsn, app_dsn))
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert tuple(flags) == (False, False)
        flags = connection.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='reconforge.quality_ncrs'::regclass").fetchone()
        assert tuple(flags) == (True, True)
        connection.execute(
            "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) "
            "VALUES(%s,'entity-b','org','ENTITY-B','Synthetic B','USD')", (runtime.tenant,),
        )
        identity = PostgresIdentityRepository(connection)
        identity.create_role(tenant_id=runtime.tenant, role_name="quality-entity-scope")
        for permission in ("manufacturing_execution.read", "manufacturing_execution.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="quality-entity-scope", permission_name=permission)
        authority = PostgresScopeAuthorityRepository(connection)
        for user, entity in (("maker-a", "entity"), ("reviewer-a", "entity"), ("reviewer-b", "entity-b")):
            identity.create_user(tenant_id=runtime.tenant, user_id=user, username=user, password=runtime.password, role_name="quality-entity-scope")
            for kind, scope_id in (("workspace", "work"), ("organization", "org"), ("legal_entity", entity)):
                authority.grant(tenant_id=runtime.tenant, grant_id=user + kind, principal_type="user", principal_id=user,
                                scope_type=kind, scope_id=scope_id, actor_id="maker")
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=app_dsn,
                         postgres_require_tls=False, secure_transport=True)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        base = {"X-ReconForge-Tenant": runtime.tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org"}
        def login(user: str, entity: str) -> dict[str, str]:
            scope = {**base, "X-ReconForge-Legal-Entity": entity}
            response = client.post("/api/v1/auth/login", headers=scope, json={"username": user, "password": runtime.password})
            assert response.status_code == 200
            headers = {**scope, "Authorization": "Bearer " + response.json()["access_token"]}
            assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
            return headers
        yield runtime, client, login("maker-a", "entity"), login("reviewer-a", "entity"), login("reviewer-b", "entity-b")


def _ncr() -> dict[str, object]:
    return {"ncr_id": "NCR-A", "lot_id": "LOT-A", "work_order_id": "WO-A", "defect_code": "DEFECT",
            "defect_severity": "major", "inspector_id": "maker-a", "quarantined_quantity_scaled": 1000}


def test_direct_repository_update_cannot_bypass_independent_disposition(scoped_quality) -> None:
    runtime, client, maker_a, reviewer_a, _ = scoped_quality
    assert client.post(BASE + "/ncrs", headers=maker_a, json=_ncr()).status_code == 200
    with PostgresTenantBoundary(runtime.factory).transaction(
        runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        repo = PostgresManufacturingQualityRepository(connection, runtime.tenant)
        original = repo.get_ncr("work", "NCR-A")
        assert original is not None
        forged = original.disposition_ncr(disposition="rework", notes="Self approval attempt", actor="maker-a")
        with pytest.raises((PermissionError, ValueError)):
            repo.update_ncr("work", forged)
        assert repo.get_ncr("work", "NCR-A") == original
    assert client.post(BASE + "/ncrs/NCR-A/disposition", headers=reviewer_a,
                       json={"disposition": "rework", "notes": "Independent reviewer"}).status_code == 200
    with PostgresTenantBoundary(runtime.factory).transaction(
        runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        repo = PostgresManufacturingQualityRepository(connection, runtime.tenant)
        approved = repo.get_ncr("work", "NCR-A")
        assert approved is not None
        repo.update_ncr("work", approved)  # Exact decision replay remains valid.
        with pytest.raises((PermissionError, ValueError)):
            repo.update_ncr("other-workspace", approved)
        with pytest.raises((PermissionError, ValueError)):
            repo.update_ncr("work", replace(approved, disposition_notes="Forged after approval"))
        assert repo.get_ncr("work", "NCR-A") == approved
        counts = connection.execute(
            "SELECT count(*) FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NCR-A' AND authority_kind='reviewer'"
        ).fetchone()
        assert counts[0] == 1

    with PostgresTenantBoundary(runtime.factory).transaction(
        runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        connection.execute("SET LOCAL TIME ZONE 'Africa/Cairo'")
        repo = PostgresManufacturingQualityRepository(connection, runtime.tenant)
        cairo = repo.get_ncr("work", "NCR-A")
        assert cairo is not None
        assert approved.disposition_at is not None and cairo.disposition_at is not None
        assert approved.disposition_at != cairo.disposition_at
        assert datetime.fromisoformat(approved.disposition_at) == datetime.fromisoformat(cairo.disposition_at)
        before_xmin = connection.execute("SELECT xmin::text FROM reconforge.quality_ncrs WHERE ncr_id='NCR-A'").fetchone()[0]
        repo.update_ncr("work", approved)
        after_xmin = connection.execute("SELECT xmin::text FROM reconforge.quality_ncrs WHERE ncr_id='NCR-A'").fetchone()[0]
        assert before_xmin == after_xmin
        assert repo.get_ncr("work", "NCR-A") == cairo
        for tampered in (
            replace(cairo, ncr_id="OTHER"),
            replace(cairo, lot_id="OTHER-LOT"),
            replace(cairo, work_order_id="OTHER-WO"),
            replace(cairo, defect_code="OTHER-DEFECT"),
            replace(cairo, defect_severity="critical"),
            replace(cairo, inspector_id="other-inspector"),
            replace(cairo, disposition_notes="Tampered in Cairo"),
            replace(cairo, quarantined_quantity_scaled=cairo.quarantined_quantity_scaled + 1),
            replace(cairo, status="closed"),
            replace(cairo, disposition="scrap"),
            replace(cairo, disposition_by="other-reviewer"),
            replace(cairo, created_at="2026-01-01T00:00:00+00:00"),
            replace(cairo, disposition_at="2026-01-01T00:00:00+00:00"),
        ):
            with pytest.raises((PermissionError, ValueError)):
                repo.update_ncr("work", tampered)
        counts = connection.execute(
            "SELECT count(*) FROM reconforge.domain_audit_events WHERE object_type='quality.ncr' "
            "AND object_id='NCR-A' AND action='quality_ncr_dispositioned'"
        ).fetchone()
        assert counts[0] == 1


def test_old_decision_cannot_reverse_a_later_persisted_state(scoped_quality) -> None:
    runtime, client, maker_a, reviewer_a, _ = scoped_quality
    assert client.post(BASE + "/ncrs", headers=maker_a, json=_ncr()).status_code == 200
    assert client.post(BASE + "/ncrs/NCR-A/disposition", headers=reviewer_a,
                       json={"disposition": "rework", "notes": "Independent reviewer"}).status_code == 200
    with PostgresTenantBoundary(runtime.factory).transaction(
        runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        repo = PostgresManufacturingQualityRepository(connection, runtime.tenant)
        approved = repo.get_ncr("work", "NCR-A")
        assert approved is not None
        # Model a later state directly, without claiming a public close workflow.
        connection.execute("UPDATE reconforge.quality_ncrs SET status='closed' WHERE ncr_id='NCR-A'")
        later = repo.get_ncr("work", "NCR-A")
        assert later is not None and later.status == "closed"
        with pytest.raises((PermissionError, ValueError)):
            repo.update_ncr("work", approved)
        assert repo.get_ncr("work", "NCR-A") == later


def test_disposition_update_failure_rolls_back_reviewer_and_audit(scoped_quality, monkeypatch) -> None:
    runtime, client, maker_a, reviewer_a, _ = scoped_quality
    assert client.post(BASE + "/ncrs", headers=maker_a, json=_ncr()).status_code == 200

    def fail_update(*_args, **_kwargs):
        raise RuntimeError("Synthetic failure after reviewer evidence is staged")

    with monkeypatch.context() as fault:
        fault.setattr(PostgresManufacturingQualityRepository, "update_ncr", fail_update)
        failed = client.post(BASE + "/ncrs/NCR-A/disposition", headers=reviewer_a,
                             json={"disposition": "rework", "notes": "Independent reviewer"})
    assert failed.status_code == 500
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        row = connection.execute("SELECT status,disposition FROM reconforge.quality_ncrs WHERE ncr_id='NCR-A'").fetchone()
        assert tuple(row) == ("open", None)
        assert connection.execute("SELECT count(*) FROM reconforge.quality_ncr_actor_authorities WHERE ncr_id='NCR-A' AND authority_kind='reviewer'").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reconforge.domain_audit_events WHERE object_type='quality.ncr' AND object_id='NCR-A' AND action='quality_ncr_dispositioned'").fetchone()[0] == 0
    retried = client.post(BASE + "/ncrs/NCR-A/disposition", headers=reviewer_a,
                          json={"disposition": "rework", "notes": "Independent reviewer"})
    assert retried.status_code == 200
