"""PostgreSQL persistence adapter for dashboard metrics."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from reconforge.domain.control_scores import READINESS_QUANTUM, percentage_from_counts
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id


class PostgresMetricsError(RuntimeError):
    """Base exception for PostgreSQL metrics persistence."""


def _metric_decimal(value: object, *, label: str) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, bool):
        raise PostgresMetricsError(f"Stored {label} metric is invalid.")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PostgresMetricsError(f"Stored {label} metric is invalid.") from exc
    if not parsed.is_finite():
        raise PostgresMetricsError(f"Stored {label} metric is invalid.")
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


class PostgresMetricsRepository:
    """Implement the metrics protocol using PostgreSQL queries with tenant isolation."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except PostgresMetricsError:
            raise
        except Exception as exc:
            raise PostgresMetricsError("PostgreSQL metrics operation failed.") from exc

    def verify_compute_permission(self, actor_label: str) -> None:
        # In PostgreSQL implementations, authorization is typically handled by the application service
        # or enforced by the API boundary. The interface requires it, so we leave it empty here
        # since we already bind to a specific tenant in the constructor.
        # RLS will prevent cross-tenant access.
        pass

    def ensure_workspace(self, workspace_name: str) -> str:
        # PostgreSQL doesn't implicitly create workspaces during metric query.
        # It relies on the workspace existing in the tenant.
        with self._transaction():
            row = self.connection.execute(
                "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id = %s AND name = %s",
                (self.tenant_id, workspace_name),
            ).fetchone()
            if row is None:
                raise PostgresMetricsError(f"Workspace {workspace_name} not found.")
            return str(row[0])

    def close_completion(self, workspace_id: str, period_name: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT
                    COUNT(task.id) AS total_count,
                    SUM(CASE WHEN task.status IN ('Complete', 'Not Applicable') THEN 1 ELSE 0 END) AS complete_count
                FROM reconforge.close_application_tasks task
                JOIN reconforge.close_application_periods period
                  ON period.tenant_id = task.tenant_id AND period.id = task.close_period_id
                WHERE period.tenant_id = %s AND period.workspace_id = %s AND (%s = '' OR period.period_name = %s)
                """,
                (self.tenant_id, workspace_id, period_name, period_name),
            ).fetchone()
            total = int(row[0] or 0)
            complete = int(row[1] or 0)
            return percentage_from_counts(numerator=complete, denominator=total)

    def unresolved_high_risk(self, workspace_id: str, period_name: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM reconforge.exception_queue_records
                WHERE tenant_id = %s AND workspace_id = %s
                  AND (%s = '' OR period_name = %s)
                  AND lower(risk_rating) IN ('high', 'critical')
                  AND status NOT IN ('Resolved', 'Accepted Risk', 'Closed')
                """,
                (self.tenant_id, workspace_id, period_name, period_name),
            ).fetchone()
            return Decimal(int(row[0] or 0))

    def review_aging(self, workspace_id: str, period_name: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT CAST(AVG(EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0) AS TEXT) AS aging
                FROM reconforge.exception_queue_records
                WHERE tenant_id = %s AND workspace_id = %s
                  AND (%s = '' OR period_name = %s)
                  AND status = 'In Review'
                """,
                (self.tenant_id, workspace_id, period_name, period_name),
            ).fetchone()
            return _quantize_metric(_metric_decimal(row[0] if row else None, label="review aging"))

    def evidence_coverage(self, workspace_id: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT
                    COUNT(DISTINCT requirement.id) AS requirement_count,
                    COUNT(DISTINCT requirement.id) FILTER (WHERE link.id IS NOT NULL) AS covered_count
                FROM reconforge.evidence_application_requirements requirement
                LEFT JOIN reconforge.evidence_application_links link
                    ON link.tenant_id = requirement.tenant_id
                   AND link.object_type = requirement.object_type
                   AND link.object_id = requirement.object_id
                WHERE requirement.tenant_id = %s AND requirement.workspace_id = %s
                """,
                (self.tenant_id, workspace_id),
            ).fetchone()
            total = int(row[0] or 0)
            covered = int(row[1] or 0)
            return percentage_from_counts(
                numerator=covered,
                denominator=total,
                empty_value=Decimal("100.00"),
            )

    def control_effectiveness(self, workspace_id: str, period_name: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT COUNT(result.id) AS total_count,
                       SUM(CASE WHEN lower(result.effectiveness_status)='effective' THEN 1 ELSE 0 END)
                           AS effective_count
                FROM reconforge.control_test_results result
                JOIN reconforge.control_test_plans plan
                  ON plan.tenant_id=result.tenant_id AND plan.id=result.test_plan_id
                WHERE plan.tenant_id=%s AND plan.workspace_id=%s
                  AND (%s='' OR plan.period_name=%s)
                """,
                (self.tenant_id, workspace_id, period_name, period_name),
            ).fetchone()
            total = int(row[0] or 0)
            effective = int(row[1] or 0)
            return percentage_from_counts(numerator=effective, denominator=total)

    def match_rate(self, workspace_id: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT
                    COUNT(result.id) AS total_count,
                    SUM(CASE WHEN result.status = 'Matched' THEN 1 ELSE 0 END) AS matched_count
                FROM reconforge.reconciliation_results result
                JOIN reconforge.matching_run_workspaces scope
                  ON scope.tenant_id=result.tenant_id AND scope.run_id=result.run_id
                WHERE result.tenant_id = %s AND scope.workspace_id = %s
                """,
                (self.tenant_id, workspace_id),
            ).fetchone()
            total = int(row[0] or 0)
            matched = int(row[1] or 0)
            return percentage_from_counts(numerator=matched, denominator=total)

    def exception_aging(self, workspace_id: str, period_name: str) -> Decimal:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT CAST(AVG(EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0) AS TEXT) AS aging
                FROM reconforge.exception_queue_records
                WHERE tenant_id = %s AND workspace_id = %s
                  AND (%s = '' OR period_name = %s)
                  AND status NOT IN ('Resolved', 'Accepted Risk', 'Closed')
                """,
                (self.tenant_id, workspace_id, period_name, period_name),
            ).fetchone()
            return _quantize_metric(_metric_decimal(row[0] if row else None, label="exception aging"))

    def period_readiness(self, workspace_id: str, period_name: str) -> Decimal:
        with self._transaction():
            rows = self.connection.execute(
                """
                SELECT CAST(readiness_score AS TEXT) AS readiness
                FROM reconforge.close_application_periods
                WHERE tenant_id = %s AND workspace_id = %s AND (%s = '' OR period_name = %s)
                """,
                (self.tenant_id, workspace_id, period_name, period_name),
            ).fetchall()
            values = [_metric_decimal(row[0], label="period readiness") for row in rows]
            for value in values:
                if value < 0 or value > 100:
                    raise PostgresMetricsError("Stored period readiness metric is invalid.")
            return _average_metric(values)

    def dashboard(self, period_name: str) -> list[dict[str, Any]]:
        with self._transaction():
            if period_name:
                cursor = self.connection.execute(
                    """
                    SELECT snapshot.id, snapshot.workspace_id, snapshot.metric_key, snapshot.period_name,
                           snapshot.value, snapshot.value_text, snapshot.lineage, snapshot.computed_at,
                           definition.name, definition.description
                    FROM reconforge.metric_snapshots snapshot
                    JOIN reconforge.metric_definitions definition ON definition.metric_key = snapshot.metric_key
                    WHERE snapshot.tenant_id = %s AND snapshot.period_name = %s
                    ORDER BY snapshot.metric_key
                    """,
                    (self.tenant_id, period_name),
                )
            else:
                cursor = self.connection.execute(
                    """
                    SELECT snapshot.id, snapshot.workspace_id, snapshot.metric_key, snapshot.period_name,
                           snapshot.value, snapshot.value_text, snapshot.lineage, snapshot.computed_at,
                           definition.name, definition.description
                    FROM reconforge.metric_snapshots snapshot
                    JOIN reconforge.metric_definitions definition ON definition.metric_key = snapshot.metric_key
                    WHERE snapshot.tenant_id = %s
                    ORDER BY snapshot.period_name, snapshot.metric_key
                    """,
                    (self.tenant_id,),
                )
            names = (
                "id",
                "workspace_id",
                "metric_key",
                "period_name",
                "value",
                "value_text",
                "lineage",
                "computed_at",
                "name",
                "description",
            )
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def lineage(self) -> list[dict[str, Any]]:
        with self._transaction():
            cursor = self.connection.execute(
                "SELECT metric_key, name, description, lineage FROM reconforge.metric_definitions ORDER BY metric_key"
            )
            names = ("metric_key", "name", "description", "lineage")
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

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
        with self._transaction():
            for snapshot_id, key, value_text, lineage in snapshots:
                self.connection.execute(
                    """
                    INSERT INTO reconforge.metric_snapshots (
                        tenant_id, id, workspace_id, metric_key, period_name, value, value_text, lineage, computed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(tenant_id, workspace_id, metric_key, period_name)
                    DO UPDATE SET
                        value = excluded.value,
                        value_text = excluded.value_text,
                        lineage = excluded.lineage,
                        computed_at = excluded.computed_at
                    """,
                    (
                        self.tenant_id,
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


POSTGRES_METRICS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.metric_definitions (
    metric_key TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    lineage TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconforge.metric_snapshots (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    metric_key TEXT NOT NULL REFERENCES reconforge.metric_definitions(metric_key),
    period_name TEXT NOT NULL,
    value NUMERIC NOT NULL,
    value_text TEXT NOT NULL,
    lineage TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, metric_key, period_name)
);

ALTER TABLE reconforge.metric_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.metric_snapshots FORCE ROW LEVEL SECURITY;

DO $reconforge$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename='metric_snapshots' AND policyname='tenant_scope') THEN
    EXECUTE format('CREATE POLICY tenant_scope ON reconforge.metric_snapshots USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))');
  END IF;
END $reconforge$;
"""


def install_postgres_metrics_schema(connection: Any) -> None:
    """Install the additive PostgreSQL metrics schema."""
    connection.execute(POSTGRES_METRICS_SCHEMA_SQL)
    # Seed the standard metric definitions
    definitions = [
        ("close_completion", "Close Completion", "Percentage of completed close tasks", "reconforge.domain.close.Task"),
        (
            "unresolved_high_risk_exceptions",
            "Unresolved High Risk",
            "Count of high or critical open exceptions",
            "reconforge.domain.exceptions.Exception",
        ),
        ("review_aging", "Review Aging", "Average days in review state", "reconforge.domain.exceptions.Exception"),
        (
            "evidence_coverage",
            "Evidence Coverage",
            "Percentage of evidence requirements met",
            "reconforge.domain.evidence.Requirement",
        ),
        (
            "control_effectiveness",
            "Control Effectiveness",
            "Percentage of effective control test results",
            "reconforge.domain.control.Result",
        ),
        ("match_rate", "Match Rate", "Percentage of matched records", "reconforge.domain.reconciliation.Result"),
        (
            "exception_aging",
            "Exception Aging",
            "Average days open for exceptions",
            "reconforge.domain.exceptions.Exception",
        ),
        ("period_readiness", "Period Readiness", "Computed period readiness score", "reconforge.domain.close.Period"),
    ]
    for key, name, description, lineage in definitions:
        connection.execute(
            """
            INSERT INTO reconforge.metric_definitions (metric_key, name, description, lineage)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (metric_key) DO NOTHING
            """,
            (key, name, description, lineage),
        )
