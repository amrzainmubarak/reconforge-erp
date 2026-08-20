"""Add hierarchy attribution to PostgreSQL consolidation-close records."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_consolidation_close_scope",
    "POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL",
)

revision = "0078_pg_close_scope"
down_revision = "0077_pg_imp_tax_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        DECLARE table_name TEXT;
                has_attribution BOOLEAN;
        BEGIN
            -- Never silently discard hierarchy attribution.  A rollback is
            -- only safe while all rows still carry the legacy NULL scope.
            FOREACH table_name IN ARRAY ARRAY[
                'consolidation_close_periods','consolidation_close_runs',
                'consolidation_close_effects','consolidation_close_period_events',
                'consolidation_close_run_lines','consolidation_close_effect_lines',
                'consolidation_close_intercompany_links','consolidation_close_impairment_links',
                'consolidation_close_deferred_tax_links','consolidation_close_ppa_links',
                'consolidation_close_ownership_change_links'
            ] LOOP
                EXECUTE format(
                    'SELECT EXISTS (SELECT 1 FROM reconforge.%I WHERE organization_id IS NOT NULL OR legal_entity_id IS NOT NULL)',
                    table_name
                ) INTO has_attribution;
                IF has_attribution THEN
                    RAISE EXCEPTION 'refusing to discard close hierarchy attribution from %', table_name;
                END IF;
            END LOOP;

            FOREACH table_name IN ARRAY ARRAY[
                'consolidation_close_periods','consolidation_close_runs',
                'consolidation_close_effects','consolidation_close_period_events',
                'consolidation_close_run_lines','consolidation_close_effect_lines',
                'consolidation_close_intercompany_links','consolidation_close_impairment_links',
                'consolidation_close_deferred_tax_links','consolidation_close_ppa_links',
                'consolidation_close_ownership_change_links'
            ] LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = table_name || '_hierarchy_unique'
                      AND conrelid = ('reconforge.' || table_name)::regclass
                ) THEN
                    EXECUTE format('ALTER TABLE reconforge.%I DROP CONSTRAINT %I', table_name, table_name || '_hierarchy_unique');
                END IF;
                EXECUTE format('DROP POLICY IF EXISTS hierarchy_scope ON reconforge.%I', table_name);
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', table_name);
                EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', table_name);
                IF table_name = ANY (ARRAY[
                    'consolidation_close_periods','consolidation_close_runs',
                    'consolidation_close_effects','consolidation_close_period_events',
                    'consolidation_close_run_lines','consolidation_close_effect_lines'
                ]) THEN
                    EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))', table_name);
                ELSE
                    EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))', table_name);
                END IF;
                EXECUTE format('ALTER TABLE reconforge.%I DROP CONSTRAINT IF EXISTS %I', table_name, table_name || '_legal_entity_scope_fkey');
                EXECUTE format('ALTER TABLE reconforge.%I DROP CONSTRAINT IF EXISTS %I', table_name, table_name || '_organization_scope_fkey');
                EXECUTE format('ALTER TABLE reconforge.%I DROP COLUMN IF EXISTS legal_entity_id', table_name);
                EXECUTE format('ALTER TABLE reconforge.%I DROP COLUMN IF EXISTS organization_id', table_name);
            END LOOP;
        END $reconforge$;

        DO $reconforge$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_periods_tenant_id_workspace_id_group_code_period_name_key' AND conrelid='reconforge.consolidation_close_periods'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_periods ADD CONSTRAINT consolidation_close_periods_tenant_id_workspace_id_group_code_period_name_key UNIQUE (tenant_id,workspace_id,group_code,period_name);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_runs_tenant_id_period_id_run_number_key' AND conrelid='reconforge.consolidation_close_runs'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_runs ADD CONSTRAINT consolidation_close_runs_tenant_id_period_id_run_number_key UNIQUE (tenant_id,period_id,run_number);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_effects_tenant_id_run_id_effect_type_key' AND conrelid='reconforge.consolidation_close_effects'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_effects ADD CONSTRAINT consolidation_close_effects_tenant_id_run_id_effect_type_key UNIQUE (tenant_id,run_id,effect_type);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_run_lines_tenant_id_run_id_ordinal_key' AND conrelid='reconforge.consolidation_close_run_lines'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_run_lines ADD CONSTRAINT consolidation_close_run_lines_tenant_id_run_id_ordinal_key UNIQUE (tenant_id,run_id,ordinal);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_effect_lines_tenant_id_effect_id_ordinal_key' AND conrelid='reconforge.consolidation_close_effect_lines'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_effect_lines ADD CONSTRAINT consolidation_close_effect_lines_tenant_id_effect_id_ordinal_key UNIQUE (tenant_id,effect_id,ordinal);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_intercompany_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_intercompany_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_intercompany_links ADD CONSTRAINT consolidation_close_intercompany_links_tenant_id_run_id_artifact_id_key UNIQUE (tenant_id,run_id,artifact_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_impairment_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_impairment_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_impairment_links ADD CONSTRAINT consolidation_close_impairment_links_tenant_id_run_id_artifact_id_key UNIQUE (tenant_id,run_id,artifact_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_impairment_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_impairment_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_impairment_links ADD CONSTRAINT consolidation_close_impairment_links_tenant_id_run_id_entity_code_key UNIQUE (tenant_id,run_id,entity_code);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_deferred_tax_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_deferred_tax_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_deferred_tax_links ADD CONSTRAINT consolidation_close_deferred_tax_links_tenant_id_run_id_artifact_id_key UNIQUE (tenant_id,run_id,artifact_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_deferred_tax_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_deferred_tax_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_deferred_tax_links ADD CONSTRAINT consolidation_close_deferred_tax_links_tenant_id_run_id_entity_code_key UNIQUE (tenant_id,run_id,entity_code);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ppa_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_ppa_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_ppa_links ADD CONSTRAINT consolidation_close_ppa_links_tenant_id_run_id_artifact_id_key UNIQUE (tenant_id,run_id,artifact_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ppa_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_ppa_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_ppa_links ADD CONSTRAINT consolidation_close_ppa_links_tenant_id_run_id_entity_code_key UNIQUE (tenant_id,run_id,entity_code);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ownership_change_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_ownership_change_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_ownership_change_links ADD CONSTRAINT consolidation_close_ownership_change_links_tenant_id_run_id_artifact_id_key UNIQUE (tenant_id,run_id,artifact_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ownership_change_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_ownership_change_links'::regclass) THEN
                ALTER TABLE reconforge.consolidation_close_ownership_change_links ADD CONSTRAINT consolidation_close_ownership_change_links_tenant_id_run_id_entity_code_key UNIQUE (tenant_id,run_id,entity_code);
            END IF;
        END $reconforge$;
        """
    )
