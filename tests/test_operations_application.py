from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reconforge.application.operations import MigrationStatus, OperationsApplicationService
from reconforge.db import connect, run_migrations
from reconforge.platform.operations import OperationsService


@dataclass
class FakeOperationsRepository:
    audit_ok: bool = True
    counts: tuple[int, int] = (2, 1)
    jobs: list[dict[str, Any]] = field(default_factory=lambda: [{"id": "JOB-1"}])
    errors: list[dict[str, Any]] = field(default_factory=lambda: [{"id": "ERR-1"}])

    def audit_chain_ok(self) -> bool:
        return self.audit_ok

    def record_counts(self) -> tuple[int, int]:
        return self.counts

    def list_jobs(self) -> list[dict[str, Any]]:
        return self.jobs

    def list_errors(self) -> list[dict[str, Any]]:
        return self.errors


def test_application_composes_health_without_database_dependency() -> None:
    repository = FakeOperationsRepository()
    service = OperationsApplicationService(
        repository,
        lambda locator: MigrationStatus(4, 6, (5, 6)),
    )

    assert service.health("opaque-database-locator") == {
        "database_reachable": True,
        "schema_version": 4,
        "latest_schema_version": 6,
        "pending_migrations": 2,
        "audit_chain_ok": True,
        "job_records": 2,
        "error_records": 1,
        "local_only": True,
    }
    assert service.jobs() == [{"id": "JOB-1"}]
    assert service.errors() == [{"id": "ERR-1"}]


def test_connection_compatibility_adapter_preserves_job_and_error_shapes(tmp_path: Path) -> None:
    database_path = tmp_path / "operations.db"
    run_migrations(database_path)
    connection = connect(database_path)
    service = OperationsService(connection)
    connection.execute(
        "INSERT INTO workspaces (id, name, local_first_note, created_at) "
        "VALUES ('WS-1', 'Operations', '', '2026-01-01T00:00:00Z')"
    )
    connection.execute(
        "INSERT INTO ops_job_history (id, workspace_id, job_type, status, summary, started_at) "
        "VALUES ('JOB-1', 'WS-1', 'import', 'completed', 'safe', '2026-01-01T00:00:00Z')"
    )
    connection.execute(
        "INSERT INTO ops_error_records (id, workspace_id, source, error_code, message, created_at) "
        "VALUES ('ERR-1', 'WS-1', 'worker', 'SAFE-1', 'redacted', '2026-01-01T00:00:00Z')"
    )
    assert service.jobs()[0]["id"] == "JOB-1"
    assert service.errors()[0]["id"] == "ERR-1"
    health = service.health(str(database_path))
    assert health["database_reachable"] is True
    assert health["schema_version"] == health["latest_schema_version"]
    assert health["pending_migrations"] == 0
    assert health["audit_chain_ok"] is True
    assert health["job_records"] == 1
    assert health["error_records"] == 1
    assert health["local_only"] is True
    connection.close()
