"""Release unposted native collections without discarding source evidence."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_commercial_collections_cancellation_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0124_pg_collection_cancellation"
down_revision = "0123_pg_native_event_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
