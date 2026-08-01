from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from reconforge.application.inventory_core import (
    InventoryCoreApplicationService,
    InventoryCoreRepositoryProtocol,
    InventoryCoreSummary,
)


class _RecordingInventoryRepository:
    def __init__(self) -> None:
        self.operation = ""
        self.arguments: dict[str, object] = {}

    def create_movement(
        self,
        *,
        movement_number: str,
        movement_type: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        movement_date: str,
        description: str,
        lines: Sequence[Mapping[str, object]],
        workspace: str = "default",
        source_reference: str = "",
        source_type: str = "Manual",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self.operation = "create_movement"
        self.arguments = {
            "movement_number": movement_number,
            "movement_type": movement_type,
            "organization_code": organization_code,
            "entity_code": entity_code,
            "period_id": period_id,
            "movement_date": movement_date,
            "description": description,
            "lines": lines,
            "workspace": workspace,
            "source_reference": source_reference,
            "source_type": source_type,
            "actor_label": actor_label,
        }
        return {"id": "movement-1", "lines": list(lines)}

    def post_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.operation = "post_movement"
        self.arguments = {"movement_id": movement_id, "reason": reason, "actor_label": actor_label}
        return {"id": movement_id, "status": "Posted"}

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryCoreSummary:
        self.operation = "summary"
        self.arguments = {"workspace": workspace, "actor_label": actor_label}
        return InventoryCoreSummary(workspace, 1, 2, 3, 4, 5, 6, 7, 8)


def _service(repository: _RecordingInventoryRepository) -> InventoryCoreApplicationService:
    return InventoryCoreApplicationService(cast(InventoryCoreRepositoryProtocol, repository))


def test_inventory_application_preserves_exact_quantity_and_governance_context() -> None:
    repository = _RecordingInventoryRepository()
    service = _service(repository)
    lines = (
        {
            "item_code": "MAT-001",
            "quantity": "999999999999.123456",
            "to_warehouse_code": "MAIN",
            "to_location_code": "RECV",
        },
    )

    result = service.create_movement(
        movement_number="MOV/2026/PORT",
        movement_type="Receipt",
        organization_code="ORG",
        entity_code="ENTITY",
        period_id="period-1",
        movement_date="2026-07-28",
        description="Exact inventory boundary",
        lines=lines,
        workspace="regulated",
        source_reference="source-9",
        source_type="Imported",
        actor_label="maker@example.test",
    )

    assert repository.operation == "create_movement"
    assert repository.arguments["lines"] is lines
    assert result["lines"][0]["quantity"] == "999999999999.123456"
    assert repository.arguments["actor_label"] == "maker@example.test"
    assert repository.arguments["workspace"] == "regulated"


def test_inventory_application_delegates_governed_post_and_typed_summary() -> None:
    repository = _RecordingInventoryRepository()
    service = _service(repository)

    assert (
        service.post_movement("movement-1", reason="Independent stock review", actor_label="checker@example.test")[
            "status"
        ]
        == "Posted"
    )
    assert repository.arguments == {
        "movement_id": "movement-1",
        "reason": "Independent stock review",
        "actor_label": "checker@example.test",
    }
    assert service.summary(workspace="regulated", actor_label="auditor").to_dict() == {
        "workspace": "regulated",
        "units_of_measure": 1,
        "items": 2,
        "warehouses": 3,
        "locations": 4,
        "lots_and_serials": 5,
        "draft_movements": 6,
        "posted_movements": 7,
        "voided_movements": 8,
    }


def test_inventory_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    source_path = Path("reconforge/application/inventory_core.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)
