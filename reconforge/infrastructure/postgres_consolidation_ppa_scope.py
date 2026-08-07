"""Hierarchy attribution and RLS policy for PostgreSQL PPA evidence."""

from __future__ import annotations

from typing import Any

POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.consolidation_ppa_artifacts
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.consolidation_ppa_artifacts
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.consolidation_ppa_artifacts
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.consolidation_ppa_artifacts
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'consolidation_ppa_tenant_organization_fkey'
          AND conrelid = 'reconforge.consolidation_ppa_artifacts'::regclass
    ) THEN
        ALTER TABLE reconforge.consolidation_ppa_artifacts
            ADD CONSTRAINT consolidation_ppa_tenant_organization_fkey
            FOREIGN KEY (tenant_id, organization_id)
            REFERENCES reconforge.organizations (tenant_id, id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'consolidation_ppa_tenant_legal_entity_fkey'
          AND conrelid = 'reconforge.consolidation_ppa_artifacts'::regclass
    ) THEN
        ALTER TABLE reconforge.consolidation_ppa_artifacts
            ADD CONSTRAINT consolidation_ppa_tenant_legal_entity_fkey
            FOREIGN KEY (tenant_id, legal_entity_id)
            REFERENCES reconforge.legal_entities (tenant_id, id)
            ON DELETE RESTRICT;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'consolidation_ppa_artifacts_tenant_id_result_digest_key'
          AND conrelid = 'reconforge.consolidation_ppa_artifacts'::regclass
    ) THEN
        ALTER TABLE reconforge.consolidation_ppa_artifacts
            DROP CONSTRAINT consolidation_ppa_artifacts_tenant_id_result_digest_key;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'consolidation_ppa_scope_result_digest_key'
          AND conrelid = 'reconforge.consolidation_ppa_artifacts'::regclass
    ) THEN
        ALTER TABLE reconforge.consolidation_ppa_artifacts
            ADD CONSTRAINT consolidation_ppa_scope_result_digest_key
            UNIQUE (tenant_id, organization_id, legal_entity_id, result_digest);
    END IF;
END $reconforge$;

CREATE INDEX IF NOT EXISTS consolidation_ppa_hierarchy_scope_idx
    ON reconforge.consolidation_ppa_artifacts
        (tenant_id, organization_id, legal_entity_id, period_id, created_at, id);

DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_ppa_artifacts;
CREATE POLICY tenant_scope ON reconforge.consolidation_ppa_artifacts
    USING (
        tenant_id = current_setting('app.tenant_id', true)
        AND (NULLIF(current_setting('app.organization_id', true), '') IS NULL
             OR organization_id = current_setting('app.organization_id', true))
        AND (NULLIF(current_setting('app.legal_entity_id', true), '') IS NULL
             OR legal_entity_id = current_setting('app.legal_entity_id', true))
    )
    WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)
        AND (NULLIF(current_setting('app.organization_id', true), '') IS NULL
             OR organization_id = current_setting('app.organization_id', true))
        AND (NULLIF(current_setting('app.legal_entity_id', true), '') IS NULL
             OR legal_entity_id = current_setting('app.legal_entity_id', true))
    );
"""


def install_postgres_consolidation_ppa_scope_schema(connection: Any) -> None:
    """Install hierarchy attribution for PPA evidence."""

    connection.execute(POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL)


__all__ = [
    "POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL",
    "install_postgres_consolidation_ppa_scope_schema",
]
