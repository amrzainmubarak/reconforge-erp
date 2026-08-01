from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from reconforge.application.close import CloseManagementApplicationService, CloseReadiness


def test_application_delegates_complete_close_contract() -> None:
    repository = Mock()
    repository.period_init.return_value = {"id": "P-1"}
    repository.task_add.return_value = {"id": "T-1"}
    repository.task_dependency.return_value = {"id": "D-1"}
    repository.task_status.return_value = {"id": "T-1", "status": "Complete"}
    readiness = CloseReadiness("P-1", "2026-08", 1, 1, 0, Decimal("100.00"))
    repository.readiness.return_value = readiness
    repository.lock_period.return_value = {"id": "P-1", "status": "Locked"}
    repository.reopen_period.return_value = {"id": "P-1", "status": "Reopened"}
    repository.list_periods.return_value = [{"id": "P-1"}]
    repository.list_tasks.return_value = [{"id": "T-1"}]
    repository.get_period.return_value = {"id": "P-1"}
    repository.get_task.return_value = {"id": "T-1"}
    service = CloseManagementApplicationService(repository)

    assert service.period_init(
        period_name="2026-08", start_date="2026-08-01", end_date="2026-08-31",
        workspace="finance", actor_label="controller", with_default_tasks=False,
    ) == {"id": "P-1"}
    assert service.task_add(
        period_id="P-1", task_code="T-1", name="Review", owner="owner",
        category="Control", risk_rating="high", due_date="2026-09-01",
        actor_label="controller", audit_task=False, autocommit=False,
    ) == {"id": "T-1"}
    assert service.task_dependency(
        task_id="T-1", depends_on_task_id="T-0", actor_label="controller"
    ) == {"id": "D-1"}
    assert service.task_status(
        task_id="T-1", status="Complete", actor_label="reviewer"
    )["status"] == "Complete"
    assert service.readiness(
        period_id="P-1", actor_label="reviewer", audit_read=False, autocommit=False
    ) == readiness
    assert service.lock_period("P-1", actor_label="reviewer")["status"] == "Locked"
    assert service.reopen_period(
        "P-1", reason="Correction", actor_label="controller"
    )["status"] == "Reopened"
    assert service.list_periods() == [{"id": "P-1"}]
    assert service.list_tasks(period_id="P-1", status="Open", owner="owner") == [{"id": "T-1"}]
    assert service.get_period("P-1") == {"id": "P-1"}
    assert service.get_task("T-1") == {"id": "T-1"}
    repository.task_add.assert_called_once_with(
        period_id="P-1", task_code="T-1", name="Review", owner="owner",
        category="Control", risk_rating="high", due_date="2026-09-01",
        actor_label="controller", audit_task=False, autocommit=False,
    )


def test_application_module_has_no_database_or_infrastructure_imports() -> None:
    path = Path(__file__).parents[1] / "reconforge" / "application" / "close.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {str(node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "sqlite3" not in imports
    assert all(not name.startswith("reconforge.infrastructure") for name in imports)
