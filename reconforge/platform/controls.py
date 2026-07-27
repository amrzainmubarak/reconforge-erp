"""Control testing and GRC-lite local workflow foundations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    read_local_record_document,
    require_permission,
    rows_to_dicts,
)
from reconforge.platform.exceptions import ExceptionQueueService


@dataclass(frozen=True)
class ControlLibraryImportResult:
    """Control library import result."""

    source_path: Path
    imported_rows: int


class ControlTestingService:
    """Local control library, test plans, results, and remediation records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def import_library(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> ControlLibraryImportResult:
        """Import a local CSV/JSON control library."""

        require_permission(self.connection, actor_label=actor_label, permission="controls.manage")
        document = read_local_record_document(input_path)
        source_path = document.source_path
        records = document.records
        if not records:
            raise PlatformError("Control library input did not contain any records.")
        workspace_id = ensure_workspace(self.connection, workspace)
        source_checksum = document.checksum_sha256
        source_metadata = {
            "source_file": source_path.name,
            "source_checksum_sha256": source_checksum,
            "source_size_bytes": document.size_bytes,
            "ingress_profile": document.profile_id,
        }
        now = utc_now_text()
        imported = 0
        try:
            for index, record in enumerate(records, start=1):
                control_code = normalize_key(
                    record.get("control_code") or record.get("id") or record.get("control_id"), default=""
                )
                if not control_code:
                    control_code = platform_id("CTRLREF", source_checksum, index)
                control_id = platform_id("CTRL", workspace_id, control_code)
                self.connection.execute(
                    """
                    INSERT INTO control_library (
                        id, workspace_id, control_code, name, owner, frequency,
                        description, risk_rating, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, control_code)
                    DO UPDATE SET
                        name = excluded.name,
                        owner = excluded.owner,
                        frequency = excluded.frequency,
                        description = excluded.description,
                        risk_rating = excluded.risk_rating,
                        updated_at = excluded.updated_at
                    """,
                    (
                        control_id,
                        workspace_id,
                        control_code,
                        normalize_text(record.get("name") or record.get("control_name"), default=control_code),
                        normalize_text(record.get("owner")),
                        normalize_text(record.get("frequency"), default="monthly"),
                        normalize_text(record.get("description")),
                        normalize_key(record.get("risk_rating"), default="medium").lower(),
                        now,
                        now,
                    ),
                )
                imported += 1
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to import control library.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="control_library",
            object_id="import",
            action="control_library_imported",
            metadata={**source_metadata, "imported_rows": imported},
        )
        return ControlLibraryImportResult(source_path=source_path, imported_rows=imported)

    def plan_tests(
        self,
        *,
        period_name: str,
        workspace: str = "default",
        sample_size: int = 0,
        actor_label: str = "local-cli",
    ) -> int:
        """Create test plans for controls in the library."""

        require_permission(self.connection, actor_label=actor_label, permission="controls.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        controls = self.connection.execute(
            "SELECT * FROM control_library WHERE workspace_id = ? ORDER BY control_code",
            (workspace_id,),
        ).fetchall()
        now = utc_now_text()
        count = 0
        for control in controls:
            plan_id = platform_id("CTP", control["id"], period_name)
            self.connection.execute(
                """
                INSERT INTO control_test_plans (
                    id, workspace_id, control_id, period_name, status, planned_by,
                    sample_size, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'Planned', ?, ?, ?, ?)
                ON CONFLICT(control_id, period_name)
                DO UPDATE SET
                    status = excluded.status,
                    planned_by = excluded.planned_by,
                    sample_size = excluded.sample_size,
                    updated_at = excluded.updated_at
                """,
                (plan_id, workspace_id, control["id"], period_name, actor_label, sample_size, now, now),
            )
            count += 1
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="control_test_plan",
            object_id=period_name,
            action="control_tests_planned",
            metadata={"period": period_name, "plan_count": count},
        )
        return count

    def record_result(
        self,
        *,
        plan_id: str,
        result_status: str,
        effectiveness_status: str,
        note: str = "",
        evidence_id: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Record one control test result."""

        require_permission(self.connection, actor_label=actor_label, permission="controls.manage")
        plan = self.get_plan(plan_id)
        result_id = platform_id("CTR", plan_id, utc_now_text())
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO control_test_results (
                    id, test_plan_id, result_status, effectiveness_status, tested_by,
                    note, evidence_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    plan_id,
                    normalize_key(result_status, default="Completed"),
                    normalize_key(effectiveness_status, default="Unknown"),
                    actor_label,
                    note,
                    evidence_id,
                    now,
                    now,
                ),
            )
            self.connection.execute(
                "UPDATE control_test_plans SET status = 'Tested', updated_at = ? WHERE id = ?",
                (now, plan_id),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to record control test result.") from exc
        if normalize_key(effectiveness_status, default="").lower() not in {"effective", "passed", "pass"}:
            control = self._control_for_plan(plan_id)
            ExceptionQueueService(self.connection, autocommit=False).upsert_exception(
                source_type="control_test",
                source_id=result_id,
                description="Control test result is not marked effective.",
                workspace="default",
                period_name=str(plan["period_name"]),
                control_code=str(control["control_code"]),
                risk_rating=str(control["risk_rating"]),
                actor_label=actor_label,
            )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="control_test_result",
            object_id=result_id,
            action="control_test_result_recorded",
            metadata={"plan_id": plan_id, "effectiveness_status": effectiveness_status},
        )
        return dict(self.connection.execute("SELECT * FROM control_test_results WHERE id = ?", (result_id,)).fetchone())

    def remediation(
        self,
        *,
        source_type: str,
        source_id: str,
        action_plan: str,
        owner: str = "",
        target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update remediation metadata for a control/testing issue."""

        require_permission(self.connection, actor_label=actor_label, permission="controls.manage")
        if not normalize_text(action_plan):
            raise PlatformError("Remediation action plan is required.")
        remediation_id = platform_id("REM", source_type, source_id)
        now = utc_now_text()
        self.connection.execute(
            """
            INSERT INTO remediation_plans (
                id, source_type, source_id, owner, status, target_date,
                action_plan, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'Open', ?, ?, ?, ?)
            ON CONFLICT(id)
            DO UPDATE SET
                owner = excluded.owner,
                target_date = excluded.target_date,
                action_plan = excluded.action_plan,
                updated_at = excluded.updated_at
            """,
            (remediation_id, source_type, source_id, owner, target_date, action_plan, now, now),
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="remediation_plan",
            object_id=remediation_id,
            action="remediation_plan_saved",
            metadata={"source_type": source_type, "source_id": source_id},
        )
        return dict(
            self.connection.execute("SELECT * FROM remediation_plans WHERE id = ?", (remediation_id,)).fetchone()
        )

    def report(self) -> dict[str, Any]:
        """Return a compact control testing report."""

        controls = self.connection.execute("SELECT COUNT(*) AS count FROM control_library").fetchone()
        plans = self.connection.execute("SELECT COUNT(*) AS count FROM control_test_plans").fetchone()
        results = self.connection.execute("SELECT COUNT(*) AS count FROM control_test_results").fetchone()
        ineffective = self.connection.execute(
            "SELECT COUNT(*) AS count FROM control_test_results WHERE lower(effectiveness_status) NOT IN ('effective', 'passed', 'pass')",
        ).fetchone()
        return {
            "controls": int(controls["count"] or 0),
            "test_plans": int(plans["count"] or 0),
            "test_results": int(results["count"] or 0),
            "ineffective_results": int(ineffective["count"] or 0),
        }

    def list_plans(self, *, period_name: str = "") -> list[dict[str, Any]]:
        """List control test plans."""

        query = """
            SELECT plan.*, control.control_code, control.name, control.owner, control.frequency, control.risk_rating
            FROM control_test_plans plan
            JOIN control_library control ON control.id = plan.control_id
        """
        params: list[object] = []
        if period_name:
            query += " WHERE plan.period_name = ?"
            params.append(period_name)
        query += " ORDER BY plan.period_name DESC, control.control_code"
        return rows_to_dicts(self.connection.execute(query, params).fetchall())

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        """Read one control test plan."""

        row = self.connection.execute("SELECT * FROM control_test_plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            raise PlatformError("Control test plan not found.")
        return dict(row)

    def _control_for_plan(self, plan_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT control.*
            FROM control_library control
            JOIN control_test_plans plan ON plan.control_id = control.id
            WHERE plan.id = ?
            """,
            (plan_id,),
        ).fetchone()
        if row is None:
            raise PlatformError("Control test plan not found.")
        return dict(row)
