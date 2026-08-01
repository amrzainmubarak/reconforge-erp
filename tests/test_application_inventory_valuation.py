from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from reconforge.application.inventory_valuation import (
    InventoryValuationApplicationService,
    InventoryValuationRepositoryProtocol,
    InventoryValuationSummary,
)


class _RecordingValuationRepository:
    def __init__(self) -> None:
        self.operation = ""
        self.arguments: dict[str, object] = {}

    def create_document(
        self,
        *,
        valuation_number: str,
        movement_id: str,
        policy_code: str,
        input_costs: Sequence[Mapping[str, object]] = (),
        valuation_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self.operation = "create_document"
        self.arguments = {
            "valuation_number": valuation_number,
            "movement_id": movement_id,
            "policy_code": policy_code,
            "input_costs": input_costs,
            "valuation_date": valuation_date,
            "actor_label": actor_label,
        }
        return {"id": "valuation-1", "input_costs": list(input_costs)}

    def approve_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.operation = "approve_document"
        self.arguments = {"document_id": document_id, "reason": reason, "actor_label": actor_label}
        return {"id": document_id, "status": "Approved", "total_value_minor": 9_999_999_999_999}


def _service(repository: _RecordingValuationRepository) -> InventoryValuationApplicationService:
    return InventoryValuationApplicationService(cast(InventoryValuationRepositoryProtocol, repository))


def test_inventory_valuation_application_preserves_exact_cost_inputs_and_actor() -> None:
    repository = _RecordingValuationRepository()
    service = _service(repository)
    costs = ({"cost_type": "Freight", "amount_minor": 9_999_999_999_999},)

    result = service.create_document(
        valuation_number="VAL/2026/PORT",
        movement_id="movement-1",
        policy_code="FIFO-KWD",
        input_costs=costs,
        valuation_date="2026-07-28",
        actor_label="maker@example.test",
    )

    assert repository.operation == "create_document"
    assert repository.arguments["input_costs"] is costs
    assert result["input_costs"][0]["amount_minor"] == 9_999_999_999_999
    assert repository.arguments["actor_label"] == "maker@example.test"


def test_inventory_valuation_application_preserves_checker_reason_and_minor_units() -> None:
    repository = _RecordingValuationRepository()
    approved = _service(repository).approve_document(
        "valuation-1", reason="Independent evidence review", actor_label="checker@example.test"
    )

    assert approved["total_value_minor"] == 9_999_999_999_999
    assert repository.arguments == {
        "document_id": "valuation-1",
        "reason": "Independent evidence review",
        "actor_label": "checker@example.test",
    }


def test_inventory_valuation_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    source_path = Path("reconforge/application/inventory_valuation.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)


def test_inventory_valuation_summary_is_immutable_and_deterministic() -> None:
    summary = InventoryValuationSummary("regulated", 1, 2, 3, 4, 5)
    assert summary.to_dict() == {
        "workspace": "regulated",
        "policies": 1,
        "draft_documents": 2,
        "approved_documents": 3,
        "open_layers": 4,
        "unvalued_posted_movements": 5,
    }
