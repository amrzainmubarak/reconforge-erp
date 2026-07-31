from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.application.intercompany import (
    IntercompanyApplicationService,
    IntercompanyImportResult,
)


class _Repository:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def import_transactions(
        self, input_path: Path | str, *, workspace: str = "default",
        default_period: str = "current", actor_label: str = "local-cli",
    ) -> IntercompanyImportResult:
        self.calls.append(("import", {
            "input_path": input_path, "workspace": workspace,
            "default_period": default_period, "actor_label": actor_label,
        }))
        return IntercompanyImportResult(self.source, 2)

    def match(
        self, *, workspace: str = "default", period_name: str = "",
        tolerance: object = Decimal("0.01"), actor_label: str = "local-cli",
    ) -> int:
        self.calls.append(("match", {
            "workspace": workspace, "period_name": period_name,
            "tolerance": tolerance, "actor_label": actor_label,
        }))
        return 1

    def settle(
        self, case_id: str, *, settlement_status: str = "Settled", dispute_owner: str = "",
        evidence_note: str = "", actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self.calls.append(("settle", {
            "case_id": case_id, "settlement_status": settlement_status,
            "dispute_owner": dispute_owner, "evidence_note": evidence_note,
            "actor_label": actor_label,
        }))
        return {"id": case_id, "status": "Resolved"}

    def cases(self, *, status: str = "") -> list[dict[str, Any]]:
        self.calls.append(("cases", {"status": status}))
        return [{"id": "ICC-1"}]

    def get_case(self, case_id: str) -> dict[str, Any]:
        self.calls.append(("get", {"case_id": case_id}))
        return {"id": case_id}


def test_application_delegates_complete_intercompany_contract(tmp_path: Path) -> None:
    source = tmp_path / "intercompany.csv"
    repository = _Repository(source)
    service = IntercompanyApplicationService(repository)

    assert service.import_transactions(
        source, workspace="finance", default_period="2026-08", actor_label="controller"
    ) == IntercompanyImportResult(source, 2)
    assert service.match(
        workspace="finance", period_name="2026-08", tolerance="0.005", actor_label="reviewer"
    ) == 1
    assert service.settle(
        "ICC-1", settlement_status="Disputed", dispute_owner="owner",
        evidence_note="note", actor_label="reviewer",
    ) == {"id": "ICC-1", "status": "Resolved"}
    assert service.cases(status="Open") == [{"id": "ICC-1"}]
    assert service.get_case("ICC-1") == {"id": "ICC-1"}
    assert [name for name, _ in repository.calls] == ["import", "match", "settle", "cases", "get"]
    assert repository.calls[1][1]["tolerance"] == "0.005"


def test_application_module_has_no_database_or_infrastructure_imports() -> None:
    path = Path(__file__).parents[1] / "reconforge" / "application" / "intercompany.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "sqlite3" not in imports
    assert all(not name.startswith("reconforge.infrastructure") for name in imports)
