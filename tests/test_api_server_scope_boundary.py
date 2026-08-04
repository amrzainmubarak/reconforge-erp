from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI, Request

from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.platform.common import ServerPrincipal


def _request(factory_state_name: str, *, workspace_id: str | None = "workspace-a") -> Request:
    app = FastAPI()
    setattr(
        app.state,
        factory_state_name,
        PostgresConnectionFactory(PostgresSettings(dsn="postgresql://scope.test/postgres", require_tls=False)),
    )
    headers = [(b"x-reconforge-tenant", b"tenant-a")]
    if workspace_id is not None:
        headers.extend(
            [
                (b"x-reconforge-workspace", workspace_id.encode("ascii")),
                (b"x-reconforge-organization", b"organization-a"),
                (b"x-reconforge-legal-entity", b"entity-a"),
            ]
        )
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "app": app})
    request.state.server_principal = ServerPrincipal(
        user=LocalUser(id="user-a", username="alice", display_name="Alice"),
        permissions=frozenset({"evidence.read", "reconciliation.read"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
        authorized_organization_ids=frozenset({"organization-a"}),
        authorized_legal_entity_ids=frozenset({"entity-a"}),
    )
    return request


@pytest.mark.parametrize(
    ("module_name", "factory_state_name", "execute_name"),
    (
        ("reconforge.api.server_reconciliation", "postgres_reconciliation_factory", "execute_postgres_reconciliation"),
        ("reconforge.api.server_evidence", "postgres_evidence_factory", "execute_postgres_evidence"),
        ("reconforge.api.server_master_data", "postgres_master_data_factory", "execute_postgres_master_data"),
        ("reconforge.api.server_ledger", "postgres_ledger_factory", "execute_postgres_ledger"),
        ("reconforge.api.server_close", "postgres_close_factory", "execute_postgres_close"),
        (
            "reconforge.api.server_consolidation_close",
            "postgres_consolidation_close_factory",
            "execute_postgres_consolidation_close",
        ),
        (
            "reconforge.api.server_consolidation_ownership",
            "postgres_consolidation_ownership_factory",
            "execute_postgres_consolidation_ownership",
        ),
    ),
)
def test_server_business_boundary_passes_only_authorized_scope_to_rls(
    module_name: str, factory_state_name: str, execute_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = __import__(module_name, fromlist=[execute_name])
    captured: dict[str, object] = {}

    class Boundary:
        def __init__(self, factory: object) -> None:
            captured["factory"] = factory

        @contextmanager
        def transaction(self, tenant_id: str, **scope: object) -> Any:
            captured["tenant_id"] = tenant_id
            captured.update(scope)
            yield object()

    monkeypatch.setattr(module, "PostgresTenantBoundary", Boundary)
    result = getattr(module, execute_name)(
        _request(factory_state_name), lambda repository, tenant: (repository.connection, tenant)
    )
    assert result[1] == "tenant-a"
    assert captured["workspace_id"] == "workspace-a"
    assert captured["organization_id"] == "organization-a"
    assert captured["legal_entity_id"] == "entity-a"


@pytest.mark.parametrize("workspace_id,code", ((None, "workspace_scope_required"), ("workspace-b", "workspace_scope_denied")))
def test_server_business_boundary_rejects_missing_or_sibling_scope_before_database(
    workspace_id: str | None, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reconforge.api.server_reconciliation as module

    opened = False

    class Boundary:
        def __init__(self, factory: object) -> None:
            nonlocal opened
            opened = True

    monkeypatch.setattr(module, "PostgresTenantBoundary", Boundary)
    with pytest.raises(APIError) as denied:
        module.execute_postgres_reconciliation(_request("postgres_reconciliation_factory", workspace_id=workspace_id), lambda *_: None)
    assert denied.value.code == code
    assert opened is False
