from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from reconforge.api import server_finance_core
from reconforge.api.routes import finance_core as routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.models import LocalUser


def _request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})


@dataclass
class _FakeFinanceRepository:
    calls: list[tuple[str, dict[str, object]]]

    def _record(self, operation: str, **values: object) -> dict[str, object]:
        self.calls.append((operation, values))
        return {"id": f"{operation}-1", "unknown_future_column": "must-not-escape", **values}

    def summary(self, **values: object):
        self.calls.append(("summary", values))
        return SimpleNamespace(
            to_dict=lambda: {
                "workspace": "workspace-a",
                "charts": 1,
                "accounts": 1,
                "dimensions": 1,
                "dimension_values": 1,
                "journals": 1,
                "draft_entries": 0,
                "validated_entries": 0,
                "voided_entries": 0,
                "unknown_summary_field": "must-not-escape",
            }
        )

    def snapshot(self, **values: object) -> dict[str, object]:
        self.calls.append(("snapshot", values))
        return {"schema_version": 1, "workspace": values["workspace"], "charts": []}

    def list_charts(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list_charts", values))
        return [{"chart_code": "DEFAULT", "organization_code": "ORG-A"}]

    def upsert_chart(self, **values: object) -> dict[str, object]:
        return self._record("chart", **values)

    def list_accounts(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list_accounts", values))
        return [{"account_code": "1000", "chart_code": "DEFAULT"}]

    def upsert_account(self, **values: object) -> dict[str, object]:
        return self._record("account", **values)

    def list_dimensions(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list_dimensions", values))
        return []

    def upsert_dimension(self, **values: object) -> dict[str, object]:
        return self._record("dimension", **values)

    def list_dimension_values(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list_dimension_values", values))
        return []

    def upsert_dimension_value(self, **values: object) -> dict[str, object]:
        return self._record("dimension_value", **values)

    def list_journals(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list_journals", values))
        return []

    def upsert_journal(self, **values: object) -> dict[str, object]:
        return self._record("journal", **values)

    def trial_balance(self, **values: object) -> dict[str, object]:
        return self._record("trial_balance", **values)

    def list_entries(self, **values: object) -> list[dict[str, object]]:
        self.calls.append(("list_entries", values))
        return []

    def create_entry(self, **values: object) -> dict[str, object]:
        return self._record("entry", **values)

    def get_entry(self, entry_id: str, **values: object) -> dict[str, object]:
        return self._record("get_entry", entry_id=entry_id, **values)

    def validate_entry(self, entry_id: str, **values: object) -> dict[str, object]:
        return self._record("validate_entry", entry_id=entry_id, **values)

    def void_entry(self, entry_id: str, **values: object) -> dict[str, object]:
        return self._record("void_entry", entry_id=entry_id, **values)


class _ScopeResult:
    def __init__(self, row: dict[str, str] | None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, str] | None:
        return self.row


class _ScopeConnection:
    def execute(self, query: str, _parameters: tuple[object, ...]) -> _ScopeResult:
        if "FROM reconforge.organizations" in query:
            return _ScopeResult({"id": "org-a", "organization_code": "ORG-A"})
        if "master_data_workspace_organizations" in query:
            return _ScopeResult({"ok": "1"})
        if "FROM reconforge.legal_entities" in query:
            return _ScopeResult({"id": "entity-a", "entity_code": "ENTITY-A"})
        raise AssertionError(f"unexpected scope query: {query}")


def test_finance_core_scope_codes_are_canonical_and_reject_spoofed_values() -> None:
    scope = RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a")
    connection = _ScopeConnection()

    assert server_finance_core._scope_codes(connection, scope) == ("ORG-A", "ENTITY-A")
    with pytest.raises(routes.APIError) as organization_error:
        server_finance_core._scope_codes(connection, scope, organization_code="ORG-SPOOF")
    assert organization_error.value.code == "organization_scope_denied"
    with pytest.raises(routes.APIError) as entity_error:
        server_finance_core._scope_codes(connection, scope, entity_code="ENTITY-SPOOF")
    assert entity_error.value.code == "entity_scope_denied"


def test_server_finance_core_routes_use_scoped_adapter_and_never_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    calls: list[tuple[str, dict[str, object]]] = []
    repository = _FakeFinanceRepository(calls)
    permission_checks: list[tuple[str, object]] = []

    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant-a", "workspace-a"))
    monkeypatch.setattr(
        routes,
        "enforce_server_scoped_permission",
        lambda _request, **values: permission_checks.append(("exact", values["permission"])),
    )
    monkeypatch.setattr(
        routes,
        "enforce_server_scoped_permissions",
        lambda _request, **values: permission_checks.append(("any", values["permissions"])),
    )
    monkeypatch.setattr(routes, "execute_postgres_finance_core", lambda _request, operation: operation(repository))
    monkeypatch.setattr(
        routes,
        "execute_postgres_finance_core_scoped",
        lambda _request, operation, **values: operation(
            repository,
            SimpleNamespace(
                organization_code=values.get("organization_code", ""),
                entity_code=values.get("entity_code", ""),
            ),
        ),
    )

    summary = routes.summary(request, user, None, workspace="default")
    chart = routes.upsert_chart(
        request,
        routes.ChartRequest(chart_code="DEFAULT", name="Default", organization_code="ORG-A"),
        user,
        None,
    )
    dimensions = routes.list_dimensions(request, user, None, workspace="default", limit=10, offset=0)
    journal = routes.upsert_journal(
        request,
        routes.JournalRequest(
            journal_code="GENERAL", name="General", organization_code="ORG-A", currency_code="USD"
        ),
        user,
        None,
    )
    assert summary["summary"]["workspace"] == "workspace-a"
    assert chart["chart"]["workspace"] == "workspace-a"
    assert "must-not-escape" not in str(chart)
    assert dimensions["pagination"]["returned"] == 0
    assert journal["journal"]["workspace"] == "workspace-a"
    assert "must-not-escape" not in str(journal)
    assert all(call[1].get("workspace") == "workspace-a" for call in calls if "workspace" in call[1])
    assert ("any", frozenset({"finance_core.read", "finance_core.manage", "finance_core.validate"})) in permission_checks
    assert ("exact", "finance_core.manage") in permission_checks


def test_server_finance_core_entry_binds_exact_debit_amount_to_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    repository = _FakeFinanceRepository([])
    captured: dict[str, object] = {}

    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant-a", "workspace-a"))
    monkeypatch.setattr(
        routes,
        "enforce_server_scoped_permission",
        lambda _request, **values: captured.update(values),
    )
    monkeypatch.setattr(routes, "execute_postgres_finance_core", lambda _request, operation: operation(repository))
    monkeypatch.setattr(
        routes,
        "execute_postgres_finance_core_scoped",
        lambda _request, operation, **values: operation(
            repository,
            SimpleNamespace(
                organization_code=values.get("organization_code", ""),
                entity_code=values.get("entity_code", ""),
            ),
        ),
    )

    result = routes.create_entry(
        request,
        routes.LedgerEntryRequest(
            entry_number="JE/ABAC/001",
            organization_code="ORG-A",
            entity_code="ENTITY-A",
            period_id="PERIOD-A",
            journal_code="GENERAL",
            posting_date="2026-08-23",
            description="Amount policy binding",
            lines=[
                routes.LedgerLineRequest(account_code="1000", debit="140.00", credit="0"),
                routes.LedgerLineRequest(account_code="3000", debit="0", credit="140.00"),
            ],
        ),
        user,
        None,
    )

    assert result["entry"]["id"] == "entry-1"
    assert captured["permission"] == "finance_core.manage"
    assert captured["amount"] == Decimal("140.00")


def test_server_finance_core_entry_rejects_negative_amount_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "execute_postgres_finance_core", lambda *_args: pytest.fail("adapter must not run"))

    with pytest.raises(routes.APIError) as error:
        routes.create_entry(
            request,
            routes.LedgerEntryRequest(
                entry_number="JE/ABAC/NEGATIVE",
                organization_code="ORG-A",
                entity_code="ENTITY-A",
                period_id="PERIOD-A",
                journal_code="GENERAL",
                posting_date="2026-08-23",
                description="Invalid amount",
                lines=[
                    routes.LedgerLineRequest(account_code="1000", debit="-1.00", credit="0"),
                    routes.LedgerLineRequest(account_code="3000", debit="0", credit="-1.00"),
                ],
            ),
            user,
            None,
        )
    assert error.value.code == "finance_entry_amount_invalid"


def test_finance_core_entry_route_drops_future_adapter_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: True)
    monkeypatch.setattr(
        routes,
        "_server_finance_workspace",
        lambda *_args, **_kwargs: "workspace-a",
    )
    monkeypatch.setattr(
        routes,
        "execute_postgres_finance_core",
        lambda _request, _operation: {
            "id": "GLE-1",
            "entry_number": "JE-001",
            "status": "Validated",
            "unknown_future_column": "must-not-escape",
            "lines": [
                {
                    "id": "line-1",
                    "line_number": 1,
                    "account_id": "account-1",
                    "unknown_line_column": "must-not-escape",
                }
            ],
        },
    )

    result = routes.get_entry(request, "GLE-1", user, None)

    assert result["entry"] == {
        "entry_number": "JE-001",
        "id": "GLE-1",
        "lines": [{"account_id": "account-1", "id": "line-1", "line_number": 1}],
        "status": "Validated",
    }


def test_server_finance_core_entry_does_not_fall_back_to_legacy_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: True)
    monkeypatch.setattr(
        routes,
        "execute_postgres_finance_core_scoped",
        lambda *_args, **_kwargs: pytest.fail("Finance Core adapter must not run for incomplete scope"),
    )
    monkeypatch.setattr(
        routes,
        "execute_postgres_ledger",
        lambda *_args, **_kwargs: pytest.fail("legacy ledger fallback must not run"),
    )

    with pytest.raises(routes.APIError) as error:
        routes.create_entry(
            request,
            routes.LedgerEntryRequest(
                entry_number="JE/BOUNDARY/001",
                organization_code="ORG-A",
                entity_code="",
                period_id="PERIOD-A",
                journal_code="GENERAL",
                posting_date="2026-08-23",
                description="Incomplete server scope",
                lines=[
                    routes.LedgerLineRequest(account_code="1000", debit="1.00", credit="0"),
                    routes.LedgerLineRequest(account_code="3000", debit="0", credit="1.00"),
                ],
            ),
            user,
            None,
        )
    assert error.value.code == "finance_core_entry_scope_required"


def test_server_finance_core_rejects_cross_workspace_payload_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    monkeypatch.setattr(routes, "server_finance_core_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "request_execution_scope", lambda _request: RequestExecutionScope("tenant-a", "workspace-a"))
    monkeypatch.setattr(routes, "execute_postgres_finance_core", lambda *_args: pytest.fail("adapter must not run"))
    with pytest.raises(routes.APIError) as error:
        routes.upsert_chart(
            request,
            routes.ChartRequest(chart_code="OTHER", name="Other", workspace="workspace-b"),
            user,
            None,
        )
    assert error.value.code == "workspace_scope_denied"
