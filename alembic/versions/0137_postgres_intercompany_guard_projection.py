"""Project typed deferred guard fields without changing native source closure.

Same function/signature; CREATE OR REPLACE preserves its OID, privileges and
existing deferred trigger attachments. Rollback restores the exact published
0134 function without deleting retained paired journals, evidence or history.
Native upgrade/rollback/catalog and adversarial gates remain required before
this isolated performance candidate can be accepted.
"""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_intercompany_guard_projection import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0137_pg_intercompany_projection"
down_revision = "0136_pg_inventory_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
