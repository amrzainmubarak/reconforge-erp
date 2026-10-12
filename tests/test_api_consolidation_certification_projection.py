"""Fail-closed projection contract for consolidation certification responses."""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from reconforge.api.routes import consolidation_close as routes
from reconforge.auth.models import LocalUser


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )


def _certification() -> dict[str, object]:
    return {
        "id": "CERT-1",
        "object_type": "consolidation_close_run",
        "object_id": "RUN-1",
        "period_name": "2026-08",
        "entity_code": "GLOBAL",
        "status": "Prepared",
        "prepared_by": "controller",
        "reviewed_by": "",
        "note": "synthetic",
        "evidence_digest": "a" * 64,
        "created_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:00Z",
        "future_certification_field": "must-not-escape",
    }


def test_local_certification_response_drops_future_fields(monkeypatch) -> None:
    class FakeRepository:
        def prepare_certification(self, *_args, **_kwargs):
            return _certification()

    monkeypatch.setattr(routes, "server_consolidation_close_enabled", lambda _request: False)
    monkeypatch.setattr(routes, "_repository", lambda _connection: FakeRepository())

    result = routes.prepare_certification(
        "RUN-1",
        _request(),
        SimpleNamespace(note="synthetic"),
        LocalUser(id="user-a", username="controller", display_name="Controller"),
        object(),
    )

    assert result["certification"]["status"] == "Prepared"
    assert result["source"] == {"kind": "sqlite-consolidation-close"}
    assert "future_certification_field" not in str(result)


def test_server_certification_response_drops_future_fields(monkeypatch) -> None:
    class FakeScope:
        tenant_id = "tenant-a"
        workspace_id = "workspace-a"

    def fake_execute(_request, operation):
        class FakeRepository:
            def get_run(self, *_args, **_kwargs):
                return {"workspace_id": "workspace-a"}

            def get_certification(self, *_args, **_kwargs):
                return _certification()

        return operation(FakeRepository(), "tenant-a")

    monkeypatch.setattr(routes, "server_consolidation_close_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_server_scope", lambda *_args, **_kwargs: FakeScope())
    monkeypatch.setattr(routes, "execute_postgres_consolidation_close", fake_execute)

    result = routes.get_certification(
        "RUN-1",
        _request(),
        LocalUser(id="user-a", username="controller", display_name="Controller"),
        object(),
    )

    assert result["certification"]["evidence_digest"] == "a" * 64
    assert result["source"] == {"kind": "postgresql-consolidation-close", "server_mode": True}
    assert "future_certification_field" not in str(result)
