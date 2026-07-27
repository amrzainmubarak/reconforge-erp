"""Add the tenant-scoped local-domain PostgreSQL unit-of-work schema."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_DOMAIN_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_domain", "POSTGRES_DOMAIN_SCHEMA_SQL"
)

revision = "0013_postgres_domain_uow"
down_revision = "0012_postgres_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_DOMAIN_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS domain_audit_events_immutable ON reconforge.domain_audit_events;
        DROP TABLE IF EXISTS reconforge.domain_audit_events;
        DROP TABLE IF EXISTS reconforge.domain_audit_ledger_state;
        DROP TABLE IF EXISTS reconforge.domain_periods;
        DROP TABLE IF EXISTS reconforge.domain_workspaces;
        DROP FUNCTION IF EXISTS reconforge.reject_domain_audit_mutation();
        """
    )
