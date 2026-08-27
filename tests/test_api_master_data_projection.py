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
