"""Hierarchy attribution and RLS policies for impairment/deferred-tax evidence."""

from __future__ import annotations

from typing import Any

POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.consolidation_impairment_artifacts
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.consolidation_impairment_artifacts
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.consolidation_impairment_artifacts
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.consolidation_impairment_artifacts
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

ALTER TABLE reconforge.consolidation_deferred_tax_artifacts
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.consolidation_deferred_tax_artifacts
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.consolidation_deferred_tax_artifacts
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.consolidation_deferred_tax_artifacts
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

DO $reconforge$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_impairment_tenant_organization_fkey' AND conrelid='reconforge.consolidation_impairment_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_impairment_artifacts ADD CONSTRAINT consolidation_impairment_tenant_organization_fkey FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_impairment_tenant_legal_entity_fkey' AND conrelid='reconforge.consolidation_impairment_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_impairment_artifacts ADD CONSTRAINT consolidation_impairment_tenant_legal_entity_fkey FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_deferred_tax_tenant_organization_fkey' AND conrelid='reconforge.consolidation_deferred_tax_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_deferred_tax_artifacts ADD CONSTRAINT consolidation_deferred_tax_tenant_organization_fkey FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_deferred_tax_tenant_legal_entity_fkey' AND conrelid='reconforge.consolidation_deferred_tax_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_deferred_tax_artifacts ADD CONSTRAINT consolidation_deferred_tax_tenant_legal_entity_fkey FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_impairment_artifacts_tenant_id_result_digest_key' AND conrelid='reconforge.consolidation_impairment_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_impairment_artifacts DROP CONSTRAINT consolidation_impairment_artifacts_tenant_id_result_digest_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_impairment_scope_result_digest_key' AND conrelid='reconforge.consolidation_impairment_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_impairment_artifacts ADD CONSTRAINT consolidation_impairment_scope_result_digest_key UNIQUE (tenant_id,organization_id,legal_entity_id,result_digest);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_deferred_tax_artifacts_tenant_id_result_digest_key' AND conrelid='reconforge.consolidation_deferred_tax_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_deferred_tax_artifacts DROP CONSTRAINT consolidation_deferred_tax_artifacts_tenant_id_result_digest_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='consolidation_deferred_tax_scope_result_digest_key' AND conrelid='reconforge.consolidation_deferred_tax_artifacts'::regclass) THEN
        ALTER TABLE reconforge.consolidation_deferred_tax_artifacts ADD CONSTRAINT consolidation_deferred_tax_scope_result_digest_key UNIQUE (tenant_id,organization_id,legal_entity_id,result_digest);
    END IF;
END $reconforge$;

CREATE INDEX IF NOT EXISTS consolidation_impairment_hierarchy_scope_idx ON reconforge.consolidation_impairment_artifacts(tenant_id,organization_id,legal_entity_id,period_id,created_at,id);
CREATE INDEX IF NOT EXISTS consolidation_deferred_tax_hierarchy_scope_idx ON reconforge.consolidation_deferred_tax_artifacts(tenant_id,organization_id,legal_entity_id,period_id,created_at,id);

DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_impairment_artifacts;
CREATE POLICY tenant_scope ON reconforge.consolidation_impairment_artifacts USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
    AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true))
) WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
    AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true))
);
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_deferred_tax_artifacts;
CREATE POLICY tenant_scope ON reconforge.consolidation_deferred_tax_artifacts USING (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
    AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true))
) WITH CHECK (
    tenant_id=current_setting('app.tenant_id',true)
    AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
    AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true))
);
"""


def install_postgres_consolidation_impairment_deferred_tax_scope_schema(connection: Any) -> None:
    """Install hierarchy attribution for impairment and deferred-tax evidence."""

    connection.execute(POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL)


__all__ = [
    "POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL",
    "install_postgres_consolidation_impairment_deferred_tax_scope_schema",
]
