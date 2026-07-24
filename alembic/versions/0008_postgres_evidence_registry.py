"""Add the tenant-scoped PostgreSQL evidence registry."""

from alembic import op
from reconforge.infrastructure.postgres_evidence import POSTGRES_EVIDENCE_SCHEMA_SQL

revision = "0008_postgres_evidence_registry"
down_revision = "0007_postgres_outbox_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install evidence metadata, links, requirements, and RLS policies."""

    op.execute(POSTGRES_EVIDENCE_SCHEMA_SQL)


def downgrade() -> None:
    """Remove the evidence registry after an explicit operator decision."""

    op.execute("DROP TABLE IF EXISTS reconforge.evidence_links")
    op.execute("DROP TABLE IF EXISTS reconforge.evidence_requirements")
    op.execute("DROP TABLE IF EXISTS reconforge.evidence_registry")
