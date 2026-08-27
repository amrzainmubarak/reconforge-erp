"""Fail-closed response projection contract for master-data summaries."""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from reconforge.api.routes import master_data as routes
from reconforge.auth.models import LocalUser


def test_master_data_summary_route_drops_future_local_service_fields(monkeypatch) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )
    summary = {
        "workspace": "default",
        "organizations": 1,
        "legal_entities": 1,
        "branches": 1,
        "periods": 1,
        "active_currencies": 1,
        "source": {"kind": "local-sqlite-master-data"},
        "unsupported_collections": [],
        "unknown_summary_field": "must-not-escape",
    }

    class FakeService:
        def __init__(self, _connection) -> None:
            pass

        def summary(self, **_kwargs):
            return SimpleNamespace(to_dict=lambda: summary)

    monkeypatch.setattr(routes, "server_master_data_enabled", lambda _request: False)
    monkeypatch.setattr(routes, "MasterDataService", FakeService)

    result = routes.summary(request, LocalUser(id="user-a", username="alice", display_name="Alice"), object())

    assert result == {
        "summary": {
            "workspace": "default",
            "organizations": 1,
            "legal_entities": 1,
            "branches": 1,
            "periods": 1,
            "active_currencies": 1,
            "source": {"kind": "local-sqlite-master-data"},
            "unsupported_collections": [],
        }
    }


def test_master_data_registry_reconciliation_drops_future_nested_fields(monkeypatch) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )
    reconciliation = {
        "schema_version": 1,
        "scope": "workspace:default",
        "status": "consistent",
        "ok": True,
        "registry": {
            "registry_version": "iso-2026-01-01",
            "digest": "a" * 64,
            "future_registry_field": "must-not-escape",
        },
        "master_currency_count": 1,
        "active_master_currency_count": 1,
        "input_digest": "b" * 64,
        "issues": [
            {
                "code": "X",
                "currency_code": "USD",
                "message": "synthetic",
                "future_issue_field": "must-not-escape",
            }
        ],
        "binding": {
            "status": "current",
            "registry_version": "iso-2026-01-01",
            "registry_digest": "c" * 64,
            "bound_at": "2026-08-27T00:00:00Z",
            "bound_by": "controller",
            "future_binding_field": "must-not-escape",
        },
        "future_top_level_field": "must-not-escape",
    }

    class FakeService:
        def __init__(self, _connection) -> None:
            pass

        def currency_registry_reconciliation(self, **_kwargs):
            return reconciliation

    monkeypatch.setattr(routes, "server_master_data_enabled", lambda _request: False)
    monkeypatch.setattr(routes, "MasterDataService", FakeService)

    result = routes.currency_registry_reconciliation(
        request,
        LocalUser(id="user-a", username="alice", display_name="Alice"),
        object(),
    )

    payload = result["reconciliation"]
    assert payload["registry"] == {"registry_version": "iso-2026-01-01", "digest": "a" * 64}
    assert payload["issues"] == [{"code": "X", "currency_code": "USD", "message": "synthetic"}]
    assert payload["binding"]["status"] == "current"
    assert "must-not-escape" not in str(payload)
