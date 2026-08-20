"""Align PostgreSQL consolidation-close period reopen state with the API contract."""

from __future__ import annotations

from alembic import op

revision = "0086_pg_close_reopened"
down_revision = "0085_pg_reversal_definer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT pg_constraint.conname
                FROM pg_constraint
                WHERE pg_constraint.conrelid = 'reconforge.consolidation_close_periods'::regclass
                  AND pg_constraint.contype = 'c'
                  AND pg_get_constraintdef(pg_constraint.oid) LIKE '%status%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE reconforge.consolidation_close_periods DROP CONSTRAINT %I',
                    constraint_name
                );
            END LOOP;
        END $reconforge$;
        ALTER TABLE reconforge.consolidation_close_periods
            ADD CONSTRAINT consolidation_close_periods_status_check
            CHECK (status IN ('Open','Locked','Reopened'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM reconforge.consolidation_close_periods
                WHERE status = 'Reopened'
            ) THEN
                RAISE EXCEPTION
                    'refusing to downgrade consolidation-close periods while Reopened rows exist';
            END IF;
        END $reconforge$;
        ALTER TABLE reconforge.consolidation_close_periods
            DROP CONSTRAINT IF EXISTS consolidation_close_periods_status_check;
        ALTER TABLE reconforge.consolidation_close_periods
            ADD CONSTRAINT consolidation_close_periods_status_check
            CHECK (status IN ('Open','Locked'));
        """
    )
