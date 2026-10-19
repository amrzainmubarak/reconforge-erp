"""PostgreSQL tenant/workspace-scoped persistence for consolidated financial statements with FORCE RLS."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from reconforge.domain.consolidated_financial_statements import ConsolidatedFinancialStatements
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError

POSTGRES_CONSOLIDATED_STATEMENTS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidated_statement_runs (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    period_id TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    as_of_date DATE NOT NULL,
    report_digest TEXT NOT NULL,
    statements_payload JSONB NOT NULL,
    prepared_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, report_digest)
);

CREATE INDEX IF NOT EXISTS idx_postgres_consolidated_statements_scope
    ON reconforge.consolidated_statement_runs (tenant_id, workspace_id, group_id, period_id);

ALTER TABLE reconforge.consolidated_statement_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidated_statement_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidated_statement_runs;
CREATE POLICY tenant_scope ON reconforge.consolidated_statement_runs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresConsolidatedStatementsRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for consolidated statement runs."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def save_run(
        self,
        *,
        workspace_id: str,
        statements: ConsolidatedFinancialStatements,
        prepared_by: str = "system",
    ) -> str:
        run_id = f"csr_{statements.group_id}_{statements.period_id}_{statements.report_digest[:12]}"
        now = utc_now_text()
        payload_str = json.dumps(asdict(statements), sort_keys=True)

        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.consolidated_statement_runs (
                        tenant_id, id, workspace_id, group_id, organization_id, reporting_currency,
                        period_id, period_start, period_end, as_of_date,
                        report_digest, statements_payload, prepared_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, report_digest) DO UPDATE SET
                        statements_payload = excluded.statements_payload,
                        prepared_by = excluded.prepared_by
                    """,
                    (
                        self.tenant_id,
                        run_id,
                        workspace_id,
                        statements.group_id,
                        statements.organization_id,
                        statements.reporting_currency,
                        statements.period_id,
                        statements.period_start,
                        statements.period_end,
                        statements.as_of_date,
                        statements.report_digest,
                        payload_str,
                        prepared_by,
                        now,
                    ),
                )

                # Append canonical audit event
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=prepared_by,
                    actor_user_id=prepared_by,
                    object_type="consolidated_financial_statements",
                    object_id=run_id,
                    action="consolidated_statements_generated",
                    after_hash=statements.report_digest,
                    metadata={
                        "workspace_id": workspace_id,
                        "group_id": statements.group_id,
                        "reporting_currency": statements.reporting_currency,
                        "period_id": statements.period_id,
                        "balanced": statements.balance_sheet.get("balanced", False),
                        "total_assets_minor": statements.balance_sheet.get("total_assets_minor", 0),
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL consolidated statement save failed: {exc}") from exc

        return run_id

    def get_run(self, *, workspace_id: str, run_id: str) -> dict[str, Any] | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT id, workspace_id, group_id, organization_id, reporting_currency,
                           period_id, period_start, period_end, as_of_date,
                           report_digest, statements_payload, prepared_by, created_at
                    FROM reconforge.consolidated_statement_runs
                    WHERE tenant_id = %s AND workspace_id = %s AND id = %s
                    """,
                    (self.tenant_id, workspace_id, run_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[10]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                return {
                    "id": row[0],
                    "workspace_id": row[1],
                    "group_id": row[2],
                    "organization_id": row[3],
                    "reporting_currency": row[4],
                    "period_id": row[5],
                    "period_start": str(row[6]),
                    "period_end": str(row[7]),
                    "as_of_date": str(row[8]),
                    "report_digest": row[9],
                    "statements": payload,
                    "prepared_by": row[11],
                    "created_at": str(row[12]),
                }
        except Exception as exc:
            raise PlatformError(f"PostgreSQL consolidated statement read failed: {exc}") from exc

    def list_runs(self, *, workspace_id: str, group_id: str | None = None) -> list[dict[str, Any]]:
        try:
            with self.connection.transaction():
                self._scope()
                if group_id:
                    cur = self.connection.execute(
                        """
                        SELECT id, workspace_id, group_id, organization_id, reporting_currency,
                               period_id, period_start, period_end, as_of_date,
                               report_digest, statements_payload, prepared_by, created_at
                        FROM reconforge.consolidated_statement_runs
                        WHERE tenant_id = %s AND workspace_id = %s AND group_id = %s
                        ORDER BY created_at DESC
                        """,
                        (self.tenant_id, workspace_id, group_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, workspace_id, group_id, organization_id, reporting_currency,
                               period_id, period_start, period_end, as_of_date,
                               report_digest, statements_payload, prepared_by, created_at
                        FROM reconforge.consolidated_statement_runs
                        WHERE tenant_id = %s AND workspace_id = %s
                        ORDER BY created_at DESC
                        """,
                        (self.tenant_id, workspace_id),
                    )
                rows = cur.fetchall()
                results = []
                for r in rows:
                    payload = r[10]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    results.append({
                        "id": r[0],
                        "workspace_id": r[1],
                        "group_id": r[2],
                        "organization_id": r[3],
                        "reporting_currency": r[4],
                        "period_id": r[5],
                        "period_start": str(r[6]),
                        "period_end": str(r[7]),
                        "as_of_date": str(r[8]),
                        "report_digest": r[9],
                        "statements": payload,
                        "prepared_by": r[11],
                        "created_at": str(r[12]),
                    })
                return results
        except Exception as exc:
            raise PlatformError(f"PostgreSQL consolidated statements list failed: {exc}") from exc
