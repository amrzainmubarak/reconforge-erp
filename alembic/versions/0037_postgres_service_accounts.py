"""Add tenant-scoped service accounts and hash-only credentials."""

from alembic import op
from reconforge.infrastructure.postgres_service_accounts import POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL

revision = "0037_postgres_service_accounts"
down_revision = "0036_postgres_scim_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.service_account_events")
    op.execute("DROP TABLE IF EXISTS reconforge.service_account_credentials")
    op.execute("DROP TABLE IF EXISTS reconforge.service_account_permissions")
    op.execute("DROP TABLE IF EXISTS reconforge.service_accounts")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_service_account_event_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_service_account_credential_update()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_service_account_credential()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_service_account_permission()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.guard_service_account_update()")
