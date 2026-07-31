"""Add durable PostgreSQL federation replay, links, and audit events."""

from alembic import op
from reconforge.infrastructure.postgres_federation import POSTGRES_FEDERATION_SCHEMA_SQL

revision = "0034_postgres_federation"
down_revision = "0033_postgres_outbox_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_FEDERATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.federation_identity_events")
    op.execute("DROP TABLE IF EXISTS reconforge.federation_identity_links")
    op.execute("DROP TABLE IF EXISTS reconforge.federation_assertion_replays")
    op.execute("DROP TABLE IF EXISTS reconforge.federation_login_challenges")
