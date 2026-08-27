"""Fail-closed projection contract for legacy audit verification responses."""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from reconforge.api.routes import audit as routes
from reconforge.auth.models import LocalUser


def _request(*, server: bool) -> Request:
    app_state = SimpleNamespace()
    if server:
        app_state.postgres_ledger_factory = object()
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=app_state),
        }
    )


def test_local_audit_verification_drops_future_fields(monkeypatch) -> None:
    class Result:
        ok = False
        checked_events = 2
        head_hash = "h" * 64
        issues = [
            SimpleNamespace(
                sequence=2,
                message="synthetic",
                future_issue_field="must-not-escape",
            )
        ]

    monkeypatch.setattr(routes, "server_ledger_enabled", lambda _request: False)
    monkeypatch.setattr(routes, "verify_audit_events", lambda _connection: Result())

    result = routes.audit_verify(
        _request(server=False),
        LocalUser(id="user-a", username="alice", display_name="Alice"),
        object(),
    )

    assert result == {
        "ok": False,
        "checked_events": 2,
        "head_hash": "h" * 64,
        "issues": [{"sequence": 2, "message": "synthetic"}],
    }
    assert "must-not-escape" not in str(result)


def test_server_audit_verification_drops_future_fields(monkeypatch) -> None:
    def fake_execute(_request, _operation):
        return {
            "ok": True,
            "checked_events": 3,
            "head_hash": "z" * 64,
            "issues": [],
            "future_server_field": "must-not-escape",
        }

    monkeypatch.setattr(routes, "server_ledger_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_enforce_server_audit_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "execute_postgres_ledger", fake_execute)

    result = routes.audit_verify(
        _request(server=True),
        LocalUser(id="user-a", username="alice", display_name="Alice"),
        None,
    )

    assert result == {
        "ok": True,
        "checked_events": 3,
        "head_hash": "z" * 64,
        "issues": [],
    }
    assert "must-not-escape" not in str(result)
