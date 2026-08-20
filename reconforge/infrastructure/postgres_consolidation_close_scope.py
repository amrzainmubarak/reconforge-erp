"""Hierarchy attribution and forced-RLS policies for PostgreSQL close records."""

from __future__ import annotations

from typing import Any

POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL = r"""
DO $reconforge$
DECLARE
    close_table_name TEXT;
    has_tenant_column BOOLEAN;
BEGIN
    FOREACH close_table_name IN ARRAY ARRAY[
        'consolidation_close_periods',
        'consolidation_close_runs',
        'consolidation_close_effects',
        'consolidation_close_period_events',
        'consolidation_close_run_lines',
        'consolidation_close_effect_lines',
        'consolidation_close_intercompany_links',
        'consolidation_close_impairment_links',
        'consolidation_close_deferred_tax_links',
        'consolidation_close_ppa_links',
        'consolidation_close_ownership_change_links'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'reconforge'
              AND table_name = close_table_name
        ) THEN
            CONTINUE;
        END IF;
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'reconforge'
              AND table_name = close_table_name
              AND column_name = 'tenant_id'
        ) INTO has_tenant_column;
        IF NOT has_tenant_column THEN
            RAISE EXCEPTION 'existing schema contract for % is missing tenant_id', close_table_name;
        END IF;
        EXECUTE format(
            'ALTER TABLE reconforge.%I ADD COLUMN IF NOT EXISTS organization_id TEXT DEFAULT NULLIF(current_setting(''app.organization_id'', true), '''')',
            close_table_name
        );
        EXECUTE format(
            'ALTER TABLE reconforge.%I ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting(''app.organization_id'', true), '''')',
            close_table_name
        );
        EXECUTE format(
            'ALTER TABLE reconforge.%I ADD COLUMN IF NOT EXISTS legal_entity_id TEXT DEFAULT NULLIF(current_setting(''app.legal_entity_id'', true), '''')',
            close_table_name
        );
        EXECUTE format(
            'ALTER TABLE reconforge.%I ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting(''app.legal_entity_id'', true), '''')',
            close_table_name
        );
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = close_table_name || '_organization_scope_fkey'
              AND conrelid = ('reconforge.' || close_table_name)::regclass
        ) THEN
            EXECUTE format(
                'ALTER TABLE reconforge.%I ADD CONSTRAINT %I FOREIGN KEY (tenant_id, organization_id) REFERENCES reconforge.organizations(tenant_id, id) ON DELETE RESTRICT',
                close_table_name,
                close_table_name || '_organization_scope_fkey'
            );
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = close_table_name || '_legal_entity_scope_fkey'
              AND conrelid = ('reconforge.' || close_table_name)::regclass
        ) THEN
            EXECUTE format(
                'ALTER TABLE reconforge.%I ADD CONSTRAINT %I FOREIGN KEY (tenant_id, legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id, id) ON DELETE RESTRICT',
                close_table_name,
                close_table_name || '_legal_entity_scope_fkey'
            );
        END IF;
        BEGIN
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS %I ON reconforge.%I(tenant_id, organization_id, legal_entity_id, created_at, id)',
                close_table_name || '_hierarchy_idx',
                close_table_name
            );
        EXCEPTION WHEN undefined_column THEN
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS %I ON reconforge.%I(tenant_id, organization_id, legal_entity_id, id)',
                close_table_name || '_hierarchy_idx',
                close_table_name
            );
        END;
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', close_table_name);
        EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I', close_table_name);
        EXECUTE format('DROP POLICY IF EXISTS hierarchy_scope ON reconforge.%I', close_table_name);
        IF close_table_name = ANY (ARRAY['consolidation_close_periods', 'consolidation_close_runs']) THEN
            EXECUTE format(
                'CREATE POLICY hierarchy_scope ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true) AND (NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL OR workspace_id=current_setting(''app.workspace_id'',true)) AND (NULLIF(current_setting(''app.organization_id'',true),'''') IS NULL OR organization_id=current_setting(''app.organization_id'',true)) AND (NULLIF(current_setting(''app.legal_entity_id'',true),'''') IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true))) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) AND (NULLIF(current_setting(''app.workspace_id'',true),'''') IS NULL OR workspace_id=current_setting(''app.workspace_id'',true)) AND (NULLIF(current_setting(''app.organization_id'',true),'''') IS NULL OR organization_id=current_setting(''app.organization_id'',true)) AND (NULLIF(current_setting(''app.legal_entity_id'',true),'''') IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true)))',
                close_table_name
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY hierarchy_scope ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true) AND (NULLIF(current_setting(''app.organization_id'',true),'''') IS NULL OR organization_id=current_setting(''app.organization_id'',true)) AND (NULLIF(current_setting(''app.legal_entity_id'',true),'''') IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true))) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) AND (NULLIF(current_setting(''app.organization_id'',true),'''') IS NULL OR organization_id=current_setting(''app.organization_id'',true)) AND (NULLIF(current_setting(''app.legal_entity_id'',true),'''') IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true)))',
                close_table_name
            );
        END IF;
    END LOOP;
END $reconforge$;

DO $reconforge$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_periods_tenant_id_workspace_id_group_code_period_name_key' AND conrelid='reconforge.consolidation_close_periods'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_periods DROP CONSTRAINT consolidation_close_periods_tenant_id_workspace_id_group_code_period_name_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_periods_hierarchy_unique' AND conrelid='reconforge.consolidation_close_periods'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_periods ADD CONSTRAINT consolidation_close_periods_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, workspace_id, group_code, period_name);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_runs_tenant_id_period_id_run_number_key' AND conrelid='reconforge.consolidation_close_runs'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_runs DROP CONSTRAINT consolidation_close_runs_tenant_id_period_id_run_number_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_runs_hierarchy_unique' AND conrelid='reconforge.consolidation_close_runs'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_runs ADD CONSTRAINT consolidation_close_runs_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, workspace_id, period_id, run_number);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_effects_tenant_id_run_id_effect_type_key' AND conrelid='reconforge.consolidation_close_effects'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_effects DROP CONSTRAINT consolidation_close_effects_tenant_id_run_id_effect_type_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_effects_hierarchy_unique' AND conrelid='reconforge.consolidation_close_effects'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_effects ADD CONSTRAINT consolidation_close_effects_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, effect_type);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_run_lines_tenant_id_run_id_ordinal_key' AND conrelid='reconforge.consolidation_close_run_lines'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_run_lines DROP CONSTRAINT consolidation_close_run_lines_tenant_id_run_id_ordinal_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_run_lines_hierarchy_unique' AND conrelid='reconforge.consolidation_close_run_lines'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_run_lines ADD CONSTRAINT consolidation_close_run_lines_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, ordinal);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_effect_lines_tenant_id_effect_id_ordinal_key' AND conrelid='reconforge.consolidation_close_effect_lines'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_effect_lines DROP CONSTRAINT consolidation_close_effect_lines_tenant_id_effect_id_ordinal_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_effect_lines_hierarchy_unique' AND conrelid='reconforge.consolidation_close_effect_lines'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_effect_lines ADD CONSTRAINT consolidation_close_effect_lines_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, effect_id, ordinal);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_intercompany_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_intercompany_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_intercompany_links DROP CONSTRAINT consolidation_close_intercompany_links_tenant_id_run_id_artifact_id_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_intercompany_links_hierarchy_unique' AND conrelid='reconforge.consolidation_close_intercompany_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_intercompany_links ADD CONSTRAINT consolidation_close_intercompany_links_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, artifact_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_impairment_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_impairment_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_impairment_links DROP CONSTRAINT consolidation_close_impairment_links_tenant_id_run_id_artifact_id_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_impairment_links_hierarchy_unique' AND conrelid='reconforge.consolidation_close_impairment_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_impairment_links ADD CONSTRAINT consolidation_close_impairment_links_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, artifact_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_impairment_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_impairment_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_impairment_links DROP CONSTRAINT consolidation_close_impairment_links_tenant_id_run_id_entity_code_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_impairment_links_hierarchy_entity_unique' AND conrelid='reconforge.consolidation_close_impairment_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_impairment_links ADD CONSTRAINT consolidation_close_impairment_links_hierarchy_entity_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, entity_code);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_deferred_tax_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_deferred_tax_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_deferred_tax_links DROP CONSTRAINT consolidation_close_deferred_tax_links_tenant_id_run_id_artifact_id_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_deferred_tax_links_hierarchy_unique' AND conrelid='reconforge.consolidation_close_deferred_tax_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_deferred_tax_links ADD CONSTRAINT consolidation_close_deferred_tax_links_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, artifact_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_deferred_tax_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_deferred_tax_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_deferred_tax_links DROP CONSTRAINT consolidation_close_deferred_tax_links_tenant_id_run_id_entity_code_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_deferred_tax_links_hierarchy_entity_unique' AND conrelid='reconforge.consolidation_close_deferred_tax_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_deferred_tax_links ADD CONSTRAINT consolidation_close_deferred_tax_links_hierarchy_entity_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, entity_code);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ppa_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_ppa_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ppa_links DROP CONSTRAINT consolidation_close_ppa_links_tenant_id_run_id_artifact_id_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ppa_links_hierarchy_unique' AND conrelid='reconforge.consolidation_close_ppa_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ppa_links ADD CONSTRAINT consolidation_close_ppa_links_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, artifact_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ppa_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_ppa_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ppa_links DROP CONSTRAINT consolidation_close_ppa_links_tenant_id_run_id_entity_code_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ppa_links_hierarchy_entity_unique' AND conrelid='reconforge.consolidation_close_ppa_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ppa_links ADD CONSTRAINT consolidation_close_ppa_links_hierarchy_entity_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, entity_code);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ownership_change_links_tenant_id_run_id_artifact_id_key' AND conrelid='reconforge.consolidation_close_ownership_change_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ownership_change_links DROP CONSTRAINT consolidation_close_ownership_change_links_tenant_id_run_id_artifact_id_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ownership_change_links_hierarchy_unique' AND conrelid='reconforge.consolidation_close_ownership_change_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ownership_change_links ADD CONSTRAINT consolidation_close_ownership_change_links_hierarchy_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, artifact_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ownership_change_links_tenant_id_run_id_entity_code_key' AND conrelid='reconforge.consolidation_close_ownership_change_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ownership_change_links DROP CONSTRAINT consolidation_close_ownership_change_links_tenant_id_run_id_entity_code_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_close_ownership_change_links_hierarchy_entity_unique' AND conrelid='reconforge.consolidation_close_ownership_change_links'::regclass) THEN
        ALTER TABLE reconforge.consolidation_close_ownership_change_links ADD CONSTRAINT consolidation_close_ownership_change_links_hierarchy_entity_unique UNIQUE NULLS NOT DISTINCT (tenant_id, organization_id, legal_entity_id, run_id, entity_code);
    END IF;
END $reconforge$;
"""


def install_postgres_consolidation_close_scope_schema(connection: Any) -> None:
    """Install hierarchy attribution and RLS for all close records."""

    connection.execute(POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL)


__all__ = [
    "POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL",
    "install_postgres_consolidation_close_scope_schema",
]
