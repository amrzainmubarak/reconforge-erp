"""Bind canonical CRM creator identity without inferring historical authors."""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_crm_authority_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0155_pg_crm_authority"
down_revision = "0154_pg_enterprise_finance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
