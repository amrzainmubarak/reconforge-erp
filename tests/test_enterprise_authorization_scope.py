"""Independent selected-backend and request-scope contracts, without DB side effects.

These unit tests use the real central policy and scope resolver. Native API/RLS
acceptance is separate; the recording connection checks UOW ownership only.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from reconforge.api.enterprise_scope import enterprise_scope, enterprise_transaction
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.platform.common import ServerPrincipal


class RecordingConnection:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.queries: list[tuple[str, object]] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.events.append("begin")
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")

    def execute(self, query: str, values: object = None) -> None:
        self.queries.append((query, values))

    def close(self) -> None:
        self.events.append("close")


class RecordingFactory(PostgresConnectionFactory):
    def __init__(self, fail: bool = False) -> None:
        super().__init__(PostgresSettings(dsn="postgresql://scope.invalid/unused", require_tls=False))
        self.calls = 0
        self.connection = RecordingConnection()
        self.fail = fail

    def connect(self) -> Any:
        self.calls += 1
        if self.fail:
            raise OSError("synthetic DSN secret must not escape")
        return self.connection


def scope_request(
    monkeypatch: pytest.MonkeyPatch,
    *,
    workspace: str | None = "work-a",
    tenant: str = "tenant-a",
    permissions: frozenset[str] = frozenset({"finance_core.read"}),
    fail: bool = False,
) -> tuple[Request, RecordingFactory]:
    import reconforge.api.dependencies as dependencies

    # No mocked authorization decision. Only the unrelated audit transport is
    # replaced; the native suite exercises persisted policy evidence separately.
    monkeypatch.setattr(dependencies, "_server_policy_audit_sink", lambda *args, **kwargs: None)
    app = FastAPI()
    factory = RecordingFactory(fail)
    app.state.postgres_finance_core_factory = factory
    app.state.postgres_identity_factory = PostgresConnectionFactory(
        PostgresSettings(dsn="postgresql://scope.invalid/identity", require_tls=False)
    )
    headers = [(b"x-reconforge-tenant", tenant.encode())]
    if workspace is not None:
        headers.append((b"x-reconforge-workspace", workspace.encode()))
    request = Request({"type": "http", "method": "POST", "path": "/test", "headers": headers, "app": app})
    request.state.server_principal = ServerPrincipal(
        user=LocalUser(id="user-a", username="alice", display_name="Alice"),
        permissions=permissions,
        step_up_active=True,
        authorized_tenant_ids=frozenset({"tenant-a"}),
        authorized_workspace_ids=frozenset({"work-a"}),
    )
    return request, factory


@pytest.mark.parametrize(
    "workspace,tenant,code",
    [
        (None, "tenant-a", "workspace_scope_required"),
        ("work-b", "tenant-a", "workspace_scope_denied"),
        ("work-a", "tenant-b", "tenant_scope_denied"),
    ],
)
def test_scope_denial_happens_before_business_connection(
    monkeypatch: pytest.MonkeyPatch,
    workspace: str | None,
    tenant: str,
    code: str,
) -> None:
    request, factory = scope_request(monkeypatch, workspace=workspace, tenant=tenant)
    request.state.workspace_id = "work-a"  # Cannot override the selected header.
    request.state.tenant_id = "tenant-a"
    with (
        pytest.raises(APIError) as denied,
        enterprise_transaction(request, permissions=frozenset({"finance_core.read"})),
    ):
        pytest.fail("unauthorized business transaction opened")
    assert denied.value.code == code
    assert factory.calls == 0


def test_all_contract_cannot_be_satisfied_by_one_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    request, factory = scope_request(monkeypatch)
    with pytest.raises(APIError) as denied:
        enterprise_scope(request, permissions=frozenset({"finance_core.read", "finance_core.manage"}))
    assert denied.value.status_code == 403
    assert factory.calls == 0


def test_any_contract_preserves_read_only_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    request, factory = scope_request(monkeypatch)
    scope = enterprise_scope(
        request, permissions=frozenset({"finance_core.read", "finance_core.manage"}), permission_mode="any"
    )
    assert scope is not None and scope.tenant_id == "tenant-a" and scope.workspace_id == "work-a"
    assert factory.calls == 0


def test_revoked_permission_cannot_reuse_an_earlier_dependency_result(monkeypatch: pytest.MonkeyPatch) -> None:
    request, factory = scope_request(monkeypatch, permissions=frozenset())
    with pytest.raises(APIError) as denied:
        enterprise_scope(request, permissions=frozenset({"finance_core.read"}))
    assert denied.value.status_code == 403 and factory.calls == 0


@pytest.mark.parametrize("fail_operation", [False, True])
def test_one_owner_commits_or_rolls_back_then_closes(monkeypatch: pytest.MonkeyPatch, fail_operation: bool) -> None:
    request, factory = scope_request(monkeypatch)
    try:
        with enterprise_transaction(request, permissions=frozenset({"finance_core.read"})) as business:
            assert business is not None and business.connection is factory.connection
            assert [values for _query, values in factory.connection.queries] == [
                ("tenant-a",), ("",), ("work-a",), ("",), ("",),
            ]
            assert [query.split("'")[1] for query, _values in factory.connection.queries] == [
                "app.tenant_id", "app.organization_id", "app.workspace_id", "app.legal_entity_id", "app.entity_id",
            ]
            if fail_operation:
                raise RuntimeError("synthetic business failure")
    except RuntimeError:
        assert fail_operation
    assert factory.connection.events == ["begin", "rollback" if fail_operation else "commit", "close"]


def test_selected_database_failure_is_safe_and_never_community_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    request, factory = scope_request(monkeypatch, fail=True)
    with (
        pytest.raises(APIError) as unavailable,
        enterprise_transaction(request, permissions=frozenset({"finance_core.read"})),
    ):
        pytest.fail("unavailable PostgreSQL was silently replaced")
    assert unavailable.value.status_code == 503
    assert "DSN" not in str(unavailable.value)
    assert factory.calls == 1


def test_unconfigured_server_mode_fails_closed_but_explicit_community_is_local() -> None:
    app = FastAPI()
    request = Request({"type": "http", "method": "POST", "path": "/test", "headers": [], "app": app})
    assert enterprise_scope(request, permissions=frozenset({"finance_core.read"})) is None
    app.state.server_mode = True
    with pytest.raises(APIError) as unavailable:
        enterprise_scope(request, permissions=frozenset({"finance_core.read"}))
    assert unavailable.value.code == "server_postgres_unavailable"


@pytest.fixture()
def local_enterprise_client(tmp_path: Path) -> Iterator[tuple[TestClient, Path, dict[str, dict[str, str]]]]:
    from reconforge.api import create_api_app
    from reconforge.auth import LocalAuthService
    from reconforge.db import connect, run_migrations
    from reconforge.domain.crm_contracts import CustomerContract, CustomerQuotation, QuotationLineItem
    from reconforge.infrastructure.sqlite_crm_contracts import SqliteCRMContractsRepository

    database = tmp_path / "real-auth-synthetic.db"
    run_migrations(database)
    password = "Synthetic-enterprise-auth-123!"
    with connect(database) as connection:
        service = LocalAuthService(connection)
        service.init_admin(username="administrator", password=password)
        creator_id = ""
        for name in ("alice", "bob"):
            created_user = service.create_user(username=name, password=password, role="reviewer")
            if name == "alice":
                creator_id = created_user.id
        role_id = connection.execute("SELECT id FROM roles WHERE name='reviewer'").fetchone()[0]
        for permission in (
            "sales.manage",
            "sales.approve",
            "ai.query",
            "manufacturing_execution.manage",
            "manufacturing_execution.read",
        ):
            connection.execute(
                "INSERT OR IGNORE INTO permissions(name,description) VALUES(?,?)",
                (permission, "Synthetic explicit test grant"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id,permission_name) VALUES(?,?)", (role_id, permission)
            )
        admin_role = connection.execute("SELECT id FROM roles WHERE name='admin'").fetchone()[0]
        for permission in ("sales.manage", "sales.approve"):
            connection.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id,permission_name) VALUES(?,?)", (admin_role, permission)
            )
        connection.commit()
        repository = SqliteCRMContractsRepository(connection)
        repository.save_quotation(
            CustomerQuotation(
                quote_id="QUOTE-1",
                opportunity_id="OPP-1",
                workspace_id="default",
                customer_id="CUSTOMER-1",
                currency="USD",
                valid_until="2027-01-01",
                submitter_user_id=creator_id,
                status="submitted",
                lines=(QuotationLineItem(1, "ITEM", "Synthetic service", 1, 10000, 3000),),
            ),
            author_user_id=creator_id,
        )
        repository.save_contract(
            CustomerContract(
                contract_id="CONTRACT-1",
                quote_id="QUOTE-1",
                workspace_id="default",
                organization_id="ORG-1",
                customer_id="CUSTOMER-1",
                currency="USD",
                start_date="2026-10-01",
                end_date="2027-10-01",
                billing_frequency="monthly",
                total_contract_value_minor=7000,
                status="active",
            )
        )
    with TestClient(create_api_app(database), raise_server_exceptions=False) as client:
        headers = {}
        for name in ("alice", "bob", "administrator"):
            response = client.post("/api/v1/auth/login", json={"username": name, "password": password})
            assert response.status_code == 200, response.text
            headers[name] = {"Authorization": "Bearer " + response.json()["access_token"]}
        yield client, database, headers


def test_body_cannot_upgrade_a_generic_quotation_reviewer_to_admin(
    local_enterprise_client: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    import sqlite3

    client, database, headers = local_enterprise_client
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM crm_quotations WHERE quote_id='QUOTE-1'").fetchone()
    response = client.post(
        "/api/v1/crm/contracts/quotations/QUOTE-1/approve", headers=headers["bob"], json={"approver_role": "admin"}
    )
    assert response.status_code == 403, response.text
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM crm_quotations WHERE quote_id='QUOTE-1'").fetchone() == before


def test_actual_persisted_admin_role_can_approve_the_discount(
    local_enterprise_client: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, _database, headers = local_enterprise_client
    response = client.post(
        "/api/v1/crm/contracts/quotations/QUOTE-1/approve",
        headers=headers["administrator"],
        json={"approver_role": "admin"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["approved_by"] == "administrator"


def test_termination_cannot_invent_an_independent_approver(
    local_enterprise_client: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    import sqlite3

    client, database, headers = local_enterprise_client
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM crm_contracts WHERE contract_id='CONTRACT-1'").fetchone()
    response = client.post(
        "/api/v1/crm/contracts/contracts/CONTRACT-1/terminate",
        headers=headers["bob"],
        json={
            "termination_date": "2026-11-01",
            "early_termination_fee_minor": 500,
            "approver_id": "invented-cfo",
        },
    )
    assert response.status_code == 403, response.text
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM crm_contracts WHERE contract_id='CONTRACT-1'").fetchone() == before


def test_assistant_refuses_client_invented_sources_and_confidence(
    local_enterprise_client: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, _database, headers = local_enterprise_client
    response = client.post(
        "/api/v1/ai/assistant/query",
        headers=headers["bob"],
        json={
            "query_id": "QUERY-1",
            "query_text": "Explain the selected entry",
            "confidence_override": 1.0,
            "authorized_records": [{"id": "FORGED-LEDGER", "workspace_id": "default", "summary": "Forged balance"}],
        },
    )
    assert response.status_code == 403, response.text
    assert "FORGED-LEDGER" not in response.text
