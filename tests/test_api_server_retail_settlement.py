from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, Request

from reconforge.api.errors import APIError
from reconforge.api.routes import retail_settlement
from reconforge.api.server_retail_settlement import execute_postgres_retail_settlement
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.platform.common import ServerPrincipal


def _request(*, workspace_id: str | None = "workspace-a") -> Request:
    app = FastAPI()
    factory = PostgresConnectionFactory(PostgresSettings(dsn="postgresql://retail.test/postgres", require_tls=False))
    app.state.postgres_identity_factory = factory
    app.state.postgres_retail_settlement_factory = factory
    headers = [(b"x-reconforge-tenant", b"tenant-a")]
    if workspace_id is not None:
        headers.extend(
            [
                (b"x-reconforge-workspace", workspace_id.encode("ascii")),
                (b"x-reconforge-organization", b"organization-a"),
                (b"x-reconforge-legal-entity", b"entity-a"),
            ]
        )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "app": app})
    request.state.server_principal = ServerPrincipal(
        user=LocalUser(id="user-a", username="alice", display_name="Alice"),
        permissions=frozenset({"finance_core.manage", "finance_core.read"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
        authorized_organization_ids=frozenset({"organization-a"}),
        authorized_legal_entity_ids=frozenset({"entity-a"}),
    )
    return request


def test_server_retail_boundary_passes_authorized_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.api.server_retail_settlement as module

    captured: dict[str, object] = {}

    class Boundary:
        def __init__(self, factory: object) -> None:
            captured["factory"] = factory

        @contextmanager
        def transaction(self, tenant_id: str, **scope: object) -> Iterator[object]:
            captured["tenant_id"] = tenant_id
            captured.update(scope)
            yield object()

    monkeypatch.setattr(module, "PostgresTenantBoundary", Boundary)
    result = execute_postgres_retail_settlement(
        _request(),
        lambda repository, tenant, workspace: (repository.connection, tenant, workspace),
    )
    assert result[1:] == ("tenant-a", "workspace-a")
    assert captured["workspace_id"] == "workspace-a"
    assert captured["organization_id"] == "organization-a"
    assert captured["legal_entity_id"] == "entity-a"


def test_server_retail_route_does_not_fallback_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    captured: dict[str, object] = {}

    def fake_execute(request: Request, operation: Callable[[object, str, str], object]) -> object:
        class Repository:
            def put_payload(
                self,
                report: dict[str, object],
                *,
                tenant_id: str,
                workspace_id: str,
                actor_label: str,
            ) -> dict[str, object]:
                captured.update(
                    report=report,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    actor_label=actor_label,
                )
                return {"id": "rtl-server", "workspace_id": workspace_id, "report": report}

        return operation(Repository(), "tenant-a", "workspace-a")

    monkeypatch.setattr(retail_settlement, "execute_postgres_retail_settlement", fake_execute)
    monkeypatch.setattr(retail_settlement, "enforce_server_scoped_permission", lambda *args, **kwargs: None)
    result = retail_settlement.persist_settlement(
        request,
        retail_settlement.RetailSettlementPersistenceRequest(report={"synthetic": True}),
        request.state.server_principal.user,
        None,
    )
    assert result["source"] == {"kind": "postgresql-retail-settlement", "server_mode": True}
    assert result["network_dispatch"] == "disabled"
    assert captured == {
        "report": {"synthetic": True},
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "actor_label": "alice",
    }


def test_server_retail_route_rejects_missing_workspace_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(workspace_id=None)
    monkeypatch.setattr(retail_settlement, "enforce_server_scoped_permission", lambda *args, **kwargs: None)
    with pytest.raises(APIError, match="Workspace"):
        retail_settlement.persist_settlement(
            request,
            retail_settlement.RetailSettlementPersistenceRequest(report={"synthetic": True}),
            request.state.server_principal.user,
            None,
        )
