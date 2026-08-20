from __future__ import annotations

from typing import Any

from reconforge.application.writeback import WritebackIntentApplicationService
from reconforge.connectors.writeback import WritebackIntent
from tests.test_connector_writeback import _intent


class _Repository:
    def __init__(self) -> None:
        self.put_calls: list[tuple[WritebackIntent, int | None]] = []
        self.get_calls: list[tuple[str, str, str]] = []
        self.list_calls: list[tuple[str, str]] = []

    def put(self, intent: WritebackIntent, *, expected_version: int | None = None) -> WritebackIntent:
        self.put_calls.append((intent, expected_version))
        return intent

    def get(self, *, intent_id: str, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        self.get_calls.append((intent_id, tenant_id, workspace_id))
        return None

    def list_latest(self, *, tenant_id: str, workspace_id: str) -> tuple[WritebackIntent, ...]:
        self.list_calls.append((tenant_id, workspace_id))
        return ()


def test_writeback_application_service_delegates_backend_neutral_contract() -> None:
    repository = _Repository()
    service = WritebackIntentApplicationService(repository)
    intent = _intent()

    assert service.put(intent, expected_version=3) == intent
    assert service.get(intent_id="intent-001", tenant_id="tenant-a", workspace_id="workspace-a") is None
    assert service.list_latest(tenant_id="tenant-a", workspace_id="workspace-a") == ()
    assert repository.put_calls == [(intent, 3)]
    assert repository.get_calls == [("intent-001", "tenant-a", "workspace-a")]
    assert repository.list_calls == [("tenant-a", "workspace-a")]
