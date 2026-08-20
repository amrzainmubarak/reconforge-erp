"""PostgreSQL reconciliation run legal-entity attribution and RLS policy."""

from __future__ import annotations

from typing import Any

POSTGRES_RECONCILIATION_ENTITY_SCOPE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.reconciliation_runs
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');

ALTER TABLE reconforge.reconciliation_runs
    ALTER COLUMN organization_id
    SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');

ALTER TABLE reconforge.reconciliation_runs
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

ALTER TABLE reconforge.reconciliation_runs
    ALTER COLUMN legal_entity_id
    SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reconciliation_runs_tenant_legal_entity_fkey'
          AND conrelid = 'reconforge.reconciliation_runs'::regclass
    ) THEN
        ALTER TABLE reconforge.reconciliation_runs
            ADD CONSTRAINT reconciliation_runs_tenant_legal_entity_fkey
            FOREIGN KEY (tenant_id, legal_entity_id)
            REFERENCES reconforge.legal_entities (tenant_id, id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reconciliation_runs_tenant_organization_fkey'
          AND conrelid = 'reconforge.reconciliation_runs'::regclass
    ) THEN
        ALTER TABLE reconforge.reconciliation_runs
            ADD CONSTRAINT reconciliation_runs_tenant_organization_fkey
            FOREIGN KEY (tenant_id, organization_id)
            REFERENCES reconforge.organizations (tenant_id, id)
            ON DELETE RESTRICT;
    END IF;
END $reconforge$;

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_tenant_entity
    ON reconforge.reconciliation_runs (tenant_id, organization_id, legal_entity_id, created_at DESC, id);

DROP POLICY IF EXISTS tenant_scope ON reconforge.reconciliation_runs;
CREATE POLICY tenant_scope ON reconforge.reconciliation_runs
    USING (
        tenant_id = current_setting('app.tenant_id', true)
        AND (
            NULLIF(current_setting('app.workspace_id', true), '') IS NULL
            OR workspace_id = current_setting('app.workspace_id', true)
        )
        AND (
            NULLIF(current_setting('app.organization_id', true), '') IS NULL
            OR organization_id = current_setting('app.organization_id', true)
        )
        AND (
            NULLIF(current_setting('app.legal_entity_id', true), '') IS NULL
            OR legal_entity_id = current_setting('app.legal_entity_id', true)
        )
    )
    WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)
        AND (
            NULLIF(current_setting('app.workspace_id', true), '') IS NULL
            OR workspace_id = current_setting('app.workspace_id', true)
        )
        AND (
            NULLIF(current_setting('app.organization_id', true), '') IS NULL
            OR organization_id = current_setting('app.organization_id', true)
        )
        AND (
            NULLIF(current_setting('app.legal_entity_id', true), '') IS NULL
            OR legal_entity_id = current_setting('app.legal_entity_id', true)
        )
    );
"""


def install_postgres_reconciliation_entity_scope_schema(connection: Any) -> None:
    """Install legal-entity attribution for reconciliation runs."""

    connection.execute(POSTGRES_RECONCILIATION_ENTITY_SCOPE_SCHEMA_SQL)
