"""Add governed integration administration and evidence-retention policy."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_security_governance",
    "POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL",
)

revision = "0052_security_governance"
down_revision = "0051_access_policy_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.retention_policies LIMIT 1)
             OR EXISTS (SELECT 1 FROM reconforge.evidence_retention_assignments LIMIT 1)
             OR EXISTS (SELECT 1 FROM reconforge.evidence_registry WHERE retention_version<>1 LIMIT 1)
          THEN
            RAISE EXCEPTION
              'refusing to discard governed retention policy or lifecycle evidence; back up and migrate it first';
          END IF;
        END $reconforge$;

        DROP TRIGGER IF EXISTS evidence_retention_assignments_append_only
          ON reconforge.evidence_retention_assignments;
        DROP TRIGGER IF EXISTS retention_policy_update_guard ON reconforge.retention_policies;
        DROP TABLE IF EXISTS reconforge.evidence_retention_assignments;
        DROP TABLE IF EXISTS reconforge.retention_policies;
        DROP FUNCTION IF EXISTS reconforge.reject_retention_assignment_mutation();
        DROP FUNCTION IF EXISTS reconforge.guard_retention_policy_update();
        DROP TRIGGER IF EXISTS evidence_retention_floor_guard ON reconforge.evidence_registry;
        DROP FUNCTION IF EXISTS reconforge.guard_evidence_retention_floor();
        ALTER TABLE reconforge.evidence_registry
          DROP CONSTRAINT IF EXISTS evidence_registry_retention_version_positive,
          DROP COLUMN IF EXISTS retention_version;
        """
    )
