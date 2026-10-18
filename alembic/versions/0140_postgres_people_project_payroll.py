"""Private personnel role and source-owned time, budget, wage and cash closure."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_people_project_payroll_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0140_pg_people_project_payroll"
down_revision = "0139_pg_intercompany_fx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The schema validates a fixed NOLOGIN role without granting any membership.
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("people_project_payroll")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("people_project_payroll")))
