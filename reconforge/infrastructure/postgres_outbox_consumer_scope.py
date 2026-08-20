"""Hierarchy attribution and RLS policy for PostgreSQL outbox receipts."""

from __future__ import annotations

from typing import Any

POSTGRES_OUTBOX_CONSUMER_SCOPE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.outbox_consumer_receipts
    ADD COLUMN IF NOT EXISTS workspace_id TEXT
    DEFAULT NULLIF(current_setting('app.workspace_id', true), '');
ALTER TABLE reconforge.outbox_consumer_receipts
    ALTER COLUMN workspace_id SET DEFAULT NULLIF(current_setting('app.workspace_id', true), '');
ALTER TABLE reconforge.outbox_consumer_receipts
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.outbox_consumer_receipts
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.outbox_consumer_receipts
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.outbox_consumer_receipts
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

CREATE INDEX IF NOT EXISTS outbox_consumer_receipts_scope_event_idx
    ON reconforge.outbox_consumer_receipts(
        tenant_id, workspace_id, organization_id, legal_entity_id, event_id, consumer_id
    );

DROP POLICY IF EXISTS tenant_scope ON reconforge.outbox_consumer_receipts;
CREATE POLICY tenant_scope ON reconforge.outbox_consumer_receipts
    USING (tenant_id = current_setting('app.tenant_id', true)
       AND (NULLIF(current_setting('app.workspace_id', true), '') IS NULL
            OR workspace_id = current_setting('app.workspace_id', true))
       AND (NULLIF(current_setting('app.organization_id', true), '') IS NULL
            OR organization_id = current_setting('app.organization_id', true))
       AND (NULLIF(current_setting('app.legal_entity_id', true), '') IS NULL
            OR legal_entity_id = current_setting('app.legal_entity_id', true)))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)
       AND (NULLIF(current_setting('app.workspace_id', true), '') IS NULL
            OR workspace_id = current_setting('app.workspace_id', true))
       AND (NULLIF(current_setting('app.organization_id', true), '') IS NULL
            OR organization_id = current_setting('app.organization_id', true))
       AND (NULLIF(current_setting('app.legal_entity_id', true), '') IS NULL
            OR legal_entity_id = current_setting('app.legal_entity_id', true)));
"""


def install_postgres_outbox_consumer_scope_schema(connection: Any) -> None:
    """Install additive hierarchy attribution for existing consumer receipts."""

    connection.execute(POSTGRES_OUTBOX_CONSUMER_SCOPE_SCHEMA_SQL)
