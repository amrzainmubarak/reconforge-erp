"""Persist PostgreSQL consolidation journal and effect lines."""

from alembic import op

revision = "0057_pg_consol_journal_lines"
down_revision = "0056_pg_policy_delegations"
branch_labels = None
depends_on = None


_UPGRADE_SQL = """
ALTER TABLE reconforge.consolidation_close_runs
    ADD COLUMN IF NOT EXISTS journal_line_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reconforge.consolidation_close_effects
    ADD COLUMN IF NOT EXISTS source_effect_id TEXT NOT NULL DEFAULT '';
ALTER TABLE reconforge.consolidation_close_effects
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'Legacy';
ALTER TABLE reconforge.consolidation_close_effects
    ADD COLUMN IF NOT EXISTS line_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_run_lines (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    elimination_id TEXT NOT NULL,
    source_line_id TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    group_account_code TEXT NOT NULL,
    account_type TEXT NOT NULL,
    amount_decimal NUMERIC(38,18) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency_code TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, run_id, ordinal),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES reconforge.consolidation_close_runs(tenant_id, id) ON DELETE CASCADE,
    CHECK (ordinal >= 1),
    CHECK (amount_minor <> 0),
    CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_effect_lines (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    effect_id TEXT NOT NULL,
    run_line_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    amount_decimal NUMERIC(38,18) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency_code TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, effect_id, ordinal),
    FOREIGN KEY (tenant_id, effect_id)
        REFERENCES reconforge.consolidation_close_effects(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, run_line_id)
        REFERENCES reconforge.consolidation_close_run_lines(tenant_id, id) ON DELETE RESTRICT,
    CHECK (ordinal >= 1),
    CHECK (amount_minor <> 0),
    CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE INDEX IF NOT EXISTS consolidation_close_run_lines_run_idx
    ON reconforge.consolidation_close_run_lines(tenant_id, run_id, ordinal);
CREATE INDEX IF NOT EXISTS consolidation_close_effect_lines_effect_idx
    ON reconforge.consolidation_close_effect_lines(tenant_id, effect_id, ordinal);

ALTER TABLE reconforge.consolidation_close_run_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_run_lines FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effect_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effect_lines FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'consolidation_close_run_lines',
        'consolidation_close_effect_lines'
    ] LOOP
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON reconforge.%I '
            'USING (tenant_id=current_setting(''app.tenant_id'',true)) '
            'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',
            table_name
        );
    END LOOP;
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_consolidation_close_child_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    RAISE EXCEPTION 'consolidation close child rows are append-only';
END;
$reconforge$;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'consolidation_close_effects',
        'consolidation_close_run_lines',
        'consolidation_close_effect_lines'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I_immutable ON reconforge.%I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE '
            'ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION '
            'reconforge.reject_consolidation_close_child_mutation()',
            table_name,
            table_name
        );
    END LOOP;
END
$reconforge$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS consolidation_close_effects_immutable
            ON reconforge.consolidation_close_effects;
        DROP TRIGGER IF EXISTS consolidation_close_run_lines_immutable
            ON reconforge.consolidation_close_run_lines;
        DROP TRIGGER IF EXISTS consolidation_close_effect_lines_immutable
            ON reconforge.consolidation_close_effect_lines;
        DROP FUNCTION IF EXISTS reconforge.reject_consolidation_close_child_mutation();
        DROP TABLE IF EXISTS reconforge.consolidation_close_effect_lines CASCADE;
        DROP TABLE IF EXISTS reconforge.consolidation_close_run_lines CASCADE;
        ALTER TABLE reconforge.consolidation_close_effects
            DROP COLUMN IF EXISTS source_effect_id,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS line_count;
        ALTER TABLE reconforge.consolidation_close_runs
            DROP COLUMN IF EXISTS journal_line_count;
        """
    )
