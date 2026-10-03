"""Real password/session HTTP posting with independent review and scope denial."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.domain.finance_posting import validation_digest
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_finance_posting import PERMISSIONS, posting_database
from tests.test_postgres_finance_scope import finance_database, isolated_postgres_migration_dsn

__all__ = ["posting_database", "finance_database", "isolated_postgres_migration_dsn"]
TENANT = "finance_scope"
PASSWORD = "Synthetic-posting-API-password-2026!"
SCOPE = {"X-ReconForge-Tenant": TENANT, "X-ReconForge-Workspace": "shared", "X-ReconForge-Organization": "org_a", "X-ReconForge-Legal-Entity": "entity_a1"}


@pytest.fixture
def posting_api(posting_database: dict[str, Any], tmp_path: Path) -> Iterator[tuple[dict[str, Any], TestClient, dict[str, dict[str, str]]]]:
    import psycopg

    db = posting_database
    with db["boundary"].transaction(TENANT) as conn:
        conn.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,'shared','org_a') ON CONFLICT DO NOTHING", (TENANT,))
        identities = PostgresIdentityRepository(conn)
        for permission in PERMISSIONS:
            identities.create_permission(tenant_id=TENANT, permission_name=permission)
        for username, permissions in (("api-maker", PERMISSIONS), ("api-checker", PERMISSIONS), ("api-reader", frozenset({"finance_core.read"}))):
            identities.create_role(tenant_id=TENANT, role_name=username)
            for permission in permissions:
                identities.grant_permission(tenant_id=TENANT, role_name=username, permission_name=permission)
            identities.create_user(tenant_id=TENANT, user_id=username, username=username, password=PASSWORD, role_name=username)
            for kind, identifier in (("workspace", "shared"), ("workspace", "other"), ("organization", "org_a"), ("legal_entity", "entity_a1"), ("legal_entity", "entity_a2")):
                PostgresScopeAuthorityRepository(conn).grant(tenant_id=TENANT, grant_id=f"{username}-{identifier}", principal_type="user", principal_id=username, scope_type=kind, scope_id=identifier, actor_id=username)
    params = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(db["admin"])["dbname"]
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=psycopg.conninfo.make_conninfo(**params), postgres_require_tls=False, secure_transport=True, policy_cache_enabled=True)
    with TestClient(app, base_url="https://testserver") as client:
        headers = {}
        for username in ("api-maker", "api-checker", "api-reader"):
            login = client.post("/api/v1/auth/login", headers={"X-ReconForge-Tenant": TENANT}, json={"username": username, "password": PASSWORD})
            assert login.status_code == 200, login.text
            headers[username] = {**SCOPE, "Authorization": "Bearer " + login.json()["access_token"]}
        yield db, client, headers


def _draft(number: str, amount: str = "100.00") -> dict[str, Any]:
    return {
        "entry_number": number, "organization_code": "ORG_A", "entity_code": "A1", "period_id": "period",
        "journal_code": "J_A", "posting_date": "2026-07-28", "description": "Actual synthetic authenticated manual draft",
        "workspace": "shared", "lines": [
            {"account_code": "A_CASH", "debit": amount, "dimensions": {"D_A": "V", "D_SHARED": "V"}},
            {"account_code": "A_CAPITAL", "credit": amount},
        ],
    }


def test_live_api_human_review_post_exact_unknown_reply_and_full_reversal(posting_api: Any) -> None:
    import psycopg

    db, client, headers = posting_api
    maker, checker, reader = (headers[key] for key in ("api-maker", "api-checker", "api-reader"))
    for actor in (maker, checker):
        assert client.post("/api/v1/auth/step-up", headers=actor, json={"password": PASSWORD}).status_code == 200
    created = client.post("/api/v1/finance-core/entries", headers=maker, json=_draft("HTTP-EXACT", "90071992547409.93"))
    assert created.status_code == 200, created.text
    entry_id = created.json()["entry"]["id"]
    self_review = client.post(f"/api/v1/finance-core/entries/{entry_id}/validate", headers=maker, json={"reason": "Self review refused"})
    assert self_review.status_code == 400, self_review.text
    reviewed = client.post(f"/api/v1/finance-core/entries/{entry_id}/validate", headers=checker, json={"reason": "Independent content review"})
    assert reviewed.status_code == 200, reviewed.text
    preview = client.get(f"/api/v1/finance-core/entries/{entry_id}/posting-preview", headers=reader)
    assert preview.status_code == 200, preview.text
    review = preview.json()["review"]
    assert review["preparer_actor_id"] == "api-maker" and review["validator_actor_id"] == "api-checker"
    digest = review["validation_digest"]
    assert validation_digest(json.loads(review["snapshot_json"])) == digest
    assert review["lines"][0]["debit_minor"] == "9007199254740993"
    command = {"command_id": "HTTP-EXACT-POST", "expected_validation_digest": digest, "reason": "Explicit reviewed operational effect"}
    assert client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=maker, json=command).status_code == 403
    assert client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=reader, json=command).status_code == 403
    wrong = client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=checker, json={**command, "expected_validation_digest": "0" * 64})
    assert wrong.status_code == 409, wrong.text
    posted = client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=checker, json=command)
    assert posted.status_code == 200, posted.text
    effect = posted.json()["posting"]
    # Ignore the successful response and repeat exactly, then retrieve authority.
    assert client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=checker, json=command).json() == posted.json()
    assert client.get(f"/api/v1/finance-core/postings/{effect['id']}", headers=reader).json() == posted.json()
    changed = client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=checker, json={**command, "reason": "Changed payload"})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "posting_command_conflict"
    target = "/api/v1/finance-core/posted-trial-balance?period_id=period&organization_code=ORG_A&entity_code=A1&workspace=shared"
    balance = client.get(target, headers=reader)
    assert balance.status_code == 200, balance.text
    assert balance.json()["trial_balance"]["effect_count"] == 1
    assert balance.json()["trial_balance"]["balance_totals"] == {"debit_minor": "9007199254740993", "credit_minor": "9007199254740993", "balanced": True}
    assert balance.json()["trial_balance"]["turnover_totals"] == balance.json()["trial_balance"]["balance_totals"]
    request = {"command_id": "HTTP-EXACT-REVERSE", "entry_number": "HTTP-FULL-REVERSAL", "period_id": "period", "posting_date": "2026-07-29", "reason": "Explicit full correction"}
    prepared = client.post(f"/api/v1/finance-core/postings/{effect['id']}/reversal", headers=maker, json=request)
    assert prepared.status_code == 200, prepared.text
    reversal_id = prepared.json()["reversal"]["entry_id"]
    assert prepared.json()["reversal"]["status"] == "Draft"
    assert client.post(f"/api/v1/finance-core/entries/{reversal_id}/validate", headers=checker, json={"reason": "Independent reversal review"}).status_code == 200
    reversal_digest = client.get(f"/api/v1/finance-core/entries/{reversal_id}/posting-preview", headers=reader).json()["review"]["validation_digest"]
    reversal = client.post(f"/api/v1/finance-core/entries/{reversal_id}/post", headers=checker, json={**command, "command_id": "HTTP-EXACT-REVERSE-POST", "expected_validation_digest": reversal_digest})
    assert reversal.status_code == 200, reversal.text
    final = client.get(target, headers=reader).json()["trial_balance"]
    assert final["effect_count"] == 2 and all(row["balance_minor"] == "0" for row in final["accounts"])
    assert final["turnover_totals"]["debit_minor"] == "18014398509481986"
    assert final["balance_totals"] == {"debit_minor": "0", "credit_minor": "0", "balanced": True}
    assert all(len(row["postings"]) == 2 for row in final["accounts"])
    with psycopg.connect(db["admin"]) as admin:
        assert admin.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 2
        assert admin.execute("SELECT count(*) FROM reconforge.finance_posting_commands").fetchone()[0] == 3
        assert admin.execute("SELECT count(*) FROM reconforge.domain_audit_events WHERE action='finance_entry_posted'").fetchone()[0] == 2
        assert admin.execute("SELECT count(*) FROM reconforge.outbox_events WHERE event_type='finance_entry_posted'").fetchone()[0] == 2


def test_live_api_scope_cookie_csrf_and_post_requires_recent_auth(posting_api: Any) -> None:
    db, client, headers = posting_api
    for actor in (headers["api-maker"], headers["api-checker"]):
        assert client.post("/api/v1/auth/step-up", headers=actor, json={"password": PASSWORD}).status_code == 200
    created = client.post("/api/v1/finance-core/entries", headers=headers["api-maker"], json=_draft("HTTP-SCOPE"))
    assert created.status_code == 200, created.text
    entry_id = created.json()["entry"]["id"]
    assert client.post(f"/api/v1/finance-core/entries/{entry_id}/validate", headers=headers["api-checker"], json={"reason": "Review exact synthetic entry"}).status_code == 200
    digest = client.get(f"/api/v1/finance-core/entries/{entry_id}/posting-preview", headers=headers["api-checker"]).json()["review"]["validation_digest"]
    command = {"command_id": "HTTP-SCOPE-POST", "expected_validation_digest": digest, "reason": "Explicit"}
    sibling = {**headers["api-checker"], "X-ReconForge-Legal-Entity": "entity_a2"}
    denied = client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=sibling, json=command)
    assert denied.status_code == 404 and entry_id not in denied.text
    login = client.post("/api/v1/auth/browser/login", headers={"X-ReconForge-Tenant": TENANT}, json={"username": "api-checker", "password": PASSWORD})
    assert login.status_code == 200, login.text
    cookie = {**SCOPE, "X-ReconForge-CSRF": login.json()["csrf_token"]}
    assert client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=SCOPE, json=command).status_code == 403
    stale = client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=cookie, json=command)
    assert stale.status_code == 403 and stale.json()["error"]["code"] == "step_up_required"
    assert client.post("/api/v1/auth/step-up", headers=cookie, json={"password": PASSWORD}).status_code == 200
    assert client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=cookie, json={**command, "actor_id": "api-checker"}).status_code == 422
    posted = client.post(f"/api/v1/finance-core/entries/{entry_id}/post", headers=cookie, json=command)
    assert posted.status_code == 200, posted.text
    assert client.get(f"/api/v1/finance-core/postings/{posted.json()['posting']['id']}", headers=sibling).status_code == 404
    assert not Path(client.app.state.db_path).exists()
