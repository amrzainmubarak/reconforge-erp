"""Source-owned voucher schedules over native periods, accounts and GL."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_accrual_deferral_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_accrual_deferral_source_ownership import (
    DOWNGRADE_SQL as DIRECTORY_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_accrual_deferral_source_ownership import (
    UPGRADE_SQL as DIRECTORY_UPGRADE_SQL,
)
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0141_pg_accrual_deferral"
down_revision = "0140_pg_people_project_payroll"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(DIRECTORY_UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("accrual_deferral")))


def downgrade() -> None:
    op.execute(sa.text(DIRECTORY_DOWNGRADE_SQL))
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("accrual_deferral")))
