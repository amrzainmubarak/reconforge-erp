from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, RequestExecutionScope, request_tenant_id
from reconforge.auth.models import LocalUser
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import (
    POSTGRES_IDENTITY_SCHEMA_SQL,
    PostgresIdentityRepository,
    PostgresSession,
)
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import ServerPrincipal, require_permission, server_principal_context, trusted_local_mode


class _FakeServerIdentity:
    def __init__(self) -> None:
        self.user = LocalUser(
            id="user-a",
            username="alice",
            display_name="Alice",
            email="alice@example.test",
            created_at="2026-01-01T00:00:00Z",
        )
        self.permissions = frozenset(
            {
                "db.read",
                "roles.manage",
                "finance_core.read",
                "finance_core.manage",
                "finance_core.validate",
                "master_data.read",
                "master_data.manage",
                "audit.read",
                "audit.verify",
                "close.read",
                "close.manage",
            }
        )
        self.revoked = False
        self.accounts: list[dict[str, object]] = []
        self.entries: dict[str, dict[str, object]] = {}
        self.currencies: list[dict[str, object]] = [
            {
                "tenant_id": "tenant-a",
                "code": "USD",
                "name": "US Dollar",
                "minor_units": 2,
                "active": True,
            }
        ]
        self.organizations: list[dict[str, object]] = [
            {
                "tenant_id": "tenant-a",
                "id": "org-a",
                "organization_code": "ORG-A",
                "name": "API Organization",
                "base_currency": "USD",
                "active": True,
            }
        ]
        self.entities: list[dict[str, object]] = []
        self.branches: list[dict[str, object]] = []
        self.periods: list[dict[str, object]] = []
        self.close_periods: list[dict[str, object]] = []
        self.close_tasks: list[dict[str, object]] = []

    def authenticate_user(self, *, tenant_id: str, username: str, password: str) -> LocalUser | None:
        assert tenant_id == "tenant-a"
        return self.user if username.casefold() == "alice" and password == "Strong-password-123" else None

    def create_session(self, *, tenant_id: str, user_id: str, **_: object) -> PostgresSession:
        assert tenant_id == "tenant-a"
        assert user_id == self.user.id
        return PostgresSession(
            id="ses-a",
            user_id=user_id,
            token="server-token",
            expires_at="2026-01-01T08:00:00Z",
        )

    def authenticate_token(self, *, tenant_id: str, token: str) -> LocalUser | None:
        return self.user if tenant_id == "tenant-a" and token == "server-token" and not self.revoked else None

    def user_permissions(self, *, tenant_id: str, user_id: str) -> frozenset[str]:
        assert tenant_id == "tenant-a"
        assert user_id == self.user.id
        return self.permissions

    def user_roles(self, *, tenant_id: str, user_id: str) -> list[str]:
        assert tenant_id == "tenant-a"
        assert user_id == self.user.id
        return ["server-admin"]

    def revoke_token(self, *, tenant_id: str, token: str) -> bool:
        if tenant_id != "tenant-a" or token != "server-token" or self.revoked:
            return False
        self.revoked = True
        return True

    def organization_by_code(self, *, tenant_id: str, organization_code: str) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        for organization in self.organizations:
            if organization["organization_code"] == organization_code.upper():
                return organization
        raise AssertionError(f"Unknown fake organization: {organization_code}")

    def summary(self, *, tenant_id: str) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        return {
            "accounts": len(self.accounts),
            "draft_entries": 0,
            "posted_entries": len(self.entries),
            "schema_version": 1,
            "source": {"kind": "postgres-master-data", "server_mode": True, "external_calls": False},
            "tenant_id": tenant_id,
            "organizations": len(self.organizations),
            "legal_entities": len(self.entities),
            "branches": len(self.branches),
            "active_currencies": sum(1 for currency in self.currencies if currency["active"]),
            "periods": len(self.periods),
            "unsupported_collections": [],
        }

    def list_currencies(self, *, tenant_id: str, active_only: bool = False) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        records = self.currencies
        return [record for record in records if not active_only or record["active"]]

    def upsert_currency(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "code": str(values["code"]).upper(),
            "name": values["name"],
            "minor_units": values["minor_units"],
            "active": values["active"],
        }
        self.currencies = [currency for currency in self.currencies if currency["code"] != record["code"]]
        self.currencies.append(record)
        return record

    def list_organizations(self, *, tenant_id: str, active_only: bool = False) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        return [organization for organization in self.organizations if not active_only or organization["active"]]

    def upsert_organization(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["organization_id"],
            "organization_code": str(values["organization_code"]).upper(),
            "name": values["name"],
            "base_currency": values["base_currency"],
            "active": values["active"],
        }
        self.organizations = [
            organization
            for organization in self.organizations
            if organization["organization_code"] != record["organization_code"]
        ]
        self.organizations.append(record)
        return record

    def list_legal_entities(
        self, *, tenant_id: str, organization_id: str | None = None
    ) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        return [
            entity
            for entity in self.entities
            if organization_id is None or entity["organization_id"] == organization_id
        ]

    def upsert_legal_entity(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["entity_id"],
            "organization_id": values["organization_id"],
            "entity_code": str(values["entity_code"]).upper(),
            "name": values["name"],
            "currency_code": values["currency_code"],
            "active": values["active"],
        }
        self.entities = [entity for entity in self.entities if entity["id"] != record["id"]]
        self.entities.append(record)
        return record

    def legal_entity_by_code(
        self, *, tenant_id: str, organization_id: str, entity_code: str
    ) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        for entity in self.entities:
            if entity["organization_id"] == organization_id and entity["entity_code"] == entity_code.upper():
                return entity
        raise AssertionError(f"Unknown fake entity: {entity_code}")

    def list_branches(self, *, tenant_id: str, organization_id: str | None = None) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        return [
            branch
            for branch in self.branches
            if organization_id is None or branch["organization_id"] == organization_id
        ]

    def upsert_branch(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["branch_id"],
            "organization_id": values["organization_id"],
            "legal_entity_id": values["legal_entity_id"],
            "branch_code": str(values["branch_code"]).upper(),
            "name": values["name"],
            "active": values["active"],
        }
        self.branches = [branch for branch in self.branches if branch["id"] != record["id"]]
        self.branches.append(record)
        return record

    def list_periods(self, *, tenant_id: str) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        return list(self.close_periods) if self.close_periods else list(self.periods)

    def upsert_period(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["period_id"],
            "name": values["name"],
            "start_date": values["start_date"],
            "end_date": values["end_date"],
            "status": "Open",
            "fiscal_year": values["fiscal_year"] or 2026,
            "period_number": values["period_number"] or 7,
            "status_reason": "",
        }
        self.periods = [period for period in self.periods if period["id"] != record["id"]]
        self.periods.append(record)
        return record

    def set_period_status(self, **values: object) -> dict[str, object]:
        for period in self.close_periods:
            if period["id"] == values["period_id"]:
                period["status"] = values["status"]
                return period
        for period in self.periods:
            if period["id"] == values["period_id"]:
                period["status"] = values["status"]
                period["status_reason"] = values["reason"]
                return period
        raise AssertionError(f"Unknown fake period: {values['period_id']}")

    def list_accounts(self, *, tenant_id: str, organization_id: str | None = None) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        return self.accounts

    def upsert_account(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["account_id"],
            "organization_id": values["organization_id"],
            "account_code": str(values["account_code"]).upper(),
            "name": values["name"],
            "account_type": values["account_type"],
            "normal_balance": values["normal_balance"],
            "active": values["active"],
        }
        self.accounts = [account for account in self.accounts if account["account_code"] != record["account_code"]]
        self.accounts.append(record)
        return record

    def account_by_code(self, *, tenant_id: str, organization_id: str, account_code: str) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        for account in self.accounts:
            if account["organization_id"] == organization_id and account["account_code"] == account_code.upper():
                return account
        raise AssertionError(f"Unknown fake account: {account_code}")

    def post_entry(self, **values: object) -> dict[str, object]:
        entry = {
            "tenant_id": values["tenant_id"],
            "id": values["entry_id"],
            "entry_number": values["entry_number"],
            "organization_id": values["organization_id"],
            "currency_code": values["currency_code"],
            "posting_date": values["posting_date"],
            "description": values["description"],
            "status": "Posted",
            "lines": [line.__dict__ for line in values["lines"]],
        }
        self.entries[str(entry["id"])] = entry
        return entry

    def get_entry(self, *, tenant_id: str, entry_id: str) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        return self.entries[entry_id]

    def list_entries(self, **_: object) -> list[dict[str, object]]:
        return list(self.entries.values())

    def trial_balance(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        return {
            "schema_version": 1,
            "source": {"kind": "postgres-ledger-control", "server_mode": True, "external_calls": False},
            "workspace": None,
            "organization_code": values["organization_code"],
            "entity_code": "",
            "period_id": values["period_id"],
            "period_name": "2026-07",
            "currency_code": "USD",
            "currency_minor_units": 2,
            "totals": {
                "debit_minor": 0,
                "credit_minor": 0,
                "balanced": True,
                "debit": "0.00",
                "credit": "0.00",
            },
            "accounts": [],
        }

    def list_audit_events(self, *, tenant_id: str, limit: int | None = None) -> list[dict[str, object]]:
        assert tenant_id == "tenant-a"
        return [
            {
                "event_sequence": 1,
                "tenant_id": tenant_id,
                "event_id": "event-1",
                "actor_id": "alice",
                "action": "ledger_entry_posted",
                "resource_type": "ledger_entry",
                "resource_id": "entry-a",
                "occurred_at": "2026-07-23T00:00:00Z",
                "request_id": "request-1",
                "before_state_hash": "",
                "after_state_hash": "after-hash",
                "previous_event_hash": "",
                "event_hash": "event-hash",
                "reason": "close",
                "metadata": {"source": "fake"},
            }
        ][:limit]

    def verify_audit_events(self, *, tenant_id: str) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        return {"ok": True, "checked_events": 1, "head_hash": "event-hash", "issues": []}

    def create_period(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["period_id"],
            "fiscal_period_id": values["fiscal_period_id"],
            "organization_id": values["organization_id"],
            "status": "Open",
            "readiness_score": 0.0,
        }
        self.close_periods = [period for period in self.close_periods if period["id"] != record["id"]]
        self.close_periods.append(record)
        return record

    def get_period(self, *, tenant_id: str, period_id: str) -> dict[str, object]:
        assert tenant_id == "tenant-a"
        for period in self.close_periods:
            if period["id"] == period_id:
                return period
        raise AssertionError(f"Unknown fake close period: {period_id}")

    def upsert_task(self, **values: object) -> dict[str, object]:
        record = {
            "tenant_id": values["tenant_id"],
            "id": values["task_id"],
            "close_period_id": values["close_period_id"],
            "task_code": values["task_code"],
            "name": values["name"],
            "status": "Not Started",
            "owner_user_id": values.get("owner_user_id", ""),
            "risk_rating": values.get("risk_rating", "medium"),
        }
        self.close_tasks = [task for task in self.close_tasks if task["id"] != record["id"]]
        self.close_tasks.append(record)
        return record

    def list_tasks(self, **values: object) -> list[dict[str, object]]:
        assert values["tenant_id"] == "tenant-a"
        period_id = str(values.get("close_period_id") or "")
        return [task for task in self.close_tasks if not period_id or task["close_period_id"] == period_id]

    def set_task_status(self, **values: object) -> dict[str, object]:
        for task in self.close_tasks:
            if task["id"] == values["task_id"]:
                task["status"] = values["status"]
                return task
        raise AssertionError(f"Unknown fake close task: {values['task_id']}")

    def readiness(self, *, tenant_id: str, period_id: str) -> dict[str, object]:
        tasks = [task for task in self.close_tasks if task["close_period_id"] == period_id]
        complete = sum(1 for task in tasks if task["status"] in {"Complete", "Not Applicable"})
        score = round((complete / len(tasks)) * 100, 2) if tasks else 0.0
        return {
            "period_id": period_id,
            "period_name": "period-a",
            "total_tasks": len(tasks),
            "complete_tasks": complete,
            "blocked_tasks": sum(1 for task in tasks if task["status"] == "Blocked"),
            "readiness_score": score,
        }

def test_server_profile_requires_tenant_isolated_legacy_storage(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tenant_db_root"):
        create_api_app(tmp_path / "control.db", postgres_dsn="postgresql://identity.test/postgres")


def test_server_profile_uses_postgres_identity_for_api_auth_and_principal_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.audit as audit_routes
    import reconforge.api.routes.auth as auth_routes
    import reconforge.api.routes.close as close_routes
    import reconforge.api.routes.finance_core as finance_core_routes
    import reconforge.api.routes.master_data as master_data_routes

    fake = _FakeServerIdentity()
    scoped_permissions: list[dict[str, object]] = []
    ledger_scoped_permissions: list[dict[str, object]] = []

    def execute(_request: Any, operation: Any) -> Any:
        return operation(fake, request_tenant_id(_request))

    def authenticate(_request: Any, token: str) -> AuthenticatedServerRequest | None:
        request_tenant_id(_request)
        user = fake.authenticate_token(tenant_id="tenant-a", token=token)
        return (
            AuthenticatedServerRequest(
                user=user,
                permissions=fake.permissions,
                principal_type="user",
                session_id="ses-a",
                step_up_active=True,
                step_up_expires_at="2026-01-01T00:10:00Z",
            )
            if user is not None
            else None
        )

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(auth_routes, "execute_postgres_identity", execute)
    monkeypatch.setattr(audit_routes, "execute_postgres_ledger", execute)
    monkeypatch.setattr(close_routes, "execute_postgres_close", execute)
    monkeypatch.setattr(close_routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant-a", "workspace-a"))
    monkeypatch.setattr(
        close_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(
        finance_core_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope("tenant-a", "workspace-a"),
    )
    monkeypatch.setattr(
        finance_core_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: ledger_scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(finance_core_routes, "execute_postgres_ledger", execute)
    monkeypatch.setattr(master_data_routes, "execute_postgres_master_data", execute)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    tenant_db = tenant_root / "tenant-a.db"
    run_migrations(tenant_db)
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
        )
    )
    tenant_headers = {"X-ReconForge-Tenant": "tenant-a"}

    missing_tenant = client.post("/api/v1/auth/login", json={"username": "alice", "password": "Strong-password-123"})
    login = client.post(
        "/api/v1/auth/login",
        headers=tenant_headers,
        json={"username": "alice", "password": "Strong-password-123"},
    )
    token_headers = {**tenant_headers, "Authorization": "Bearer server-token"}
    me = client.get("/api/v1/auth/me", headers=token_headers)
    roles = client.get("/api/v1/roles", headers=token_headers)
    finance_summary = client.get("/api/v1/finance-core/summary", headers=token_headers)
    master_currency = client.post(
        "/api/v1/master-data/currencies",
        headers=token_headers,
        json={"code": "EUR", "name": "Euro", "minor_units": 2},
    )
    master_organization = client.post(
        "/api/v1/master-data/organizations",
        headers=token_headers,
        json={"organization_code": "ORG-B", "name": "Second Organization", "base_currency": "USD"},
    )
    master_entity = client.post(
        "/api/v1/master-data/entities",
        headers=token_headers,
        json={
            "organization_code": "ORG-A",
            "entity_code": "LE-1",
            "name": "Legal Entity",
            "currency_code": "USD",
        },
    )
    master_branch = client.post(
        "/api/v1/master-data/branches",
        headers=token_headers,
        json={
            "organization_code": "ORG-A",
            "branch_code": "BR-1",
            "name": "Main Branch",
            "entity_code": "LE-1",
        },
    )
    master_period = client.post(
        "/api/v1/master-data/periods",
        headers=token_headers,
        json={"name": "2026-07", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    period_id = master_period.json()["period"]["id"]
    master_period_status = client.post(
        f"/api/v1/master-data/periods/{period_id}/status",
        headers=token_headers,
        json={"status": "Soft Closed"},
    )
    server_trial_balance = client.get(
        "/api/v1/finance-core/trial-balance",
        headers=token_headers,
        params={"period_id": period_id, "organization": "ORG-A", "entity": ""},
    )
    audit_events = client.get("/api/v1/audit/events", headers=token_headers)
    audit_verify = client.get("/api/v1/audit/verify", headers=token_headers)
    entity_trial_balance = client.get(
        "/api/v1/finance-core/trial-balance",
        headers=token_headers,
        params={"period_id": period_id, "organization": "ORG-A", "entity": "LE-1"},
    )
    master_summary = client.get("/api/v1/master-data/summary", headers=token_headers)
    master_snapshot = client.get("/api/v1/master-data/snapshot", headers=token_headers)
    master_entities = client.get("/api/v1/master-data/entities", headers=token_headers)
    master_periods = client.get("/api/v1/master-data/periods", headers=token_headers)
    close_period = client.post(
        "/api/v1/close/periods",
        headers=token_headers,
        json={"fiscal_period_id": period_id, "organization_code": "ORG-A"},
    )
    assert close_period.status_code == 200, close_period.text
    close_period_id = close_period.json()["period"]["id"]
    close_periods = client.get("/api/v1/close/periods", headers=token_headers)
    close_tasks = client.get(
        "/api/v1/close/tasks",
        headers=token_headers,
        params={"period_id": close_period_id},
    )
    close_readiness = client.get(
        f"/api/v1/close/periods/{close_period_id}/readiness",
        headers=token_headers,
    )
    close_task_status = client.post(
        f"/api/v1/close/tasks/{close_tasks.json()['tasks'][0]['id']}/status",
        headers=token_headers,
        json={"status": "In Progress"},
    )
    cash = client.post(
        "/api/v1/finance-core/accounts",
        headers=token_headers,
        json={"organization_code": "ORG-A", "account_code": "1000", "name": "Cash"},
    )
    revenue = client.post(
        "/api/v1/finance-core/accounts",
        headers=token_headers,
        json={
            "organization_code": "ORG-A",
            "account_code": "4000",
            "name": "Revenue",
            "account_type": "Income",
            "normal_balance": "Credit",
        },
    )
    accounts = client.get("/api/v1/finance-core/accounts", headers=token_headers, params={"organization": "ORG-A"})
    entry = client.post(
        "/api/v1/finance-core/entries",
        headers=token_headers,
        json={
            "entry_number": "JE-001",
            "organization_code": "ORG-A",
            "posting_date": "2026-07-23",
            "description": "Server ledger entry",
            "currency_code": "USD",
            "lines": [
                {"account_code": "1000", "debit": "100.00", "credit": "0"},
                {"account_code": "4000", "debit": "0", "credit": "100.00"},
            ],
        },
    )
    entry_id = entry.json()["entry"]["id"]
    fetched_entry = client.get(f"/api/v1/finance-core/entries/{entry_id}", headers=token_headers)
    entries = client.get("/api/v1/finance-core/entries", headers=token_headers)
    validation = client.post(
        f"/api/v1/finance-core/entries/{entry_id}/validate",
        headers=token_headers,
        json={"reason": "Reviewed"},
    )
    unsupported_chart = client.post(
        "/api/v1/finance-core/charts",
        headers=token_headers,
        json={"chart_code": "DEFAULT", "name": "Chart"},
    )
    denied = client.post(
        "/api/v1/users",
        headers=token_headers,
        json={"username": "new-user", "password": "Secret-123", "role": "reviewer"},
    )
    logout = client.post("/api/v1/auth/logout", headers=token_headers)
    after_logout = client.get("/api/v1/auth/me", headers=token_headers)

    assert missing_tenant.status_code == 400
    assert missing_tenant.json()["error"]["code"] == "tenant_required"
    assert login.status_code == 200
    assert login.json()["access_token"] == "server-token"
    assert me.status_code == 200
    assert me.json()["roles"] == ["server-admin"]
    assert roles.status_code == 409
    assert roles.json()["error"]["code"] == "local_identity_surface_disabled"
    assert finance_summary.status_code == 200
    assert master_currency.status_code == 200
    assert master_organization.status_code == 200
    assert master_entity.status_code == 200
    assert master_branch.status_code == 200
    assert master_period.status_code == 200
    assert master_period_status.status_code == 200
    assert master_period_status.json()["period"]["status"] == "Soft Closed"
    assert server_trial_balance.status_code == 200
    assert server_trial_balance.json()["totals"]["balanced"] is True
    assert audit_events.status_code == 200
    assert audit_events.json()["source"]["kind"] == "postgresql-ledger-control"
    assert audit_events.json()["events"][0]["metadata"] == {"source": "fake"}
    assert audit_verify.status_code == 200
    assert audit_verify.json()["ok"] is True
    assert entity_trial_balance.status_code == 501
    assert master_summary.status_code == 200
    assert master_summary.json()["summary"]["source"]["kind"] == "postgres-master-data"
    assert master_snapshot.status_code == 200
    assert master_snapshot.json()["unsupported_collections"] == []
    assert len(master_snapshot.json()["periods"]) == 1
    assert master_entities.status_code == 200
    assert master_entities.json()["pagination"]["returned"] == 1
    assert master_periods.status_code == 200
    assert master_periods.json()["pagination"]["returned"] == 1
    assert close_period.status_code == 200
    assert close_period.json()["source"]["kind"] == "postgresql-close-control"
    assert close_periods.status_code == 200
    assert close_tasks.status_code == 200
    assert len(close_tasks.json()["tasks"]) == 5
    assert close_readiness.status_code == 200
    assert close_task_status.status_code == 200
    assert scoped_permissions == [
        {"permission": "close.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        {"permission": "close.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
    ]
    assert ledger_scoped_permissions == [
        {"permission": "finance_core.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        {"permission": "finance_core.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        {"permission": "finance_core.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
    ]
    assert cash.status_code == 200
    assert revenue.status_code == 200
    assert accounts.status_code == 200
    assert accounts.json()["pagination"]["returned"] == 2
    assert entry.status_code == 200
    assert entry.json()["entry"]["status"] == "Posted"
    assert fetched_entry.status_code == 200
    assert fetched_entry.json()["entry"]["entry_number"] == "JE-001"
    assert entries.status_code == 200
    assert entries.json()["pagination"]["returned"] == 1
    assert validation.status_code == 501
    assert unsupported_chart.status_code == 501
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"
    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    assert after_logout.status_code == 401


def test_server_principal_binds_permission_to_actor_and_never_uses_local_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "principal.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        user = LocalUser(id="server-user", username="alice", display_name="Alice")
        principal = ServerPrincipal(user=user, permissions=frozenset({"accounts.prepare"}))
        with trusted_local_mode(False), server_principal_context(principal):
            assert require_permission(connection, actor_label="alice", permission="accounts.prepare") == user
            with pytest.raises(ValueError, match="Permission denied"):
                require_permission(connection, actor_label="alice", permission="accounts.review")
            with pytest.raises(ValueError, match="Authenticated actor"):
                require_permission(connection, actor_label="bob", permission="accounts.prepare")
    finally:
        connection.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_server_api_uses_postgres_identity_and_tenant_scope(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    from reconforge.api.routes.master_data import _server_id
    from reconforge.infrastructure.postgres import install_postgres_rls_schema
    from reconforge.infrastructure.postgres_close import POSTGRES_CLOSE_SCHEMA_SQL
    from reconforge.infrastructure.postgres_consolidation_close import (
        POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL,
    )
    from reconforge.infrastructure.postgres_consolidation_ownership import (
        POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL,
    )
    from reconforge.infrastructure.postgres_consolidation_ppa import POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL
    from reconforge.infrastructure.postgres_ledger import (
        POSTGRES_LEDGER_SCHEMA_SQL,
        PostgresLedgerRepository,
    )
    from reconforge.infrastructure.postgres_master_data import (
        POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
        POSTGRES_MASTER_DATA_SCHEMA_SQL,
        PostgresMasterDataRepository,
    )
    from reconforge.infrastructure.postgres_privileged_sessions import POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL
    from reconforge.infrastructure.postgres_writeback import POSTGRES_WRITEBACK_SCHEMA_SQL

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant_a = f"api_identity_a_{token}"
    tenant_b = f"api_identity_b_{token}"
    organization_id = _server_id("org", tenant_a, "ORG-A")
    admin = admin_factory.connect()
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant_id in (tenant_a, tenant_b):
        run_migrations(root / f"{tenant_id}.db")
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_FISCAL_PERIOD_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_CLOSE_SCHEMA_SQL)
            admin.execute(POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL)
            admin.execute(POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL)
            admin.execute(POSTGRES_WRITEBACK_SCHEMA_SQL)
            admin.execute(POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL)
            admin.execute(
                f"GRANT USAGE ON SCHEMA reconforge TO {app_user}" if app_user else "SELECT 1"
            )
            if app_user:
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                    f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                    f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                    f"reconforge.identity_sessions, reconforge.currencies, reconforge.organizations, "
                    f"reconforge.identity_step_up_assertions, "
                    f"reconforge.emergency_access_requests, reconforge.emergency_access_permissions, "
                    f"reconforge.emergency_access_events, "
                    f"reconforge.legal_entities, reconforge.branches, reconforge.fiscal_periods, "
                    f"reconforge.ledger_accounts, "
                    f"reconforge.ledger_entries, reconforge.ledger_lines, reconforge.audit_events, "
                    f"reconforge.outbox_events, reconforge.close_periods, reconforge.close_tasks, "
                    f"reconforge.close_task_dependencies, reconforge.certification_records, "
                    f"reconforge.consolidation_close_periods, reconforge.consolidation_close_runs, "
                    f"reconforge.consolidation_close_effects, reconforge.consolidation_close_period_events, "
                    f"reconforge.consolidation_close_run_lines, reconforge.consolidation_close_effect_lines, "
                    f"reconforge.consolidation_ppa_artifacts, reconforge.consolidation_ownership_interests, "
                    f"reconforge.connector_writeback_intents TO {app_user}"
                )
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE ON reconforge.principal_scope_grants TO {app_user}"
                )
                admin.execute(
                    f"GRANT SELECT, INSERT ON reconforge.domain_workspaces TO {app_user}"
                )
                admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
        app_role = factory.connect()
        role = app_role.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        app_role.close()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live API identity test requires a non-superuser, non-BYPASSRLS application role")
        for tenant_id in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                connection.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, tenant_id),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,'workspace-a','Workspace A')",
                (tenant_a,),
            )
            master_data = PostgresMasterDataRepository(connection)
            master_data.upsert_currency(tenant_id=tenant_a, code="USD", name="US Dollar")
            master_data.upsert_organization(
                tenant_id=tenant_a,
                organization_id=organization_id,
                organization_code="ORG-A",
                name="API Organization",
                base_currency="USD",
            )
            connection.execute(
                "UPDATE reconforge.organizations SET application_workspace_id='workspace-a' "
                "WHERE tenant_id=%s AND id=%s",
                (tenant_a, organization_id),
            )
            ledger = PostgresLedgerRepository(connection)
            ledger.upsert_account(
                tenant_id=tenant_a,
                organization_id=organization_id,
                account_id="cash-a",
                account_code="1000",
                name="Cash",
            )
            repository = PostgresIdentityRepository(connection)
            repository.create_role(tenant_id=tenant_a, role_name="Admin")
            repository.create_permission(tenant_id=tenant_a, permission_name="db.read")
            repository.create_permission(tenant_id=tenant_a, permission_name="finance_core.read")
            repository.create_permission(tenant_id=tenant_a, permission_name="finance_core.manage")
            repository.create_permission(tenant_id=tenant_a, permission_name="finance_core.validate")
            repository.create_permission(tenant_id=tenant_a, permission_name="master_data.read")
            repository.create_permission(tenant_id=tenant_a, permission_name="master_data.manage")
            repository.create_permission(tenant_id=tenant_a, permission_name="audit.read")
            repository.create_permission(tenant_id=tenant_a, permission_name="audit.verify")
            repository.create_permission(tenant_id=tenant_a, permission_name="close.read")
            repository.create_permission(tenant_id=tenant_a, permission_name="close.manage")
            repository.create_permission(tenant_id=tenant_a, permission_name="connectors.writeback.propose")
            repository.create_permission(tenant_id=tenant_a, permission_name="connectors.writeback.approve")
            repository.create_permission(tenant_id=tenant_a, permission_name="connectors.writeback.dispatch")
            repository.create_permission(tenant_id=tenant_a, permission_name="connectors.writeback.reconcile")
            repository.create_permission(tenant_id=tenant_a, permission_name="roles.manage")
            repository.grant_permission(tenant_id=tenant_a, role_name="admin", permission_name="db.read")
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="finance_core.read",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="finance_core.manage",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="finance_core.validate",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="master_data.read",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="master_data.manage",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="audit.read",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="audit.verify",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="close.read",
            )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="close.manage",
            )
            for permission_name in (
                "connectors.writeback.propose",
                "connectors.writeback.approve",
                "connectors.writeback.dispatch",
                "connectors.writeback.reconcile",
            ):
                repository.grant_permission(
                    tenant_id=tenant_a,
                    role_name="admin",
                    permission_name=permission_name,
                )
            repository.grant_permission(
                tenant_id=tenant_a,
                role_name="admin",
                permission_name="roles.manage",
            )
            repository.create_user(
                tenant_id=tenant_a,
                user_id="api-user-a",
                username="Alice",
                password="Strong-password-123",
                role_name="admin",
            )
            repository.create_user(
                tenant_id=tenant_a,
                user_id="api-user-reviewer",
                username="Reviewer",
                password="Strong-password-123",
                role_name="admin",
            )
            repository.create_user(
                tenant_id=tenant_a,
                user_id="api-user-poster",
                username="Poster",
                password="Strong-password-123",
                role_name="admin",
            )
            scope_authority = PostgresScopeAuthorityRepository(connection)
            scope_authority.grant(
                tenant_id=tenant_a,
                grant_id="scope-user-workspace-a",
                principal_type="user",
                principal_id="api-user-a",
                scope_type="workspace",
                scope_id="workspace-a",
                actor_id="api-user-a",
            )
            scope_authority.grant(
                tenant_id=tenant_a,
                grant_id="scope-user-org-a",
                principal_type="user",
                principal_id="api-user-a",
                scope_type="organization",
                scope_id=organization_id,
                actor_id="api-user-a",
            )
            for user_id, suffix in (("api-user-reviewer", "reviewer"), ("api-user-poster", "poster")):
                scope_authority.grant(
                    tenant_id=tenant_a,
                    grant_id=f"scope-user-workspace-a-{suffix}",
                    principal_type="user",
                    principal_id=user_id,
                    scope_type="workspace",
                    scope_id="workspace-a",
                    actor_id="api-user-a",
                )
                scope_authority.grant(
                    tenant_id=tenant_a,
                    grant_id=f"scope-user-org-a-{suffix}",
                    principal_type="user",
                    principal_id=user_id,
                    scope_type="organization",
                    scope_id=organization_id,
                    actor_id="api-user-a",
                )
        from dataclasses import dataclass

        from reconforge.connectors.writeback_network import (
            WritebackNetworkExecutor,
            WritebackNetworkRegistration,
            WritebackNetworkResponse,
        )
        from tests.test_connector_writeback import _intent as writeback_intent

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        client = TestClient(app)
        headers = {"X-ReconForge-Tenant": tenant_a}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "alice", "password": "Strong-password-123"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {
            **headers,
            "X-ReconForge-Workspace": "workspace-a",
            "X-ReconForge-Organization": organization_id,
        }
        authenticated_headers = {
            **headers,
            "Authorization": f"Bearer {token}",
        }
        missing_scope = client.get(
            "/api/v1/finance-core/summary",
            headers={"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {token}"},
        )
        sibling_scope = client.get(
            "/api/v1/finance-core/summary",
            headers={
                "X-ReconForge-Tenant": tenant_a,
                "X-ReconForge-Workspace": "workspace-b",
                "Authorization": f"Bearer {token}",
            },
        )
        me_scoped = client.get("/api/v1/auth/me", headers=authenticated_headers)
        finance_before_step_up = client.post(
            "/api/v1/finance-core/accounts",
            headers=authenticated_headers,
            json={"organization_code": "ORG-A", "account_code": "4999", "name": "Denied before step-up"},
        )
        step_up = client.post(
            "/api/v1/auth/step-up",
            headers=authenticated_headers,
            json={"password": "Strong-password-123"},
        )
        assert finance_before_step_up.status_code == 403
        assert finance_before_step_up.json()["error"]["code"] == "step_up_required"
        assert step_up.status_code == 200
        assert step_up.json()["method"] == "password_reauthentication"
        from tests.test_consolidation_ppa import _request as ppa_request

        ppa_payload = ppa_request().to_dict()
        ppa_payload.pop("prepared_by", None)
        ppa_payload["approved_by"] = "api-user-reviewer"
        ppa_created = client.post(
            "/api/v1/consolidation-ppa",
            headers=authenticated_headers,
            json=ppa_payload,
        )
        assert ppa_created.status_code == 200, ppa_created.text
        assert ppa_created.json()["artifact"]["posted"] is False
        ppa_id = ppa_created.json()["artifact"]["id"]
        ppa_loaded = client.get(
            f"/api/v1/consolidation-ppa/{ppa_id}",
            headers=authenticated_headers,
        )
        assert ppa_loaded.status_code == 200, ppa_loaded.text
        assert ppa_loaded.json()["artifact"]["id"] == ppa_id
        ownership_payload = {
            "group_code": "GLOBAL-GROUP",
            "workspace": "default",
            "interest_id": "OWN-API-2026",
            "parent_entity_code": "PARENT",
            "subsidiary_entity_code": "SUB",
            "direct_ownership_percentage": "0.80",
            "effective_from": "2026-01-01",
            "effective_to": "",
            "version": "1.0.0",
            "source_digest": "b" * 64,
            "approved_by": "api-user-reviewer",
            "approved_at": "2026-01-01T00:00:00Z",
        }
        ownership_created = client.post(
            "/api/v1/consolidation-ownership/interests",
            headers=authenticated_headers,
            json=ownership_payload,
        )
        assert ownership_created.status_code == 200, ownership_created.text
        assert ownership_created.json()["source"]["kind"] == "postgresql-consolidation-ownership"
        ownership_resolved = client.get(
            "/api/v1/consolidation-ownership/effective",
            headers=authenticated_headers,
            params={"group_code": "GLOBAL-GROUP", "reporting_date": "2026-08-01"},
        )
        assert ownership_resolved.status_code == 200, ownership_resolved.text
        assert ownership_resolved.json()["interests"][0]["interest_id"] == "OWN-API-2026"
        sibling_ownership = client.get(
            "/api/v1/consolidation-ownership/effective",
            headers={**authenticated_headers, "X-ReconForge-Workspace": "workspace-b"},
            params={"group_code": "GLOBAL-GROUP", "reporting_date": "2026-08-01"},
        )
        assert sibling_ownership.status_code == 403
        assert sibling_ownership.json()["error"]["code"] == "workspace_scope_denied"
        close_period_payload = {
            "group_code": "GLOBAL-GROUP",
            "period_id": "2026-08",
            "reporting_currency": "USD",
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-08-31",
            "reporting_date": "2026-08-31",
        }
        close_period_created = client.post(
            "/api/v1/consolidation-close/periods",
            headers=authenticated_headers,
            json=close_period_payload,
        )
        assert close_period_created.status_code == 200, close_period_created.text
        assert close_period_created.json()["source"]["kind"] == "postgresql-consolidation-close"
        assert close_period_created.json()["period"]["workspace_id"] == "workspace-a"
        close_periods = client.get(
            "/api/v1/consolidation-close/periods",
            headers=authenticated_headers,
        )
        assert close_periods.status_code == 200, close_periods.text
        assert close_periods.json()["source"]["kind"] == "postgresql-consolidation-close"
        assert [item["period_name"] for item in close_periods.json()["periods"]] == ["2026-08"]
        from dataclasses import replace

        from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet
        from tests.test_sqlite_consolidation_close import _worksheet

        worksheet = prepare_consolidation_worksheet(replace(_worksheet().request, prepared_by="api-user-a"))
        prepared_run = client.post(
            "/api/v1/consolidation-close/runs",
            headers=authenticated_headers,
            json={"run_number": "RUN-API-001", "worksheet": worksheet.to_dict()},
        )
        assert prepared_run.status_code == 200, prepared_run.text
        assert prepared_run.json()["run"]["status"] == "Prepared"
        run_id = prepared_run.json()["run"]["id"]
        reviewer_login = client.post(
            "/api/v1/auth/login",
            headers={"X-ReconForge-Tenant": tenant_a},
            json={"username": "reviewer", "password": "Strong-password-123"},
        )
        assert reviewer_login.status_code == 200, reviewer_login.text
        reviewer_headers = {**headers, "Authorization": f"Bearer {reviewer_login.json()['access_token']}"}
        reviewer_step_up = client.post(
            "/api/v1/auth/step-up",
            headers=reviewer_headers,
            json={"password": "Strong-password-123"},
        )
        assert reviewer_step_up.status_code == 200, reviewer_step_up.text
        poster_login = client.post(
            "/api/v1/auth/login",
            headers={"X-ReconForge-Tenant": tenant_a},
            json={"username": "poster", "password": "Strong-password-123"},
        )
        assert poster_login.status_code == 200, poster_login.text
        poster_headers = {**headers, "Authorization": f"Bearer {poster_login.json()['access_token']}"}
        poster_step_up = client.post(
            "/api/v1/auth/step-up",
            headers=poster_headers,
            json={"password": "Strong-password-123"},
        )
        assert poster_step_up.status_code == 200, poster_step_up.text

        connector_id = "reference-rest-writeback"
        payload_bytes = b'{"amount":"10.00","currency":"USD","reference":"live-payment-1"}'
        import hashlib
        import json

        writeback_payload = writeback_intent(
            intent_id=f"intent-live-{token}",
            tenant_id=tenant_a,
            workspace_id="workspace-a",
            connector_id=connector_id,
            operation="payment.create",
            payload_digest=hashlib.sha256(payload_bytes).hexdigest(),
            requested_by="api-user-a",
        ).model_dump(mode="json")

        @dataclass
        class Transport:
            calls: int = 0

            def post(
                self,
                endpoint: str,
                *,
                headers: dict[str, str],
                body: bytes,
                timeout_seconds: int,
                maximum_response_bytes: int,
            ) -> WritebackNetworkResponse:
                del endpoint, headers, body, timeout_seconds, maximum_response_bytes
                self.calls += 1
                provider = {
                    "accepted": True,
                    "idempotency_key": writeback_payload["idempotency_key"],
                    "provider_reference": "live-provider-1",
                }
                response_digest = hashlib.sha256(
                    json.dumps(provider, sort_keys=True, separators=(",", ":")).encode("ascii")
                ).hexdigest()
                return WritebackNetworkResponse(
                    status=200,
                    body=json.dumps({**provider, "response_digest": response_digest}).encode("ascii"),
                )

        class Payloads:
            def resolve(self, intent: object) -> bytes:
                del intent
                return payload_bytes

        class Secrets:
            def resolve(self, reference: str) -> bytes:
                assert reference == f"vault://{tenant_a}/writeback-token"
                return b"synthetic-live-writeback-token"

        transport = Transport()
        app.state.writeback_network_executor = WritebackNetworkExecutor(
            transport,
            payload_resolver=Payloads(),
            secret_resolver=Secrets(),
        )
        app.state.writeback_network_registrations = {
            connector_id: WritebackNetworkRegistration.model_validate(
                {
                    "registration_schema": "writeback-network-registration-v1",
                    "connector_id": connector_id,
                    "version": "1.0.0",
                    "endpoint": "https://api.example.test/v1/writeback",
                    "egress_destinations": ("https://api.example.test/v1/writeback",),
                        "credential_reference": f"vault://{tenant_a}/writeback-token",
                    "allowed_operations": frozenset({"payment.create"}),
                    "feature_enabled": True,
                    "synthetic_sandbox": True,
                }
            )
        }
        proposed_writeback = client.post(
            "/api/v1/connectors/writeback/intents",
            headers=authenticated_headers,
            json=writeback_payload,
        )
        assert proposed_writeback.status_code == 200, proposed_writeback.text
        approved_writeback = client.post(
            f"/api/v1/connectors/writeback/intents/{writeback_payload['intent_id']}/approve",
            headers=reviewer_headers,
            json={
                "assurance": "mfa",
                "reason": "Live synthetic provider review.",
                "tenant_id": tenant_a,
                "workspace_id": "workspace-a",
            },
        )
        assert approved_writeback.status_code == 200, approved_writeback.text
        dispatched_writeback = client.post(
            f"/api/v1/connectors/writeback/intents/{writeback_payload['intent_id']}/dispatch",
            headers=reviewer_headers,
            json={"tenant_id": tenant_a, "workspace_id": "workspace-a", "expected_version": 2},
        )
        assert dispatched_writeback.status_code == 200, dispatched_writeback.text
        assert dispatched_writeback.json()["intent"]["status"] == "acknowledged"
        assert dispatched_writeback.json()["network_dispatch"] == "acknowledged"
        assert transport.calls == 1
        approved_run = client.post(
            f"/api/v1/consolidation-close/runs/{run_id}/approve",
            headers=reviewer_headers,
            json={"expected_version": 1, "reason": "Independent live worksheet review."},
        )
        assert approved_run.status_code == 200, approved_run.text
        assert approved_run.json()["run"]["status"] == "Approved"
        posted_run = client.post(
            f"/api/v1/consolidation-close/runs/{run_id}/post",
            headers=poster_headers,
            json={"expected_version": 2, "reason": "Live synthetic control journal posting."},
        )
        assert posted_run.status_code == 200, posted_run.text
        assert posted_run.json()["run"]["status"] == "Posted"
        locked_period = client.post(
            f"/api/v1/consolidation-close/periods/{close_period_created.json()['period']['id']}/lock",
            headers=reviewer_headers,
            json={"expected_version": 1, "reason": "Live synthetic period lock."},
        )
        assert locked_period.status_code == 200, locked_period.text
        assert locked_period.json()["period"]["status"] == "Locked"
        reopened_period = client.post(
            f"/api/v1/consolidation-close/periods/{close_period_created.json()['period']['id']}/reopen",
            headers=authenticated_headers,
            json={"expected_version": 2, "reason": "Live synthetic independent reopen."},
        )
        assert reopened_period.status_code == 200, reopened_period.text
        assert reopened_period.json()["period"]["status"] == "Open"
        close_sibling = client.get(
            "/api/v1/consolidation-close/periods",
            headers={**authenticated_headers, "X-ReconForge-Workspace": "workspace-b"},
        )
        assert close_sibling.status_code == 403
        assert close_sibling.json()["error"]["code"] == "workspace_scope_denied"
        missing_scope = client.get(
            "/api/v1/finance-core/summary",
            headers={"X-ReconForge-Tenant": tenant_a, "Authorization": f"Bearer {token}"},
        )
        sibling_scope = client.get(
            "/api/v1/finance-core/summary",
            headers={
                "X-ReconForge-Tenant": tenant_a,
                "X-ReconForge-Workspace": "workspace-b",
                "Authorization": f"Bearer {token}",
            },
        )
        assert missing_scope.status_code == 400
        assert missing_scope.json()["error"]["code"] == "workspace_scope_required"
        assert sibling_scope.status_code == 403
        assert sibling_scope.json()["error"]["code"] == "workspace_scope_denied"
        assert me_scoped.status_code == 200
        assert me_scoped.json()["authorized_scopes"]["workspaces"] == ["workspace-a"]
        assert me_scoped.json()["authorized_scopes"]["organizations"] == [organization_id]
        authorized = client.get(
            "/api/v1/roles",
            headers=authenticated_headers,
        )
        finance_summary = client.get(
            "/api/v1/finance-core/summary",
            headers={**headers, "Authorization": f"Bearer {token}"},
        )
        finance_account = client.post(
            "/api/v1/finance-core/accounts",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={"organization_code": "ORG-A", "account_code": "4000", "name": "Revenue"},
        )
        finance_entry = client.post(
            "/api/v1/finance-core/entries",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={
                "entry_number": "JE-API-001",
                "organization_code": "ORG-A",
                "posting_date": "2026-07-23",
                "description": "Live server ledger entry",
                "currency_code": "USD",
                "lines": [
                    {"account_code": "1000", "debit": "100.00", "credit": "0"},
                    {"account_code": "4000", "debit": "0", "credit": "100.00"},
                ],
            },
        )
        master_currency = client.post(
            "/api/v1/master-data/currencies",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={"code": "USD", "name": "US Dollar", "minor_units": 2},
        )
        master_organization = client.post(
            "/api/v1/master-data/organizations",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={
                "organization_code": "ORG-A",
                "name": "API Organization Updated",
                "base_currency": "USD",
            },
        )
        master_entity = client.post(
            "/api/v1/master-data/entities",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={
                "organization_code": "ORG-A",
                "entity_code": "LE-API",
                "name": "API Legal Entity",
                "currency_code": "USD",
            },
        )
        master_branch = client.post(
            "/api/v1/master-data/branches",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={
                "organization_code": "ORG-A",
                "branch_code": "BR-API",
                "name": "API Branch",
                "entity_code": "LE-API",
            },
        )
        master_period = client.post(
            "/api/v1/master-data/periods",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={"name": "2026-07", "start_date": "2026-07-01", "end_date": "2026-07-31"},
        )
        master_period_status = client.post(
            f"/api/v1/master-data/periods/{master_period.json()['period']['id']}/status",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={"status": "Soft Closed"},
        )
        server_trial_balance = client.get(
            "/api/v1/finance-core/trial-balance",
            headers={**headers, "Authorization": f"Bearer {token}"},
            params={
                "period_id": master_period.json()["period"]["id"],
                "organization": "ORG-A",
                "entity": "",
            },
        )
        close_period = client.post(
            "/api/v1/close/periods",
            headers={**headers, "Authorization": f"Bearer {token}"},
            json={
                "fiscal_period_id": master_period.json()["period"]["id"],
                "organization_code": "ORG-A",
            },
        )
        close_period_id = close_period.json()["period"]["id"]
        close_tasks = client.get(
            "/api/v1/close/tasks",
            headers={**headers, "Authorization": f"Bearer {token}"},
            params={"period_id": close_period_id},
        )
        close_readiness = client.get(
            f"/api/v1/close/periods/{close_period_id}/readiness",
            headers={**headers, "Authorization": f"Bearer {token}"},
        )
        audit_events = client.get(
            "/api/v1/audit/events",
            headers={**headers, "Authorization": f"Bearer {token}"},
        )
        audit_verify = client.get(
            "/api/v1/audit/verify",
            headers={**headers, "Authorization": f"Bearer {token}"},
        )
        master_snapshot = client.get(
            "/api/v1/master-data/snapshot",
            headers={**headers, "Authorization": f"Bearer {token}"},
        )
        cross_tenant = client.get(
            "/api/v1/auth/me",
            headers={"X-ReconForge-Tenant": tenant_b, "Authorization": f"Bearer {token}"},
        )
        assert authorized.status_code == 409
        assert authorized.json()["error"]["code"] == "local_identity_surface_disabled"
        assert finance_summary.status_code == 200
        assert finance_account.status_code == 200
        assert finance_entry.status_code == 200
        assert finance_entry.json()["entry"]["status"] == "Posted"
        assert master_currency.status_code == 200
        assert master_organization.status_code == 200
        assert master_entity.status_code == 200
        assert master_branch.status_code == 200
        assert master_period.status_code == 200
        assert master_period_status.status_code == 200
        assert server_trial_balance.status_code == 200
        assert server_trial_balance.json()["totals"]["balanced"] is True
        assert close_period.status_code == 200
        assert close_tasks.status_code == 200
        assert len(close_tasks.json()["tasks"]) == 5
        assert close_readiness.status_code == 200
        assert audit_events.status_code == 200
        assert audit_events.json()["source"]["kind"] == "postgresql-ledger-control"
        assert audit_events.json()["events"]
        assert audit_verify.status_code == 200
        assert audit_verify.json()["ok"] is True
        assert master_snapshot.status_code == 200
        assert master_snapshot.json()["source"]["kind"] == "postgres-master-data"
        assert len(master_snapshot.json()["periods"]) == 1
        assert cross_tenant.status_code == 401
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "ALTER TABLE reconforge.identity_step_up_assertions "
                    "DISABLE TRIGGER identity_step_up_assertions_append_only"
                )
                admin.execute(
                    "ALTER TABLE reconforge.principal_scope_grants "
                    "DISABLE TRIGGER principal_scope_grants_guard"
                )
                admin.execute(
                    "ALTER TABLE reconforge.consolidation_ppa_artifacts "
                    "DISABLE TRIGGER consolidation_ppa_artifact_guard"
                )
                admin.execute(
                    "DELETE FROM reconforge.consolidation_ppa_artifacts WHERE tenant_id IN (%s, %s)",
                    (tenant_a, tenant_b),
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
                admin.execute(
                    "ALTER TABLE reconforge.consolidation_ppa_artifacts "
                    "ENABLE TRIGGER consolidation_ppa_artifact_guard"
                )
                admin.execute(
                    "ALTER TABLE reconforge.principal_scope_grants "
                    "ENABLE TRIGGER principal_scope_grants_guard"
                )
                admin.execute(
                    "ALTER TABLE reconforge.identity_step_up_assertions "
                    "ENABLE TRIGGER identity_step_up_assertions_append_only"
                )
        except psycopg.Error:
            pass
        admin.close()
