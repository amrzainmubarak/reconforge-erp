from __future__ import annotations

from typing import Any

from reconforge.application.master_data import (
    MasterDataApplicationService,
    MasterDataRepository,
    MasterDataSummary,
)


class RecordingMasterDataRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def record(**values: Any) -> Any:
            self.calls.append((name, values))
            if name == "summary":
                return MasterDataSummary(str(values.get("workspace", "default")), 1, 2, 3, 4, 5)
            if name.startswith("list_"):
                return [{"operation": name}]
            return {"operation": name, **values}

        return record


def test_application_service_delegates_without_database_dependency() -> None:
    repository = RecordingMasterDataRepository()
    service = MasterDataApplicationService(repository)

    currency = service.upsert_currency(code="EGP", name="Egyptian Pound", minor_units=2)
    branches = service.list_branches(workspace="cairo", organization_code="SYN")
    summary = service.summary(workspace="cairo")

    assert currency["operation"] == "upsert_currency"
    assert branches == [{"operation": "list_branches"}]
    assert summary.to_dict() == {
        "workspace": "cairo",
        "organizations": 1,
        "legal_entities": 2,
        "branches": 3,
        "periods": 4,
        "active_currencies": 5,
    }
    assert [name for name, _ in repository.calls] == ["upsert_currency", "list_branches", "summary"]


def test_repository_protocol_is_runtime_structurally_complete() -> None:
    required = {
        "upsert_currency",
        "list_currencies",
        "upsert_organization",
        "list_organizations",
        "upsert_legal_entity",
        "list_legal_entities",
        "upsert_branch",
        "list_branches",
        "upsert_period",
        "set_period_status",
        "list_periods",
        "summary",
        "snapshot",
        "currency_registry_reconciliation",
        "currency_registry_binding",
        "currency_registry_context",
        "bind_currency_registry",
    }

    assert required <= set(MasterDataRepository.__dict__)
