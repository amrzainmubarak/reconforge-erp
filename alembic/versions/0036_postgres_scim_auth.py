"""Add hash-only SCIM client credentials."""

from alembic import op
from reconforge.infrastructure.postgres_scim_auth import POSTGRES_SCIM_AUTH_SCHEMA_SQL

revision = "0036_postgres_scim_auth"
down_revision = "0035_postgres_scim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_SCIM_AUTH_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.scim_credentials")
