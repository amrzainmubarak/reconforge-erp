"""Add tenant-scoped durable-job aggregate persistence."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_DURABLE_JOB_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_jobs", "POSTGRES_DURABLE_JOB_SCHEMA_SQL"
)

revision = "0012_postgres_jobs"
down_revision = "0011_postgres_recon_ckpts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_DURABLE_JOB_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS durable_job_partition_effects_immutable ON reconforge.durable_job_partition_effects;
        DROP TRIGGER IF EXISTS durable_job_lease_events_immutable ON reconforge.durable_job_lease_events;
        DROP TRIGGER IF EXISTS durable_job_transitions_immutable ON reconforge.durable_job_transitions;
        DROP TABLE IF EXISTS reconforge.durable_job_partition_effects;
        DROP TABLE IF EXISTS reconforge.durable_job_lease_events;
        DROP TABLE IF EXISTS reconforge.durable_job_leases;
        DROP TABLE IF EXISTS reconforge.durable_job_transitions;
        DROP TABLE IF EXISTS reconforge.durable_jobs;
        DROP FUNCTION IF EXISTS reconforge.reject_durable_job_evidence_mutation();
        """
    )
