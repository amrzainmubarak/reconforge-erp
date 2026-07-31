"""Contract-compatible PostgreSQL evidence-registry aggregate."""

from alembic import op
from reconforge.infrastructure.postgres_evidence_application import (
    POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL,
)

revision = "0031_postgres_evidence_app"
down_revision = "0030_postgres_close_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.evidence_application_links CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.evidence_application_requirements CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.evidence_application_registry CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.evidence_application_guard()")
