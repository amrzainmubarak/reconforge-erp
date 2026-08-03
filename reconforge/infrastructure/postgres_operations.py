"""PostgreSQL adapter for tenant-scoped operational diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reconforge.application.operations import MigrationStatus
from reconforge.infrastructure.postgres import ConnectionFactory, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository

POSTGRES_MIGRATION_REVISIONS = (
    "0001_postgres_tenant_boundary",
    "0002_postgres_master_data",
    "0003_postgres_ledger",
    "0004_postgres_identity",
    "0005_postgres_fiscal_periods",
    "0006_postgres_close",
    "0007_postgres_outbox_delivery",
    "0008_postgres_evidence_registry",
    "0009_postgres_recon_results",
    "0010_postgres_recon_exec",
    "0011_postgres_recon_ckpts",
    "0012_postgres_jobs",
    "0013_postgres_domain_uow",
    "0014_postgres_operations",
    "0015_postgres_idempotency",
    "0016_postgres_journals",
    "0017_postgres_control_testing",
    "0018_postgres_intercompany",
    "0019_postgres_finance_core",
    "0020_postgres_master_data_app",
    "0021_postgres_payables",
    "0022_postgres_receivables",
    "0023_postgres_matching_app",
    "0024_postgres_inventory_core",
    "0025_postgres_inventory_value",
    "0026_postgres_inventory_reverse",
    "0027_postgres_inventory_planning",
    "0028_postgres_accounts",
    "0029_postgres_approvals",
    "0030_postgres_close_app",
    "0031_postgres_evidence_app",
    "0032_postgres_exceptions",
    "0033_postgres_outbox_app",
    "0034_postgres_federation",
    "0035_postgres_scim",
    "0036_postgres_scim_auth",
    "0037_postgres_service_accounts",
    "0038_postgres_step_up",
    "0039_postgres_emergency_access",
    "0040_postgres_webauthn_mfa",
    "0041_postgres_execution_scope",
    "0042_postgres_job_scope",
    "0043_postgres_export_scope",
    "0044_postgres_business_scope",
    "0045_postgres_workspace_scope",
    "0046_postgres_scope_authority",
    "0047_postgres_scheduler",
    "0048_postgres_notifications",
    "0049_security_center_acl",
    "0050_identity_admin_lifecycle",
    "0051_access_policy_lifecycle",
    "0052_security_governance",
    "0053_audit_administration_acl",
    "0054_pg_consol_ownership",
    "0055_pg_consol_close",
    "0056_pg_policy_delegations",
    "0057_pg_consol_journal_lines",
    "0058_pg_policy_permission_scopes",
)


class PostgresOperationsError(RuntimeError):
    """Safe operational-diagnostics failure."""


def _records(cursor: Any, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True)) for row in rows]


@dataclass(frozen=True)
class PostgresOperationsRepository:
    """Read sanitized operational state from a caller-scoped connection."""

    connection: Any
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", validate_tenant_id(self.tenant_id))

    def audit_chain_ok(self) -> bool:
        try:
            return PostgresAuditEventRepository(self.connection, self.tenant_id).verify().ok
        except Exception:
            return False

    def record_counts(self) -> tuple[int, int]:
        row = self.connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM reconforge.ops_job_history WHERE tenant_id=%s),
              (SELECT COUNT(*) FROM reconforge.ops_error_records WHERE tenant_id=%s)
            """,
            (self.tenant_id, self.tenant_id),
        ).fetchone()
        if row is None:
            raise PostgresOperationsError("Operational record counts are unavailable.")
        return int(row[0]), int(row[1])

    def list_jobs(self) -> list[dict[str, Any]]:
        columns = ("id", "workspace_id", "job_type", "status", "summary", "started_at", "completed_at")
        cursor = self.connection.execute(
            """
            SELECT id, workspace_id, job_type, status, summary, started_at, completed_at
            FROM reconforge.ops_job_history WHERE tenant_id=%s
            ORDER BY started_at DESC, id
            """,
            (self.tenant_id,),
        )
        return _records(cursor, columns)

    def list_errors(self) -> list[dict[str, Any]]:
        columns = ("id", "workspace_id", "source", "error_code", "message", "created_at")
        cursor = self.connection.execute(
            """
            SELECT id, workspace_id, source, error_code, message, created_at
            FROM reconforge.ops_error_records WHERE tenant_id=%s
            ORDER BY created_at DESC, id
            """,
            (self.tenant_id,),
        )
        return _records(cursor, columns)

    def is_local_only(self) -> bool:
        return False


@dataclass(frozen=True)
class PostgresMigrationStatusProvider:
    """Read Alembic state without exposing connection settings to Application code."""

    connection_factory: ConnectionFactory

    def __call__(self, database_locator: str) -> MigrationStatus:
        if not str(database_locator or "").strip():
            raise PostgresOperationsError("Database locator label must not be blank.")
        connection = self.connection_factory.connect()
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except Exception as exc:
            raise PostgresOperationsError("PostgreSQL migration status is unavailable.") from exc
        finally:
            connection.close()
        if row is None:
            raise PostgresOperationsError("PostgreSQL migration state is empty.")
        current = str(row[0])
        try:
            current_index = POSTGRES_MIGRATION_REVISIONS.index(current)
        except ValueError as exc:
            raise PostgresOperationsError("PostgreSQL migration revision is unsupported.") from exc
        return MigrationStatus(
            current_version=current,
            latest_version=POSTGRES_MIGRATION_REVISIONS[-1],
            pending_versions=POSTGRES_MIGRATION_REVISIONS[current_index + 1 :],
        )


POSTGRES_OPERATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.ops_job_history (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    job_type TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL, completed_at TEXT,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, workspace_id)
      REFERENCES reconforge.domain_workspaces(tenant_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.ops_error_records (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    source TEXT NOT NULL, error_code TEXT NOT NULL, message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, workspace_id)
      REFERENCES reconforge.domain_workspaces(tenant_id, id) ON DELETE CASCADE
);
ALTER TABLE reconforge.ops_job_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ops_job_history FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ops_error_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ops_error_records FORCE ROW LEVEL SECURITY;
DO $reconforge$ DECLARE table_name TEXT; BEGIN
  FOREACH table_name IN ARRAY ARRAY['ops_job_history','ops_error_records'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
      EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
    END IF;
  END LOOP;
END $reconforge$;
"""


def install_postgres_operations_schema(connection: Any) -> None:
    connection.execute(POSTGRES_OPERATIONS_SCHEMA_SQL)
