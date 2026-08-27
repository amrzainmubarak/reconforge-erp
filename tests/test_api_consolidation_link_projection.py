"""Fail-closed projection contract for consolidation evidence-link responses."""

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


def test_intercompany_link_response_drops_future_fields(monkeypatch) -> None:
    link = {
        "tenant_id": "tenant-a",
        "id": "LINK-1",
        "run_id": "RUN-1",
        "artifact_id": "ART-1",
        "artifact_result_digest": "a" * 64,
        "matched_elimination_ids": ["ELIM-1"],
        "unresolved_count": 0,
        "link_digest": "b" * 64,
        "actor": "reviewer",
        "created_at": "2026-08-27T00:00:00Z",
        "future_link_field": "must-not-escape",
    }

    def fake_execute(_request, _operation):
        return link

    class Scope:
        tenant_id = "tenant-a"
        workspace_id = "workspace-a"

    monkeypatch.setattr(routes, "server_consolidation_close_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_server_scope", lambda *_args, **_kwargs: Scope())
    monkeypatch.setattr(routes, "enforce_server_scoped_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "execute_postgres_consolidation_close", fake_execute)

    result = routes.attach_intercompany_evidence(
        "RUN-1",
        _request(),
        SimpleNamespace(artifact_id="ART-1"),
        LocalUser(id="user-a", username="reviewer", display_name="Reviewer"),
    )

    assert result["link"] == {
        "tenant_id": "tenant-a",
        "id": "LINK-1",
        "run_id": "RUN-1",
        "artifact_id": "ART-1",
        "artifact_result_digest": "a" * 64,
        "matched_elimination_ids": ["ELIM-1"],
        "unresolved_count": 0,
        "link_digest": "b" * 64,
        "actor": "reviewer",
        "created_at": "2026-08-27T00:00:00Z",
    }
    assert result["source"] == {"kind": "postgresql-consolidation-close", "server_mode": True}
    assert "future_link_field" not in str(result)
