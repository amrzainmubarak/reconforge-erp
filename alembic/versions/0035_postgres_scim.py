"""Add forced-RLS SCIM provisioning lifecycle storage."""

from alembic import op
from reconforge.infrastructure.postgres_scim import POSTGRES_SCIM_SCHEMA_SQL

revision = "0035_postgres_scim"
down_revision = "0034_postgres_federation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_SCIM_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.scim_events")
    op.execute("DROP TABLE IF EXISTS reconforge.scim_group_members")
    op.execute("DROP TABLE IF EXISTS reconforge.scim_groups")
    op.execute("DROP TABLE IF EXISTS reconforge.scim_users")
