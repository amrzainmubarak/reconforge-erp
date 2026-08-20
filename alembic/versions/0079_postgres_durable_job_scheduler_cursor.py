"""Add tenant-scoped durable-job scheduler cursor coordination."""

from __future__ import annotations

from alembic import op

revision = "0079_pg_job_cursor"
down_revision = "0078_pg_close_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reconforge.durable_job_scheduler_cursors (
            tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
            scheduler_key TEXT NOT NULL,
            lane_digest TEXT NOT NULL CHECK (lane_digest ~ '^[0-9a-f]{64}$'),
            lane_count INTEGER NOT NULL CHECK (lane_count > 0),
            next_index INTEGER NOT NULL CHECK (next_index >= 0 AND next_index < lane_count),
            version BIGINT NOT NULL CHECK (version > 0),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, scheduler_key)
        );
        CREATE INDEX IF NOT EXISTS durable_job_scheduler_cursors_updated_idx
            ON reconforge.durable_job_scheduler_cursors(tenant_id, updated_at, scheduler_key);
        ALTER TABLE reconforge.durable_job_scheduler_cursors ENABLE ROW LEVEL SECURITY;
        ALTER TABLE reconforge.durable_job_scheduler_cursors FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_scope ON reconforge.durable_job_scheduler_cursors;
        CREATE POLICY tenant_scope ON reconforge.durable_job_scheduler_cursors
            USING (tenant_id=current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id=current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM reconforge.durable_job_scheduler_cursors
            ) THEN
                RAISE EXCEPTION '0079 downgrade refuses non-empty scheduler cursor state';
            END IF;
        END $reconforge$;
        DROP TABLE IF EXISTS reconforge.durable_job_scheduler_cursors;
        """
    )
