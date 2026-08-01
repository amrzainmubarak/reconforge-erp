"""Add workspace ownership for the complete Master Data application port."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_master_data_application",
    "POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL",
)

revision = "0020_postgres_master_data_app"
down_revision = "0019_postgres_finance_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.master_data_workspace_periods")
    op.execute("DROP TABLE IF EXISTS reconforge.master_data_workspace_organizations")
    op.execute(
        """ALTER TABLE reconforge.organizations DROP CONSTRAINT IF EXISTS organizations_application_workspace_fk;
        ALTER TABLE reconforge.fiscal_periods DROP CONSTRAINT IF EXISTS fiscal_periods_application_workspace_fk;
        DROP INDEX IF EXISTS reconforge.idx_organizations_workspace_code;
        DROP INDEX IF EXISTS reconforge.idx_fiscal_periods_workspace_name;
        DROP INDEX IF EXISTS reconforge.idx_fiscal_periods_legacy_name;
        ALTER TABLE reconforge.organizations DROP COLUMN IF EXISTS application_workspace_id;
        ALTER TABLE reconforge.fiscal_periods DROP COLUMN IF EXISTS application_workspace_id;
        ALTER TABLE reconforge.fiscal_periods ADD CONSTRAINT fiscal_periods_tenant_id_name_key UNIQUE (tenant_id,name);"""
    )
