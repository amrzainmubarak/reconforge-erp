"""Make generic PostgreSQL close lock evidence immutable after locking."""

from __future__ import annotations

from alembic import op

revision = "0092_pg_close_lock_evidence"
down_revision = "0091_pg_close_period_sod"
branch_labels = None
depends_on = None


def _guard_function(*, immutable_lock_evidence: bool) -> str:
    immutable_guard = """
            IF OLD.status = 'Locked' AND NEW.status = 'Locked'
               AND (NEW.locked_by IS DISTINCT FROM OLD.locked_by
                    OR NEW.locked_at IS DISTINCT FROM OLD.locked_at) THEN
                RAISE EXCEPTION 'locked close-period evidence is immutable';
            END IF;
    """ if immutable_lock_evidence else ""
    return f"""
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
{immutable_guard}
            RETURN NEW;
        END;
        $reconforge$;
    """


def upgrade() -> None:
    op.execute(_guard_function(immutable_lock_evidence=True))


def downgrade() -> None:
    op.execute(_guard_function(immutable_lock_evidence=False))
