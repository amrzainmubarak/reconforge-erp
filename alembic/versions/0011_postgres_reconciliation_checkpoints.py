"""Add durable, idempotent reconciliation partition checkpoints."""

from alembic import op
from reconforge.infrastructure.postgres_reconciliation_checkpoints import (
    POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL,
)

revision = "0011_postgres_reconciliation_checkpoints"
down_revision = "0010_postgres_reconciliation_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install tenant-scoped checkpoint state for resumable partition work."""

    op.execute(POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL)


def downgrade() -> None:
    """Remove checkpoint state while preserving reconciliation output."""

    op.execute(
        """
        DROP TRIGGER IF EXISTS reconciliation_checkpoints_immutable
            ON reconforge.reconciliation_execution_checkpoints;
        DROP INDEX IF EXISTS reconforge.idx_reconciliation_checkpoints_run_status;
        DROP TABLE IF EXISTS reconforge.reconciliation_execution_checkpoints;
        """
    )
