from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from starlette.requests import Request

from reconforge.api.routes import finance_core as routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.models import LocalUser


def _request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})


class _Repository:
    def summary(self, **_values: object) -> dict[str, object]:
        return {
            "accounts": 0,
            "draft_entries": 0,
            "posted_entries": 0,
            "source": {"kind": "postgresql-ledger-control"},
            "unsupported_collections": [],
        }

    def list_accounts(self, **_values: object) -> list[dict[str, object]]:
        return []

    def organization_by_code(self, **_values: object) -> dict[str, object]:
        return {"id": "org-a", "active": True}

    def trial_balance(self, **_values: object) -> dict[str, object]:
        return {"balances": []}

    def list_entries(self, **_values: object) -> list[dict[str, object]]:
        return []

    def get_entry(self, **_values: object) -> dict[str, object]:
        return {"id": "entry-a"}


def test_legacy_finance_reads_recheck_tenant_policy_before_adapter(monkeypatch: Any) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    policy_calls: list[dict[str, object]] = []
    repository = _Repository()

    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: False)
    monkeypatch.setattr(routes, "server_ledger_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant-a", "workspace-a"))
    monkeypatch.setattr(
        routes,
        "enforce_server_tenant_permission",
        lambda _request, **values: policy_calls.append(values),
    )
    monkeypatch.setattr(
        routes,
        "execute_postgres_ledger",
        lambda _request, operation: operation(repository, "tenant-a"),
    )

    routes.summary(request, user, None, workspace="default")
    routes.list_accounts(request, user, None, workspace="default", limit=100, offset=0)
    routes.trial_balance(
        request,
        period_id="2026-Q3",
        organization="ORG-A",
        entity="",
        current_user=user,
        connection=None,
        workspace="default",
    )
    routes.list_entries(request, user, None, workspace="default", limit=100, offset=0)
    routes.get_entry(request, "entry-a", user, None)

    assert policy_calls == [
        {"permission": "finance_core.read", "tenant_id": "tenant-a"},
        {"permission": "finance_core.read", "tenant_id": "tenant-a"},
        {"permission": "finance_core.read", "tenant_id": "tenant-a"},
        {"permission": "finance_core.read", "tenant_id": "tenant-a"},
        {"permission": "finance_core.read", "tenant_id": "tenant-a"},
    ]
