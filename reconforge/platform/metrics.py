"""Governed local dashboard metrics."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    audit,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
    rows_to_dicts,
)


class MetricsService:
    """Compute local dashboard values from DB-backed workflow tables."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def compute(self, *, workspace: str = "default", period_name: str = "", actor_label: str = "local-cli") -> list[dict[str, Any]]:
        """Compute and store governed metric snapshots."""

        require_permission(self.connection, actor_label=actor_label, permission="metrics.read")
        workspace_id = ensure_workspace(self.connection, workspace)
        definitions = self.lineage()
        values = {
            "close_completion": self._close_completion(workspace_id, period_name),
            "unresolved_high_risk_exceptions": self._unresolved_high_risk(workspace_id, period_name),
            "review_aging": self._review_aging(workspace_id, period_name),
            "evidence_coverage": self._evidence_coverage(workspace_id),
            "control_effectiveness": self._control_effectiveness(workspace_id, period_name),
            "match_rate": self._match_rate(workspace_id),
            "exception_aging": self._exception_aging(workspace_id, period_name),
            "period_readiness": self._period_readiness(workspace_id, period_name),
        }
        now = utc_now_text()
        for definition in definitions:
            key = str(definition["metric_key"])
            value = float(values.get(key, 0.0))
            snapshot_id = platform_id("METS", workspace_id, key, period_name)
            self.connection.execute(
                """
                INSERT INTO metric_snapshots (
                    id, workspace_id, metric_key, period_name, value, value_text, lineage, computed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, metric_key, period_name)
                DO UPDATE SET
                    value = excluded.value,
                    value_text = excluded.value_text,
                    lineage = excluded.lineage,
                    computed_at = excluded.computed_at
                """,
                (snapshot_id, workspace_id, key, period_name, value, str(value), str(definition["lineage"]), now),
            )
        self.connection.commit()
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="metrics",
            object_id=period_name or "all",
            action="metrics_computed",
            metadata={"period": period_name, "metric_count": len(values)},
        )
        return self.dashboard(period_name=period_name)

    def dashboard(self, *, period_name: str = "") -> list[dict[str, Any]]:
        """Return dashboard metric snapshots with definitions and lineage."""

        if period_name:
            rows = self.connection.execute(
                """
                SELECT snapshot.*, definition.name, definition.description
                FROM metric_snapshots snapshot
                JOIN metric_definitions definition ON definition.metric_key = snapshot.metric_key
                WHERE snapshot.period_name = ?
                ORDER BY snapshot.metric_key
                """,
                (period_name,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT snapshot.*, definition.name, definition.description
                FROM metric_snapshots snapshot
                JOIN metric_definitions definition ON definition.metric_key = snapshot.metric_key
                ORDER BY snapshot.period_name, snapshot.metric_key
                """,
            ).fetchall()
        return rows_to_dicts(rows)

    def lineage(self) -> list[dict[str, Any]]:
        """Return governed metric definitions."""

        return rows_to_dicts(self.connection.execute("SELECT * FROM metric_definitions ORDER BY metric_key").fetchall())

    def _close_completion(self, workspace_id: str, period_name: str) -> float:
        row = self.connection.execute(
            """
            SELECT
                COUNT(task.id) AS total_count,
                SUM(CASE WHEN task.status IN ('Complete', 'Not Applicable') THEN 1 ELSE 0 END) AS complete_count
            FROM close_tasks_db task
            JOIN close_periods period ON period.id = task.close_period_id
            WHERE period.workspace_id = ? AND (? = '' OR period.period_name = ?)
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        total = int(row["total_count"] or 0)
        complete = int(row["complete_count"] or 0)
        return round((complete / total) * 100, 2) if total else 0.0

    def _unresolved_high_risk(self, workspace_id: str, period_name: str) -> float:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM exceptions_queue
            WHERE workspace_id = ?
              AND (? = '' OR period_name = ?)
              AND lower(risk_rating) IN ('high', 'critical')
              AND status NOT IN ('Resolved', 'Closed')
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        return float(row["count"] or 0)

    def _review_aging(self, workspace_id: str, period_name: str) -> float:
        row = self.connection.execute(
            """
            SELECT AVG(julianday('now') - julianday(created_at)) AS aging
            FROM account_reconciliation_records
            WHERE workspace_id = ?
              AND (? = '' OR period_name = ?)
              AND status NOT IN ('Complete', 'Accepted Risk')
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        return round(float(row["aging"] or 0.0), 2)

    def _evidence_coverage(self, workspace_id: str) -> float:
        row = self.connection.execute(
            """
            SELECT
                COUNT(DISTINCT requirement.id) AS requirement_count,
                COUNT(DISTINCT link.object_type || ':' || link.object_id) AS covered_count
            FROM evidence_requirements requirement
            LEFT JOIN evidence_links link
                ON link.object_type = requirement.object_type
               AND link.object_id = requirement.object_id
            WHERE requirement.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        total = int(row["requirement_count"] or 0)
        covered = int(row["covered_count"] or 0)
        return round((covered / total) * 100, 2) if total else 100.0

    def _control_effectiveness(self, workspace_id: str, period_name: str) -> float:
        row = self.connection.execute(
            """
            SELECT
                COUNT(result.id) AS total_count,
                SUM(CASE WHEN lower(result.effectiveness_status) = 'effective' THEN 1 ELSE 0 END) AS effective_count
            FROM control_test_results result
            JOIN control_test_plans plan ON plan.id = result.test_plan_id
            WHERE plan.workspace_id = ? AND (? = '' OR plan.period_name = ?)
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        total = int(row["total_count"] or 0)
        effective = int(row["effective_count"] or 0)
        return round((effective / total) * 100, 2) if total else 0.0

    def _match_rate(self, workspace_id: str) -> float:
        row = self.connection.execute(
            """
            SELECT
                COUNT(result.id) AS total_count,
                SUM(CASE WHEN result.status = 'Matched' THEN 1 ELSE 0 END) AS matched_count
            FROM match_results result
            JOIN match_jobs job ON job.id = result.job_id
            WHERE job.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        total = int(row["total_count"] or 0)
        matched = int(row["matched_count"] or 0)
        return round((matched / total) * 100, 2) if total else 0.0

    def _exception_aging(self, workspace_id: str, period_name: str) -> float:
        row = self.connection.execute(
            """
            SELECT AVG(julianday('now') - julianday(created_at)) AS aging
            FROM exceptions_queue
            WHERE workspace_id = ?
              AND (? = '' OR period_name = ?)
              AND status NOT IN ('Resolved', 'Closed')
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        return round(float(row["aging"] or 0.0), 2)

    def _period_readiness(self, workspace_id: str, period_name: str) -> float:
        row = self.connection.execute(
            """
            SELECT AVG(readiness_score) AS readiness
            FROM close_periods
            WHERE workspace_id = ? AND (? = '' OR period_name = ?)
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        return round(float(row["readiness"] or 0.0), 2)
