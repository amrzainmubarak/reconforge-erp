"""Add immutable recipient-scoped notification evidence after the retained receipt schema."""

from alembic import op
from reconforge.infrastructure.notification_inbox_schema import POSTGRES_NOTIFICATION_INBOX_SQL

revision = "0101_pg_notification_inbox"
down_revision = "0100_pg_inventory_receipt"
branch_labels = None
depends_on = None


DOWNGRADE_SQL = r"""
DO $inbox$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.notification_inbox)
 OR EXISTS(SELECT 1 FROM reconforge.notification_inbox_reads) THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Notification evidence history prevents downgrade; restore a verified pre-upgrade backup.';
 END IF;
END $inbox$;
DROP TABLE reconforge.notification_inbox_reads;
DROP TABLE reconforge.notification_inbox;
DROP FUNCTION reconforge.guard_notification_inbox_admission();
DROP FUNCTION reconforge.guard_notification_inbox();
DROP FUNCTION reconforge.inbox_can_act(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT);
"""


def upgrade() -> None:
    op.execute(POSTGRES_NOTIFICATION_INBOX_SQL)


def downgrade() -> None:
    # Permission records intentionally remain additive. A pre-existing operator
    # grant cannot be distinguished from a migration-created one without
    # deleting authorization history during a rollback.
    op.execute(DOWNGRADE_SQL)
