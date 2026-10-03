"""Require an independent actor to reopen a locked close period."""

from __future__ import annotations

from alembic import op

revision = "0091_pg_close_period_sod"
down_revision = "0090_pg_writeback_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE reconforge.close_periods
            ADD COLUMN IF NOT EXISTS locked_by TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS reopened_by TEXT NOT NULL DEFAULT '';

        UPDATE reconforge.close_periods
        SET locked_by = 'legacy-unknown'
        WHERE status IN ('Locked', 'Reopened') AND locked_by = '';

        UPDATE reconforge.close_periods
        SET reopened_by = 'legacy-unknown'
        WHERE status = 'Reopened' AND reopened_by = '';

        CREATE OR REPLACE FUNCTION reconforge.guard_close_period_sod() RETURNS trigger
        LANGUAGE plpgsql AS $reconforge$
        BEGIN
            IF OLD.status IN ('Open', 'Under Review', 'Approved', 'Reopened') AND NEW.status = 'Locked'
               AND (NEW.locked_by = '' OR NEW.locked_at IS NULL) THEN
                RAISE EXCEPTION 'locking a close period requires actor and timestamp evidence';
            END IF;
            IF OLD.status = 'Locked' AND NEW.status = 'Reopened'
               AND (OLD.locked_by = '' OR NEW.reopened_by = '' OR NEW.reopened_at IS NULL) THEN
                RAISE EXCEPTION 'reopening a close period requires actor evidence';
            END IF;
            IF OLD.status = 'Locked' AND NEW.status = 'Reopened'
               AND NEW.reopened_by = OLD.locked_by THEN
                RAISE EXCEPTION 'reopening a close period requires an independent actor';
            END IF;
            RETURN NEW;
        END;
        $reconforge$;

        DROP TRIGGER IF EXISTS close_period_sod_guard ON reconforge.close_periods;
        CREATE TRIGGER close_period_sod_guard
        BEFORE UPDATE ON reconforge.close_periods
        FOR EACH ROW EXECUTE FUNCTION reconforge.guard_close_period_sod();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM reconforge.close_periods
                WHERE status IN ('Locked', 'Reopened')
            ) THEN
                RAISE EXCEPTION
                    'refusing to downgrade close-period SoD while lock evidence is retained';
            END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS close_period_sod_guard ON reconforge.close_periods;
        DROP FUNCTION IF EXISTS reconforge.guard_close_period_sod();
        ALTER TABLE reconforge.close_periods
            DROP COLUMN IF EXISTS reopened_by,
            DROP COLUMN IF EXISTS locked_by;
        """
    )
