from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from reconforge.api.routes import finance_core as routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.application.finance_core import FinanceCoreSummary
from reconforge.auth.models import LocalUser


def _request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})


@dataclass
class _FakeFinanceRepository:
    calls: list[tuple[str, dict[str, object]]]

    def _record(self, operation: str, **values: object) -> dict[str, object]:
        self.calls.append((operation, values))
        return {"id": f"{operation}-1", **values}

    def summary(self, **values: object) -> FinanceCoreSummary:
        self.calls.append(("summary", values))
        return FinanceCoreSummary("workspace-a", 1, 1, 1, 1, 1, 0, 0, 0)

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
    assert dimensions["pagination"]["returned"] == 0
    assert journal["journal"]["workspace"] == "workspace-a"
    assert all(call[1].get("workspace") == "workspace-a" for call in calls if "workspace" in call[1])
    assert ("any", frozenset({"finance_core.read", "finance_core.manage", "finance_core.validate"})) in permission_checks
    assert ("exact", "finance_core.manage") in permission_checks


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
