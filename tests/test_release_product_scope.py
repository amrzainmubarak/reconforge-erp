"""Authorized native artifact requests must retain the selected workspace boundary."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.intercompany_elimination import IntercompanyEliminationApplicationService
from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_crm_contracts import PostgresCRMContractsRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_intercompany_elimination import (
    PostgresIntercompanyEliminationError,
    PostgresIntercompanyEliminationRepository,
)
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_enterprise_finance_bridge import BridgeRuntime, bridge_runtime, source  # noqa: F401
from tests.test_postgres_intercompany_elimination_runtime import _lines
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime, receipt_database  # noqa: F401
from tests.test_postgres_people_project_payroll import people, personnel_database  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"), reason="P1 release product workspace gate requires disposable native PostgreSQL; review2026-10-25")


def test_native_authorized_role_cannot_read_or_persist_sibling_workspace_artifact(receipt_database: tuple[str, str], tmp_path: Path) -> None:  # noqa: F811
    runtime = create_receipt_runtime(receipt_database)
    ids: dict[str, str] = {}
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        connection.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,'sibling','Synthetic sibling')", (runtime.tenant,))
        identity = PostgresIdentityRepository(connection)
        for permission in ("finance_core.read", "finance_core.manage", "sales.manage", "sales.approve"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        identity.create_user(tenant_id=runtime.tenant, user_id="source-human-id", username="source-human-name", password=runtime.password, role_name="receipt-operator")
        identity.create_user(tenant_id=runtime.tenant, user_id="source-reviewer-id", username="source-reviewer-name", password=runtime.password, role_name="receipt-operator")
        identity.create_user(tenant_id=runtime.tenant, user_id="collision-author-id", username="source-reviewer-id", password=runtime.password, role_name="receipt-operator")
        PostgresScopeAuthorityRepository(connection).grant(tenant_id=runtime.tenant, grant_id="source-work", principal_type="user", principal_id="maker", scope_type="workspace", scope_id="work", actor_id="maker")
        PostgresScopeAuthorityRepository(connection).grant(tenant_id=runtime.tenant, grant_id="source-human-work", principal_type="user", principal_id="source-human-id", scope_type="workspace", scope_id="work", actor_id="maker")
        PostgresScopeAuthorityRepository(connection).grant(tenant_id=runtime.tenant, grant_id="source-reviewer-work", principal_type="user", principal_id="source-reviewer-id", scope_type="workspace", scope_id="work", actor_id="maker")
        PostgresScopeAuthorityRepository(connection).grant(tenant_id=runtime.tenant, grant_id="collision-author-work", principal_type="user", principal_id="collision-author-id", scope_type="workspace", scope_id="work", actor_id="maker")
        service = IntercompanyEliminationApplicationService(PostgresIntercompanyEliminationRepository(connection, runtime.tenant))
        for workspace, suffix in (("work", "1"), ("sibling", "2")):
            result = service.prepare_and_persist(_lines(suffix), reporting_currency="USD", prepared_by="maker", prepared_at="2026-10-25T00:00:00Z", version="1.0.0", workspace=workspace, actor_label="maker")
            ids[workspace] = str(result["id"])
        # The original API passed a username into a stable identity FK. Prove
        # that exact caller shape is refused without retaining an artifact.
        with pytest.raises(PostgresIntercompanyEliminationError, match="persistence failed"):
            service.prepare_and_persist(_lines("5"), reporting_currency="USD", prepared_by="source-human-name", prepared_at="2026-10-25T00:00:00Z", version="1.0.0", workspace="work", actor_label="source-human-name")
        assert connection.execute("SELECT count(*) FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 2
    with PostgresTenantBoundary(runtime.factory).transaction(
        runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        crm = PostgresCRMContractsRepository(connection, runtime.tenant)
        for quote_id, original_author in (("Q-LEGACY-NAME", "source-human-name"), ("Q-LEGACY-ID-COLLISION", "source-reviewer-id")):
            crm.save_quotation(CustomerQuotation(quote_id, "OP-SOURCE", "work", "CUSTOMER", "USD", "2026-12-31", original_author, "draft", (QuotationLineItem(1, "SERVICE", "Synthetic legacy service", 1, 1001),)))
    with runtime.actor("maker") as (connection, _repository, _actor):
        repository = PostgresIntercompanyEliminationRepository(connection, runtime.tenant)
        assert repository.get(ids["work"], actor_label="maker")["workspace_id"] == "work"
        with pytest.raises(PostgresIntercompanyEliminationError, match="not found"):
            repository.get(ids["sibling"], actor_label="maker")
        with pytest.raises(PostgresIntercompanyEliminationError, match="authority is denied"):
            repository.list_elimination_runs("sibling", actor_label="maker")
        service = IntercompanyEliminationApplicationService(repository)
        with pytest.raises(PostgresIntercompanyEliminationError, match="authority is denied"):
            service.prepare_and_persist(_lines("3"), reporting_currency="USD", prepared_by="maker", prepared_at="2026-10-25T00:00:00Z", version="1.0.0", workspace="sibling", actor_label="maker")
        assert connection.execute("SELECT current_setting('app.workspace_id',true)").fetchone()[0] == "work"
        assert len(repository.list_elimination_runs("work", actor_label="maker")) == 1
    application = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=receipt_database[1], postgres_require_tls=False)
    client = TestClient(application)
    tenant_headers = {"X-ReconForge-Tenant": runtime.tenant}
    login = client.post("/api/v1/auth/login", headers=tenant_headers, json={"username": "source-human-name", "password": runtime.password})
    assert login.status_code == 200, login.text
    headers = {**tenant_headers, "X-ReconForge-Workspace": "work", "Authorization": "Bearer " + login.json()["access_token"]}
    step_up = client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password})
    assert step_up.status_code == 200, step_up.text
    own = client.get("/api/v1/intercompany/eliminations/runs/" + ids["work"], headers=headers)
    assert own.status_code == 200, own.text
    assert own.json()["workspace_id"] == "work"
    denied = client.get("/api/v1/intercompany/eliminations/runs/" + ids["sibling"], headers=headers)
    assert denied.status_code == 404
    listed = client.get("/api/v1/intercompany/eliminations/runs", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["runs"]] == [ids["work"]]
    lines: list[dict[str, Any]] = []
    for line in _lines("4"):
        serialized = line.to_dict()
        amount = serialized["amount"]
        assert isinstance(amount, dict)
        serialized["amount"] = {key: amount[key] for key in ("amount", "currency", "minor_units", "rounding_policy")}
        lines.append(serialized)
    created = client.post("/api/v1/intercompany/eliminations/propose", headers=headers, json={"reporting_currency": "USD", "lines": lines})
    assert created.status_code == 200, created.text
    loaded = client.get("/api/v1/intercompany/eliminations/runs/" + created.json()["run_id"], headers=headers)
    assert loaded.status_code == 200, loaded.text
    assert len(loaded.json()["request_payload"]["lines"]) == 2
    assert loaded.json()["prepared_by"] == "source-human-id"
    quote_path = "/api/v1/crm/contracts/quotations"
    quotation = client.post(quote_path, headers=headers, json={"quote_id": "Q-STABLE-ID", "opportunity_id": "OP-SOURCE", "customer_id": "CUSTOMER", "currency": "USD", "valid_until": "2026-12-31", "lines": [{"line_number": 1, "item_id": "SERVICE", "description": "Synthetic service", "quantity": 1, "unit_price_minor": 1001}]})
    assert quotation.status_code == 200, quotation.text
    assert client.get(quote_path + "/Q-STABLE-ID", headers=headers).json()["submitter_user_id"] == "source-human-id"
    import psycopg
    with psycopg.connect(receipt_database[0]) as admin:
        admin.execute("UPDATE reconforge.identity_users SET username='source-human-renamed' WHERE tenant_id=%s AND id='source-human-id'", (runtime.tenant,))
        admin.execute("UPDATE reconforge.identity_users SET username='collision-renamed' WHERE tenant_id=%s AND id='collision-author-id'", (runtime.tenant,))
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        PostgresIdentityRepository(connection).create_user(tenant_id=runtime.tenant, user_id="username-reuse-id", username="source-human-name", password=runtime.password, role_name="receipt-operator")
    refused = client.post(quote_path + "/Q-STABLE-ID/approve", headers=headers, json={"approver_role": "sales_rep"})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "crm_sod_violation"
    assert client.get(quote_path + "/Q-STABLE-ID", headers=headers).json()["status"] == "draft"
    legacy = client.post(quote_path + "/Q-LEGACY-NAME/approve", headers=headers, json={"approver_role": "sales_rep"})
    assert legacy.status_code == 409 and legacy.json()["error"]["code"] == "quotation_identity_unverified"
    duplicate = client.post(quote_path, headers=headers, json={"quote_id": "Q-LEGACY-NAME", "opportunity_id": "OP-TAKEOVER", "customer_id": "CUSTOMER-OTHER", "currency": "USD", "valid_until": "2026-12-31", "lines": [{"line_number": 1, "item_id": "OTHER", "description": "Rejected takeover", "quantity": 1, "unit_price_minor": 9999}]})
    assert duplicate.status_code == 409
    original_legacy = client.get(quote_path + "/Q-LEGACY-NAME", headers=headers).json()
    assert original_legacy["submitter_user_id"] == "source-human-name" and original_legacy["status"] == "draft" and original_legacy["total_net_minor"] == 1001
    collision_login = client.post("/api/v1/auth/login", headers=tenant_headers, json={"username": "collision-renamed", "password": runtime.password})
    assert collision_login.status_code == 200
    collision_headers = {**headers, "Authorization": "Bearer " + collision_login.json()["access_token"]}
    assert client.post("/api/v1/auth/step-up", headers=collision_headers, json={"password": runtime.password}).status_code == 200
    collision_refused = client.post(quote_path + "/Q-LEGACY-ID-COLLISION/approve", headers=collision_headers, json={"approver_role": "sales_rep"})
    assert collision_refused.status_code == 409 and collision_refused.json()["error"]["code"] == "quotation_identity_unverified"
    reviewer = client.post("/api/v1/auth/login", headers=tenant_headers, json={"username": "source-reviewer-name", "password": runtime.password})
    assert reviewer.status_code == 200, reviewer.text
    headers["Authorization"] = "Bearer " + reviewer.json()["access_token"]
    assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
    approved = client.post(quote_path + "/Q-STABLE-ID/approve", headers=headers, json={"approver_role": "sales_rep"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by_user_id"] == "source-reviewer-id"
    assert approved.json()["approved_by"] == "source-reviewer-name"
    assert client.get(quote_path + "/Q-STABLE-ID", headers=headers).json()["approved_by_user_id"] == "source-reviewer-id"
    duplicate_approved = client.post(quote_path, headers=headers, json={"quote_id": "Q-STABLE-ID", "opportunity_id": "OP-TAKEOVER", "customer_id": "CUSTOMER-OTHER", "currency": "USD", "valid_until": "2026-12-31", "lines": [{"line_number": 1, "item_id": "OTHER", "description": "Rejected approved replacement", "quantity": 1, "unit_price_minor": 9999}]})
    assert duplicate_approved.status_code == 409
    retained = client.get(quote_path + "/Q-STABLE-ID", headers=headers).json()
    assert retained["status"] == "approved" and retained["total_net_minor"] == 1001 and retained["submitter_user_id"] == "source-human-id" and retained["approved_by_user_id"] == "source-reviewer-id"
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        assert PostgresCRMContractsRepository(connection, runtime.tenant).quotation_author_id("work", "Q-LEGACY-NAME") is None


def test_native_api_invoice_retry_reuses_original_issue_time(bridge_runtime: BridgeRuntime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from reconforge.infrastructure import postgres_project_milestone_billing as module

    runtime = bridge_runtime
    invoice_id = source(runtime, "ProjectMilestone")
    application = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=runtime.base.factory.settings.dsn, postgres_require_tls=False)
    client = TestClient(application)
    headers = {"X-ReconForge-Tenant": runtime.base.tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity"}
    login = client.post("/api/v1/auth/login", headers=headers, json={"username": "maker", "password": runtime.base.password})
    assert login.status_code == 200, login.text
    headers["Authorization"] = "Bearer " + login.json()["access_token"]
    assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.base.password}).status_code == 200
    payload = {"invoice_id": invoice_id, "customer_code": "CUSTOMER", "financial_context": {"command_id": "API-TIMESTAMP-RETRY", "organization_code": "ORG", "entity_code": "ENTITY", "period_id": "period", "posting_date": "2026-10-25", "journal_code": "STOCK"}}
    monkeypatch.setattr(module, "utc_now_text", lambda: "2026-10-25T00:00:00Z")
    first = client.post("/api/v1/projects/billing/milestones/MS1/bill", headers=headers, json=payload)
    assert first.status_code == 200, first.text

    def reject_reissued_timestamp() -> str:
        raise AssertionError("Retry must use the immutable original issue timestamp.")

    monkeypatch.setattr(module, "utc_now_text", reject_reissued_timestamp)
    repeated = client.post("/api/v1/projects/billing/milestones/MS1/bill", headers=headers, json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first.json()
    with runtime.actor("maker", private=False) as (connection, _repository, _actor):
        row = connection.execute("SELECT issued_at FROM reconforge.project_milestone_invoices WHERE tenant_id=%s AND invoice_id=%s", (runtime.base.tenant, invoice_id)).fetchone()
        assert row[0] == "2026-10-25T00:00:00Z"
        assert connection.execute("SELECT count(*) FROM reconforge.enterprise_finance_bindings WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()[0] == 1
