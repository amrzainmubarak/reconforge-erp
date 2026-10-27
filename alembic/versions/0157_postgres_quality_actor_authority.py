"""Bind NCR creation and independent disposition to canonical user authority."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.quality_actor_authority_schema import (
    POSTGRES_DOWNGRADE_SQL,
    POSTGRES_UPGRADE_SQL,
)

revision = "0157_pg_quality_actor_authority"
down_revision = "0156_pg_hcm_leave_entity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(POSTGRES_UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(POSTGRES_DOWNGRADE_SQL))
