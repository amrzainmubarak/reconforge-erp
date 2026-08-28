"""Tests for API dependencies (idempotency keys & cursor pagination)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request

import reconforge.api.dependencies as dependencies_module
from reconforge.api.dependencies import (
    _server_policy_audit_sink,
    get_cursor_pagination,
    get_idempotency_key,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext
from reconforge.platform.common import ServerPrincipal


def test_cursor_pagination_defaults() -> None:
    params = get_cursor_pagination()
    assert params.cursor is None
    assert params.limit == 50


def test_cursor_pagination_custom() -> None:
    params = get_cursor_pagination(cursor="eyJsYXN0X2lkIjoxMH0=", limit=100)
    assert params.cursor == "eyJsYXN0X2lkIjoxMH0="
    assert params.limit == 100


def test_cursor_pagination_rejects_blank_cursor() -> None:
    with pytest.raises(APIError) as exc_info:
        get_cursor_pagination(cursor="   ", limit=50)
    assert exc_info.value.code == "invalid_cursor"


def test_idempotency_key_absent() -> None:
    assert get_idempotency_key(None, None) is None


def test_idempotency_key_standard_header() -> None:
    key = get_idempotency_key("repeat-repeat-repeat", None)
    assert key == "repeat-repeat-repeat"


def test_idempotency_key_custom_header_alias() -> None:
    key = get_idempotency_key(None, "x-key-999")
    assert key == "x-key-999"


def test_idempotency_key_rejects_blank() -> None:
    with pytest.raises(APIError) as exc_info:
        get_idempotency_key("   ", None)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "invalid_idempotency_key"


@pytest.mark.parametrize("dependency_mode", ["all", "any"])
def test_server_permission_dependency_binds_authenticated_tenant_scope(
    monkeypatch: pytest.MonkeyPatch,
    dependency_mode: str,
) -> None:
    app = FastAPI()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users",
            "headers": [(b"x-reconforge-tenant", b"tenant-a")],
            "app": app,
        }
    )
    principal = ServerPrincipal(
        user=LocalUser(id="user-a", username="alice", display_name="Alice"),
        permissions=frozenset({"db.read"}),
        authorized_tenant_ids=frozenset({"tenant-b"}),
    )
    request.state.server_principal = principal
    monkeypatch.setattr(dependencies_module, "server_identity_enabled", lambda _request: True)
    decisions = []
    monkeypatch.setattr(
        dependencies_module,
        "audit_policy_decision",
        lambda decision, **_kwargs: decisions.append(decision),
    )

    dependency = (
        require_permission("db.read")
        if dependency_mode == "all"
        else require_any_permission({"db.read"})
    )
    with pytest.raises(APIError) as denied:
        dependency(request, current_user=principal.user, connection=None)

    assert denied.value.status_code == 403
    assert denied.value.code == "permission_denied"
    assert len(decisions) == 1
    assert decisions[0].reason_code == "tenant_scope_denied"


def test_server_policy_audit_sink_persists_only_closed_redacted_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class Repository:
        def append(self, **kwargs: object) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(dependencies_module, "server_audit_administration_enabled", lambda _request: True)
    monkeypatch.setattr(
        dependencies_module,
        "execute_postgres_policy_audit",
        lambda _request, operation: operation(Repository(), "tenant-a"),
    )
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="sensitive-user",
            username="alice",
            user_permissions={"finance_core.validate"},
            tenant_id="tenant-secret",
            workspace_id="workspace-secret",
        ),
        required_permission="finance_core.validate",
    )
    sink = _server_policy_audit_sink(object(), actor_id="sensitive-user")
    assert sink is not None

    from reconforge.auth.policy import audit_policy_decision

    evidence = audit_policy_decision(
        decision,
        actor_id="sensitive-user",
        required_permissions=frozenset({"finance_core.validate"}),
        surface="POST /api/v1/finance-core/journals/validate",
        request_id="request-secret",
        context=PolicyEvaluationContext(
            user_id="sensitive-user",
            username="alice",
            user_permissions={"finance_core.validate"},
            tenant_id="tenant-secret",
            workspace_id="workspace-secret",
        ),
        audit_sink=sink,
    )

    assert len(captured) == 1
    event = captured[0]
    assert event["actor_user_id"] == "sensitive-user"
    assert event["object_type"] == "authorization.policy_decision"
    assert event["object_id"] == evidence.decision_digest
    assert event["after_hash"] == evidence.decision_digest
    metadata = event["metadata"]
    assert isinstance(metadata, dict)
    serialized = json.dumps(metadata, sort_keys=True)
    assert "tenant-secret" not in serialized
    assert "workspace-secret" not in serialized
    assert "request-secret" not in serialized
    assert metadata["policy_decision_evidence"] == evidence.to_dict()
