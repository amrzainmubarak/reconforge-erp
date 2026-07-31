from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

from reconforge.application.inventory_valuation_reversal import (
    InventoryValuationReversalApplicationService,
    InventoryValuationReversalRepositoryProtocol,
    InventoryValuationReversalSummary,
)


class _RecordingReversalRepository:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def create_reversal(
        self,
        *,
        reversal_number: str,
        original_valuation_document_id: str,
        reversal_movement_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self.arguments = {
            "reversal_number": reversal_number,
            "original_valuation_document_id": original_valuation_document_id,
            "reversal_movement_id": reversal_movement_id,
            "actor_label": actor_label,
        }
        return {"id": "reversal-1", "total_value_minor": 9_999_999_999_999}

    def approve_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        self.arguments = {"reversal_id": reversal_id, "reason": reason, "actor_label": actor_label}
        return {"id": reversal_id, "status": "Approved", "total_value_minor": 9_999_999_999_999}


def _service(repository: _RecordingReversalRepository) -> InventoryValuationReversalApplicationService:
    return InventoryValuationReversalApplicationService(cast(InventoryValuationReversalRepositoryProtocol, repository))


def test_reversal_application_preserves_lineage_actor_and_exact_minor_units() -> None:
    repository = _RecordingReversalRepository()
    result = _service(repository).create_reversal(
        reversal_number="REV/2026/PORT",
        original_valuation_document_id="valuation-1",
        reversal_movement_id="movement-2",
        actor_label="maker@example.test",
    )
    assert result["total_value_minor"] == 9_999_999_999_999
    assert repository.arguments["original_valuation_document_id"] == "valuation-1"
    assert repository.arguments["actor_label"] == "maker@example.test"


def test_reversal_application_preserves_checker_reason() -> None:
    repository = _RecordingReversalRepository()
    approved = _service(repository).approve_reversal(
        "reversal-1", reason="Independent evidence review", actor_label="checker@example.test"
    )
    assert approved["status"] == "Approved"
    assert repository.arguments == {
        "reversal_id": "reversal-1",
        "reason": "Independent evidence review",
        "actor_label": "checker@example.test",
    }


def test_reversal_application_boundary_has_no_database_or_infrastructure_dependency() -> None:
    path = Path("reconforge/application/inventory_valuation_reversal.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    assert "sqlite3" not in imports
    assert not any(name.startswith("reconforge.infrastructure") for name in imports)


def test_reversal_summary_is_immutable_and_deterministic() -> None:
    summary = InventoryValuationReversalSummary("regulated", 1, 2, 3, 4, 5)
    assert summary.to_dict() == {
        "workspace": "regulated",
        "draft_reversals": 1,
        "approved_reversals": 2,
        "cancelled_reversals": 3,
        "approved_effects": 4,
        "finance_drafts": 5,
    }
