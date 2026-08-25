from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.auth.models import LocalUser


class _AccountRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_reconciliations(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list", values))
        return [{"id": "rec-a", "status": "Draft", "workspace": "workspace-a"}]

    def create_reconciliation(self, **values: object) -> dict[str, object]:
        self.calls.append(("create", values))
        return {"id": "rec-a", "status": "Draft", **values}

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, object]:
        self.calls.append(("get", {"reconciliation_id": reconciliation_id}))
        return {"id": reconciliation_id, "status": "Draft"}

    def prepare(self, **values: object) -> dict[str, object]:
        self.calls.append(("prepare", values))
        return {"id": str(values["reconciliation_id"]), "status": "Prepared"}

    def submit(self, reconciliation_id: str, **values: object) -> dict[str, object]:
        self.calls.append(("submit", {"reconciliation_id": reconciliation_id, **values}))
        return {"id": reconciliation_id, "status": "In Review"}

    def review(self, reconciliation_id: str, **values: object) -> dict[str, object]:
        self.calls.append(("review", {"reconciliation_id": reconciliation_id, **values}))
        return {"id": reconciliation_id, "status": "Reviewed"}

    def complete(self, reconciliation_id: str, **values: object) -> dict[str, object]:
        self.calls.append(("complete", {"reconciliation_id": reconciliation_id, **values}))
        return {"id": reconciliation_id, "status": "Complete"}


def test_server_accounts_routes_use_scoped_postgres_adapter_and_bind_reviewer(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.accounts as account_routes

    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    permissions = frozenset({"accounts.read", "accounts.prepare", "accounts.review", "accounts.complete"})
    repository = _AccountRepository()
    policy_checks: list[dict[str, object]] = []

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "server-token" else None

    def execute(request: Any, operation: Any) -> Any:
        assert request_tenant_id(request) == "tenant-a"
        return operation(repository, "tenant-a")

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)
    monkeypatch.setattr(
        account_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
    )
    monkeypatch.setattr(
        account_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: policy_checks.append(kwargs),
    )
    monkeypatch.setattr(
        account_routes,
        "enforce_server_scoped_permissions",
        lambda _request, **kwargs: policy_checks.append(kwargs),
    )
    monkeypatch.setattr(account_routes, "execute_postgres_accounts", execute)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://accounts.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {
        "X-ReconForge-Tenant": "tenant-a",
        "X-ReconForge-Workspace": "workspace-a",
        "Authorization": "Bearer server-token",
    }

    created = client.post(
        "/api/v1/accounts/reconciliations",
        headers=headers,
        json={
            "period_name": "2026-08",
            "entity_code": "ENTITY",
            "account_code": "1000",
            "account_name": "Cash",
            "balance": "125.25",
            "preparer": "spoofed-preparer",
            "reviewer": "spoofed-reviewer",
        },
    )
    listed = client.get("/api/v1/accounts/reconciliations", headers=headers)
    reviewed = client.post(
        "/api/v1/accounts/reconciliations/rec-a/review",
        headers=headers,
        json={"reviewer": "spoofed-reviewer"},
    )

    assert created.status_code == 200, created.text
    assert listed.status_code == 200, listed.text
    assert reviewed.status_code == 200, reviewed.text
    create_values = next(values for name, values in repository.calls if name == "create")
    review_values = next(values for name, values in repository.calls if name == "review")
    assert create_values["workspace"] == "workspace-a"
    assert create_values["actor_label"] == "user-a"
    assert create_values["preparer"] == ""
    assert review_values["reviewer"] == "user-a"
    assert review_values["actor_label"] == "user-a"
    assert any(check.get("permission") == "accounts.review" for check in policy_checks)
    assert any(check.get("permissions") == permissions for check in policy_checks)
