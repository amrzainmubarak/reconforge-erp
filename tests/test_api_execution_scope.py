from __future__ import annotations

import pytest
from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import (
    AuthenticatedServerRequest,
    request_execution_scope,
    server_principal_from_authentication,
)
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_scope_authority import PrincipalScopeSnapshot
from reconforge.platform.common import ServerPrincipal


def _request(headers: dict[str, str], principal: ServerPrincipal | None) -> Request:
    encoded = [(key.lower().encode("ascii"), value.encode("ascii")) for key, value in headers.items()]
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": encoded})
    if principal is not None:
        request.state.server_principal = principal
    return request


def _principal() -> ServerPrincipal:
    return ServerPrincipal(
        user=LocalUser(id="user-a", username="alice", display_name="Alice"),
        permissions=frozenset({"reconciliation.read"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
        authorized_organization_ids=frozenset({"organization-a"}),
        authorized_legal_entity_ids=frozenset({"entity-a"}),
    )


def test_execution_scope_requires_authenticated_granted_workspace() -> None:
    with pytest.raises(APIError) as missing_auth:
        request_execution_scope(
            _request({"X-ReconForge-Tenant": "tenant-a", "X-ReconForge-Workspace": "workspace-a"}, None)
        )
    assert missing_auth.value.code == "auth_required"
    with pytest.raises(APIError) as missing_workspace:
        request_execution_scope(_request({"X-ReconForge-Tenant": "tenant-a"}, _principal()))
    assert missing_workspace.value.code == "workspace_scope_required"
    with pytest.raises(APIError) as sibling:
        request_execution_scope(
            _request(
                {"X-ReconForge-Tenant": "tenant-a", "X-ReconForge-Workspace": "workspace-b"},
                _principal(),
            )
        )
    assert sibling.value.code == "workspace_scope_denied"


def test_execution_scope_composes_workspace_organization_and_entity() -> None:
    scope = request_execution_scope(
        _request(
            {
                "X-ReconForge-Tenant": "tenant-a",
                "X-ReconForge-Workspace": "workspace-a",
                "X-ReconForge-Organization": "organization-a",
                "X-ReconForge-Legal-Entity": "entity-a",
            },
            _principal(),
        )
    )
    assert scope.workspace_id == "workspace-a"
    assert scope.organization_id == "organization-a"
    assert scope.legal_entity_id == "entity-a"


def test_execution_scope_rejects_entity_without_organization_and_sibling_entity() -> None:
    with pytest.raises(APIError) as missing_parent:
        request_execution_scope(
            _request(
                {
                    "X-ReconForge-Tenant": "tenant-a",
                    "X-ReconForge-Workspace": "workspace-a",
                    "X-ReconForge-Legal-Entity": "entity-a",
                },
                _principal(),
            )
        )
    assert missing_parent.value.code == "organization_scope_required"
    with pytest.raises(APIError) as sibling:
        request_execution_scope(
            _request(
                {
                    "X-ReconForge-Tenant": "tenant-a",
                    "X-ReconForge-Workspace": "workspace-a",
                    "X-ReconForge-Organization": "organization-a",
                    "X-ReconForge-Legal-Entity": "entity-b",
                },
                _principal(),
            )
        )
    assert sibling.value.code == "entity_scope_denied"


def test_authenticated_scope_snapshot_is_bound_to_server_principal() -> None:
    principal = server_principal_from_authentication(
        AuthenticatedServerRequest(
            user=LocalUser(id="user-a", username="alice", display_name="Alice"),
            permissions=frozenset({"evidence.read"}),
            principal_type="user",
            scope_authority=PrincipalScopeSnapshot(
                workspace_ids=frozenset({"workspace-a"}),
                organization_ids=frozenset({"organization-a"}),
                legal_entity_ids=frozenset({"entity-a"}),
            ),
        )
    )
    assert principal.authorized_workspace_ids == frozenset({"workspace-a"})
    assert principal.authorized_organization_ids == frozenset({"organization-a"})
    assert principal.authorized_legal_entity_ids == frozenset({"entity-a"})
