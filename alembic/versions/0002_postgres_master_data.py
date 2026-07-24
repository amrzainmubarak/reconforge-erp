"""Add tenant-scoped PostgreSQL master-data tables."""

from __future__ import annotations

from alembic import op
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL

revision = "0002_postgres_master_data"
down_revision = "0001_postgres_tenant_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the bounded organization master-data schema."""

    op.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)


def downgrade() -> None:
    """Drop only the master-data tables and added organization columns."""

    op.execute("DROP TABLE IF EXISTS reconforge.branches")
    op.execute("DROP TABLE IF EXISTS reconforge.legal_entities")
    op.execute(
        "ALTER TABLE reconforge.organizations "
        "DROP CONSTRAINT IF EXISTS organizations_tenant_base_currency_fk"
    )
    op.execute("DROP TABLE IF EXISTS reconforge.currencies")
    op.execute("DROP INDEX IF EXISTS reconforge.idx_organizations_tenant_code")
    op.execute(
        "ALTER TABLE reconforge.organizations "
        "DROP COLUMN IF EXISTS organization_code, "
        "DROP COLUMN IF EXISTS base_currency, "
        "DROP COLUMN IF EXISTS active, "
        "DROP COLUMN IF EXISTS updated_at"
    )
