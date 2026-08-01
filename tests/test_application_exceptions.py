"""Contract tests for the backend-neutral exception queue boundary."""

from __future__ import annotations

from typing import Any

from reconforge.application.exceptions import ExceptionQueueApplicationService


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def upsert_exception(self, **values: Any) -> dict[str, Any]:
        self.calls.append(("upsert", values))
        return {"id": "EXQ-1", **values}

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        self.calls.append(("list", filters))
        return [{"id": "EXQ-1"}]

    def assign(self, exception_id: str, *, owner: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.calls.append(("assign", (exception_id, owner, actor_label)))
        return {"id": exception_id, "owner": owner}

    def set_status(self, exception_id: str, *, status: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.calls.append(("status", (exception_id, status, actor_label)))
        return {"id": exception_id, "status": status}

    def bulk_update(
        self,
        exception_ids: object,
        *,
        status: str = "",
        owner: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        identifiers = tuple(exception_ids)  # type: ignore[arg-type]
        self.calls.append(("bulk", (identifiers, status, owner, actor_label)))
        return len(identifiers)

    def get(self, exception_id: str) -> dict[str, Any]:
        self.calls.append(("get", exception_id))
        return {"id": exception_id}


def test_exception_application_service_preserves_complete_contract() -> None:
    repository = _Repository()
    service = ExceptionQueueApplicationService(repository)

    saved = service.upsert_exception(
        source_type="control",
        source_id="C-1",
        description="Variance",
        workspace="finance",
        risk_rating="high",
        actor_label="reviewer",
    )
    listed = service.list(status="Open", owner="owner-a")
    assigned = service.assign("EXQ-1", owner="owner-b", actor_label="reviewer")
    updated = service.set_status("EXQ-1", status="In Review", actor_label="reviewer")
    count = service.bulk_update(["EXQ-1", "EXQ-2"], status="Closed", actor_label="reviewer")
    fetched = service.get("EXQ-1")

    assert saved["workspace"] == "finance"
    assert listed == [{"id": "EXQ-1"}]
    assert assigned["owner"] == "owner-b"
    assert updated["status"] == "In Review"
    assert count == 2
    assert fetched == {"id": "EXQ-1"}
    assert [name for name, _ in repository.calls] == [
        "upsert", "list", "assign", "status", "bulk", "get"
    ]
