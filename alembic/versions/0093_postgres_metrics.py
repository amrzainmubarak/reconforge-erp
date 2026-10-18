"""Install the dashboard metrics omitted from the PostgreSQL migration chain.

SQL and standard definitions are frozen here so replay never imports a later
application schema. Definitions are shared product metadata; snapshots are
tenant data protected by forced RLS. Downgrade refuses retained user data.
"""

from __future__ import annotations

from alembic import op

revision = "0093_pg_metrics"
down_revision = "0092_pg_close_lock_evidence"
branch_labels = None
depends_on = None

_DEFINITIONS = """
 ('close_completion', 'Close Completion', 'Percentage of completed close tasks', 'reconforge.domain.close.Task'),
 ('unresolved_high_risk_exceptions', 'Unresolved High Risk', 'Count of high or critical open exceptions',
  'reconforge.domain.exceptions.Exception'),
 ('review_aging', 'Review Aging', 'Average days in review state', 'reconforge.domain.exceptions.Exception'),
 ('evidence_coverage', 'Evidence Coverage', 'Percentage of evidence requirements met', 'reconforge.domain.evidence.Requirement'),
 ('control_effectiveness', 'Control Effectiveness', 'Percentage of effective control test results', 'reconforge.domain.control.Result'),
 ('match_rate', 'Match Rate', 'Percentage of matched records', 'reconforge.domain.reconciliation.Result'),
 ('exception_aging', 'Exception Aging', 'Average days open for exceptions', 'reconforge.domain.exceptions.Exception'),
 ('period_readiness', 'Period Readiness', 'Computed period readiness score', 'reconforge.domain.close.Period')
"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS reconforge.metric_definitions (
            metric_key TEXT NOT NULL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            lineage TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reconforge.metric_snapshots (
            id TEXT NOT NULL,
            tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL,
            metric_key TEXT NOT NULL REFERENCES reconforge.metric_definitions(metric_key),
            period_name TEXT NOT NULL,
            value NUMERIC NOT NULL,
            value_text TEXT NOT NULL,
            lineage TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, id),
            UNIQUE (tenant_id, workspace_id, metric_key, period_name)
        );
        ALTER TABLE reconforge.metric_snapshots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE reconforge.metric_snapshots FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_scope ON reconforge.metric_snapshots;
        CREATE POLICY tenant_scope ON reconforge.metric_snapshots
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    """)
    op.execute(
        "INSERT INTO reconforge.metric_definitions (metric_key, name, description, lineage) VALUES "
        + _DEFINITIONS + " ON CONFLICT (metric_key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("""
        SET LOCAL row_security = off;
        LOCK TABLE reconforge.metric_snapshots, reconforge.metric_definitions IN ACCESS EXCLUSIVE MODE;
        DO $reconforge$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.metric_snapshots) THEN
                RAISE EXCEPTION 'metrics downgrade refused: snapshots are retained; restore a pre-upgrade backup';
            END IF;
            IF EXISTS (
                SELECT metric_key, name, description, lineage FROM reconforge.metric_definitions
                EXCEPT VALUES
    """ + _DEFINITIONS + """
            ) THEN
                RAISE EXCEPTION 'metrics downgrade refused: custom definitions are retained; restore a pre-upgrade backup';
            END IF;
        END;
        $reconforge$;
        DROP TABLE reconforge.metric_snapshots;
        DROP TABLE reconforge.metric_definitions;
    """)
