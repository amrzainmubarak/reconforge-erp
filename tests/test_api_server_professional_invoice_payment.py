from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI, Request

from reconforge.api.errors import APIError
from reconforge.api.routes import professional_invoice_payment
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.platform.common import ServerPrincipal


def _request(*, workspace_id: str | None = "workspace-a") -> Request:
    app = FastAPI()
    factory = PostgresConnectionFactory(PostgresSettings(dsn="postgresql://professional.test/postgres", require_tls=False))
    app.state.postgres_identity_factory = factory
    app.state.postgres_professional_invoice_payment_factory = factory
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


def test_server_professional_route_does_not_fallback_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
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
                return {"id": "pip-server", "workspace_id": workspace_id, "report": report}

        return operation(Repository(), "tenant-a", "workspace-a")

    monkeypatch.setattr(professional_invoice_payment, "execute_postgres_professional_invoice_payment", fake_execute)
    monkeypatch.setattr(professional_invoice_payment, "enforce_server_scoped_permission", lambda *args, **kwargs: None)
    result = professional_invoice_payment.persist_professional_invoice_payment(
        request,
        professional_invoice_payment.ProfessionalInvoicePaymentPersistenceRequest(
            report={"decision_digest": "f" * 64, "artifact_digest": "a" * 64},
            workspace="workspace-a",
        ),
        request.state.server_principal.user,
        None,
    )
    assert result["source"] == {"kind": "postgresql-professional-invoice-payment", "server_mode": True}
    assert result["network_dispatch"] == "disabled"
    assert captured == {
        "report": {"decision_digest": "f" * 64, "artifact_digest": "a" * 64},
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "actor_label": "alice",
    }


def test_server_professional_route_rejects_missing_workspace_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(workspace_id=None)
    monkeypatch.setattr(professional_invoice_payment, "enforce_server_scoped_permission", lambda *args, **kwargs: None)
    with pytest.raises(APIError, match="Workspace"):
        professional_invoice_payment.persist_professional_invoice_payment(
            request,
            professional_invoice_payment.ProfessionalInvoicePaymentPersistenceRequest(
                report={"decision_digest": "f" * 64, "artifact_digest": "a" * 64},
                workspace="workspace-a",
            ),
            request.state.server_principal.user,
            None,
        )
