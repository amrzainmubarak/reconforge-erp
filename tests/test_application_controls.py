"""Contract and scope tests for the backend-neutral control-testing boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reconforge.application.controls import ControlLibraryImportResult, ControlTestingApplicationService
from reconforge.db import connect, run_migrations
from reconforge.platform.controls import ControlTestingService


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def import_library(self, input_path: Path | str, **values: Any) -> ControlLibraryImportResult:
        self.calls.append(("import", (input_path, values)))
        return ControlLibraryImportResult(Path(input_path), 3)

    def plan_tests(self, **values: Any) -> int:
        self.calls.append(("plan", values))
        return 3

    def record_result(self, **values: Any) -> dict[str, Any]:
        self.calls.append(("result", values))
        return {"id": "CTR-1", **values}

    def remediation(self, **values: Any) -> dict[str, Any]:
        self.calls.append(("remediation", values))
        return {"id": "REM-1", **values}

    def report(self) -> dict[str, Any]:
        self.calls.append(("report", {}))
        return {"controls": 3}

    def list_plans(self, *, period_name: str = "") -> list[dict[str, Any]]:
        self.calls.append(("list", period_name))
        return [{"id": "CTP-1", "period_name": period_name}]

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        self.calls.append(("get", plan_id))
        return {"id": plan_id}


def test_control_application_service_preserves_complete_contract(tmp_path: Path) -> None:
    repository = _Repository()
    service = ControlTestingApplicationService(repository)
    source = tmp_path / "controls.csv"
    assert service.import_library(source, workspace="finance", actor_label="owner").imported_rows == 3
    assert service.plan_tests(period_name="2026-07", workspace="finance", sample_size=5, actor_label="owner") == 3
    assert service.record_result(
        plan_id="CTP-1", result_status="Complete", effectiveness_status="Ineffective",
        note="Variance", evidence_id="EVD-1", actor_label="tester",
    )["evidence_id"] == "EVD-1"
    assert service.remediation(
        source_type="control", source_id="CTR-1", action_plan="Correct", owner="owner",
        target_date="2026-08-01", actor_label="tester",
    )["action_plan"] == "Correct"
    assert service.report() == {"controls": 3}
    assert service.list_plans(period_name="2026-07")[0]["id"] == "CTP-1"
    assert service.get_plan("CTP-1") == {"id": "CTP-1"}
    assert [name for name, _ in repository.calls] == ["import", "plan", "result", "remediation", "report", "list", "get"]


def test_ineffective_result_keeps_the_planned_workspace_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "controls-scope.db"
    source = tmp_path / "controls.csv"
    source.write_text("control_code,name,risk_rating\nCTRL-1,Scoped control,high\n", encoding="utf-8")
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = ControlTestingService(connection)
        service.import_library(source, workspace="finance")
        service.plan_tests(period_name="2026-07", workspace="finance")
        plan = service.list_plans(period_name="2026-07")[0]
        service.record_result(
            plan_id=str(plan["id"]), result_status="Completed", effectiveness_status="Ineffective"
        )
        scopes = connection.execute(
            """
            SELECT workspace.name FROM exceptions_queue exception
            JOIN workspaces workspace ON workspace.id = exception.workspace_id
            WHERE exception.source_type = 'control_test'
            """
        ).fetchall()
        assert [row["name"] for row in scopes] == ["finance"]
    finally:
        connection.close()


def test_control_application_module_has_no_database_or_adapter_import() -> None:
    source = Path("reconforge/application/controls.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "reconforge.infrastructure" not in source
