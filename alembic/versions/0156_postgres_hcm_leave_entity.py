"""Bind leave authority to the canonical employee organization and legal entity."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_hcm_leave_scope_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0156_pg_hcm_leave_entity"
down_revision = "0155_pg_crm_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
