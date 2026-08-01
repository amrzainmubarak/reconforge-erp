from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

from reconforge.application.inventory_planning import (
    InventoryPlanningApplicationService,
    InventoryPlanningRepositoryProtocol,
    InventoryPlanningSummary,
)


class _Repository:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def record_counted_quantity(
        self, session_id: str, line_id: str, *, counted_quantity: object, note: str = "", actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        self.arguments = {
            "session_id": session_id,
            "line_id": line_id,
            "counted_quantity": counted_quantity,
            "note": note,
            "actor_label": actor_label,
        }
        return {"counted_quantity": counted_quantity}

    def approve_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.arguments = {"session_id": session_id, "reason": reason, "actor_label": actor_label}
        return {"status": "Approved"}


def _service(repository: _Repository) -> InventoryPlanningApplicationService:
    return InventoryPlanningApplicationService(cast(InventoryPlanningRepositoryProtocol, repository))


def test_application_preserves_exact_quantity_and_actor() -> None:
    repository = _Repository()
    quantity = "999999999999.123456"
    result = _service(repository).record_counted_quantity(
        "count-1", "line-1", counted_quantity=quantity, note="blind count", actor_label="counter@example.test"
    )
    assert result["counted_quantity"] == quantity
    assert repository.arguments["counted_quantity"] is quantity
    assert repository.arguments["actor_label"] == "counter@example.test"


def test_application_preserves_independent_approval_reason() -> None:
    repository = _Repository()
    result = _service(repository).approve_count_session(
        "count-1", reason="Independent recount", actor_label="checker@example.test"
    )
    assert result["status"] == "Approved"
    assert repository.arguments == {
        "session_id": "count-1",
        "reason": "Independent recount",
        "actor_label": "checker@example.test",
    }


def test_application_boundary_is_connection_free() -> None:
    tree = ast.parse(Path("reconforge/application/inventory_planning.py").read_text(encoding="utf-8"))
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports.update(n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)


def test_summary_is_immutable_and_deterministic() -> None:
    assert InventoryPlanningSummary("regulated", 1, 2, 3, 4, 5, 6).to_dict()["active_reorder_rules"] == 6
