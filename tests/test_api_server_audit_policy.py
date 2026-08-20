from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from reconforge.api.routes import audit as routes
from reconforge.auth.models import LocalUser


def _request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})


class _Repository:
    def list_audit_events(self, **values: object) -> list[dict[str, object]]:
        assert values == {"tenant_id": "tenant-a", "limit": None}
        return [{"id": "audit-1"}]

    def verify_audit_events(self, **values: object) -> dict[str, object]:
        assert values == {"tenant_id": "tenant-a"}
        return {"ok": True, "checked_events": 1}


def test_server_legacy_audit_views_recheck_tenant_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    policy_calls: list[dict[str, object]] = []
    repository = _Repository()

    monkeypatch.setattr(routes, "server_ledger_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "request_tenant_id", lambda _request: "tenant-a")
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

    events = routes.audit_events(request, user, limit=None, connection=None)
    verification = routes.audit_verify(request, user, connection=None)

    assert events["events"] == [{"id": "audit-1"}]
    assert verification["ok"] is True
    assert policy_calls == [
        {"permission": "audit.read", "tenant_id": "tenant-a"},
        {"permission": "audit.verify", "tenant_id": "tenant-a"},
    ]
