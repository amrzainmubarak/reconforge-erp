from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.audit import list_audit_events
from reconforge.db import connect, run_migrations
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError
from reconforge.platform.evidence import EvidenceRegistryService
from reconforge.platform.metrics import MetricsService


def test_close_evidence_and_metrics_foundations(tmp_path: Path) -> None:
    db_path = tmp_path / "close_evidence_metrics.db"
    run_migrations(db_path)
    evidence_file = tmp_path / "support.txt"
    evidence_file.write_text("synthetic support only\n", encoding="utf-8")

    connection = connect(db_path, require_exists=True)
    try:
        close = CloseManagementService(connection)
        period = close.period_init(period_name="2026-05", start_date="2026-05-01", end_date="2026-05-31")
        tasks = close.list_tasks(period_id=str(period["id"]))
        close.task_status(task_id=str(tasks[0]["id"]), status="Blocked", blocker_reason="Waiting for export")
        with pytest.raises(PlatformError, match="blocked"):
            close.lock_period(str(period["id"]))
        readiness = close.readiness(period_id=str(period["id"]))

        evidence = EvidenceRegistryService(connection)
        requirement = evidence.requirement(
            object_type="reconciliation",
            object_id="REC-1",
            requirement_code="TB",
            description="Trial balance support",
        )
        registered = evidence.register(evidence_file, evidence_code="EV-1", object_type="reconciliation", object_id="REC-1")
        verification = evidence.verify(str(registered["id"]))
        coverage = evidence.coverage()

        metrics = MetricsService(connection).compute(period_name="2026-05")
        metric_keys = {metric["metric_key"] for metric in metrics}
        audit_actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()

    assert readiness.total_tasks == 5
    assert readiness.blocked_tasks == 1
    assert verification.ok is True
    assert requirement["requirement_code"] == "TB"
    assert coverage["coverage_pct"] == 100.0
    assert {"close_completion", "evidence_coverage", "period_readiness"} <= metric_keys
    assert "close_task_status_updated" in audit_actions
    assert "evidence_registered" in audit_actions
    assert "metrics_computed" in audit_actions
