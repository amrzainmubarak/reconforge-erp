"""Add governed budget envelopes and retained commitment evidence."""

from alembic import op

from reconforge.infrastructure.postgres_budget_control_schema import POSTGRES_BUDGET_CONTROL_SCHEMA_SQL


revision = "0102_pg_budget_control"
down_revision = "0101_pg_notification_inbox"
branch_labels = None
depends_on = None


DOWNGRADE_SQL = r"""
DO $budget$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.budget_envelopes)
 OR EXISTS(SELECT 1 FROM reconforge.budget_commitment_events)
 OR EXISTS(SELECT 1 FROM reconforge.budget_commands) THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Budget evidence history prevents downgrade; restore a verified pre-upgrade backup.';
 END IF;
END $budget$;
DROP TABLE reconforge.budget_commands;
DROP TABLE reconforge.budget_commitment_events;
DROP TABLE reconforge.budget_envelopes;
DROP FUNCTION reconforge.budget_command_guard();
DROP FUNCTION reconforge.budget_event_apply();
DROP FUNCTION reconforge.budget_event_guard();
DROP FUNCTION reconforge.budget_envelope_guard();
"""


def upgrade() -> None:
    op.execute(POSTGRES_BUDGET_CONTROL_SCHEMA_SQL)


def downgrade() -> None:
    # Retained budget, command, audit, and outbox references are never discarded
    # to make an incompatible reader appear safe.
    op.execute(DOWNGRADE_SQL)
