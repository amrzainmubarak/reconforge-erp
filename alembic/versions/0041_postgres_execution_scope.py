"""Add explicit workspace, organization, and legal-entity RLS scope."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_execution_scope", "POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL"
)

revision = "0041_postgres_execution_scope"
down_revision = "0040_postgres_webauthn_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    for table_name in (
        "domain_workspaces", "domain_periods", "master_data_workspace_organizations",
        "organizations", "legal_entities", "branches",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_scope ON reconforge.{table_name}")
        column = "id" if table_name == "tenants" else "tenant_id"
        op.execute(
            f"CREATE POLICY tenant_scope ON reconforge.{table_name} "
            f"USING ({column}=current_setting('app.tenant_id',true)) "
            f"WITH CHECK ({column}=current_setting('app.tenant_id',true))"
        )
