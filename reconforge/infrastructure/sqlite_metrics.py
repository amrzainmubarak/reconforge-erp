"""SQLite persistence adapter for dashboard metrics."""

from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from reconforge.domain.control_scores import READINESS_QUANTUM, percentage_from_counts
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    require_permission,
    rows_to_dicts,
)


def _metric_decimal(value: object, *, label: str) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, bool):
        raise PlatformError(f"Stored {label} metric is invalid.")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PlatformError(f"Stored {label} metric is invalid.") from exc
    if not parsed.is_finite():
        raise PlatformError(f"Stored {label} metric is invalid.")
    return parsed


def _quantize_metric(value: Decimal) -> Decimal:
    integer_digits = max(1, value.adjusted() + 1) if value else 1
    required_precision = max(28, len(value.as_tuple().digits) + 4, integer_digits + 4)
    with localcontext() as context:
        context.prec = required_precision
        return value.quantize(READINESS_QUANTUM, rounding=ROUND_HALF_UP)


def _average_metric(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0.00")
    max_adjusted = max((value.adjusted() for value in values if value), default=0)
    min_exponent = min((int(value.as_tuple().exponent) for value in values), default=0)
    required_precision = max(28, max_adjusted - min_exponent + len(str(len(values))) + 6)
    with localcontext() as context:
        context.prec = required_precision
        average = sum(values, Decimal(0)) / Decimal(len(values))
    return _quantize_metric(average)


class SQLiteMetricsRepository:
    """Implement the metrics protocol using direct SQLite queries."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def verify_compute_permission(self, actor_label: str) -> None:
        require_permission(self.connection, actor_label=actor_label, permission="metrics.read")

    def ensure_workspace(self, workspace_name: str) -> str:
        return ensure_workspace(self.connection, workspace_name)

    def close_completion(self, workspace_id: str, period_name: str) -> Decimal:
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
        return percentage_from_counts(numerator=complete, denominator=total)

    def unresolved_high_risk(self, workspace_id: str, period_name: str) -> Decimal:
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
        return Decimal(int(row["count"] or 0))

    def review_aging(self, workspace_id: str, period_name: str) -> Decimal:
        row = self.connection.execute(
            """
            SELECT CAST(AVG(julianday('now') - julianday(created_at)) AS TEXT) AS aging
            FROM account_reconciliation_records
            WHERE workspace_id = ?
              AND (? = '' OR period_name = ?)
              AND status NOT IN ('Complete', 'Accepted Risk')
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        return _quantize_metric(_metric_decimal(row["aging"], label="review aging"))

    def evidence_coverage(self, workspace_id: str) -> Decimal:
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
        return percentage_from_counts(
            numerator=covered,
            denominator=total,
            empty_value=Decimal("100.00"),
        )

    def control_effectiveness(self, workspace_id: str, period_name: str) -> Decimal:
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
        return percentage_from_counts(numerator=effective, denominator=total)

    def match_rate(self, workspace_id: str) -> Decimal:
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
        return percentage_from_counts(numerator=matched, denominator=total)

    def exception_aging(self, workspace_id: str, period_name: str) -> Decimal:
        row = self.connection.execute(
            """
            SELECT CAST(AVG(julianday('now') - julianday(created_at)) AS TEXT) AS aging
            FROM exceptions_queue
            WHERE workspace_id = ?
              AND (? = '' OR period_name = ?)
              AND status NOT IN ('Resolved', 'Closed')
            """,
            (workspace_id, period_name, period_name),
        ).fetchone()
        return _quantize_metric(_metric_decimal(row["aging"], label="exception aging"))

    def period_readiness(self, workspace_id: str, period_name: str) -> Decimal:
        rows = self.connection.execute(
            """
            SELECT CAST(readiness_score AS TEXT) AS readiness
            FROM close_periods
            WHERE workspace_id = ? AND (? = '' OR period_name = ?)
            """,
            (workspace_id, period_name, period_name),
        ).fetchall()
        values = [_metric_decimal(row["readiness"], label="period readiness") for row in rows]
        for value in values:
            if value < 0 or value > 100:
                raise PlatformError("Stored period readiness metric is invalid.")
        return _average_metric(values)

    def dashboard(self, period_name: str) -> list[dict[str, Any]]:
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
        return rows_to_dicts(self.connection.execute("SELECT * FROM metric_definitions ORDER BY metric_key").fetchall())

    def save_snapshots_and_audit(
        self,
        *,
        actor_label: str,
        workspace_id: str,
        period_name: str,
        snapshots: list[tuple[str, str, str, str]],
        computed_at: str,
        metric_count: int,
    ) -> None:
        for snapshot_id, key, value_text, lineage in snapshots:
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
                (
                    snapshot_id,
                    workspace_id,
                    key,
                    period_name,
                    value_text,
                    value_text,
                    lineage,
                    computed_at,
                ),
            )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="metrics",
            object_id=period_name or "all",
            action="metrics_computed",
            metadata={"period": period_name, "metric_count": metric_count},
        )
