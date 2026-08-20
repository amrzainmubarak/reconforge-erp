"""PostgreSQL transactional-outbox hierarchy attribution and RLS policy."""

from __future__ import annotations

from typing import Any

POSTGRES_OUTBOX_SCOPE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.outbox_events
    ADD COLUMN IF NOT EXISTS workspace_id TEXT
    DEFAULT NULLIF(current_setting('app.workspace_id', true), '');
ALTER TABLE reconforge.outbox_events
    ALTER COLUMN workspace_id SET DEFAULT NULLIF(current_setting('app.workspace_id', true), '');
ALTER TABLE reconforge.outbox_events
    ADD COLUMN IF NOT EXISTS organization_id TEXT
    DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.outbox_events
    ALTER COLUMN organization_id SET DEFAULT NULLIF(current_setting('app.organization_id', true), '');
ALTER TABLE reconforge.outbox_events
    ADD COLUMN IF NOT EXISTS legal_entity_id TEXT
    DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');
ALTER TABLE reconforge.outbox_events
    ALTER COLUMN legal_entity_id SET DEFAULT NULLIF(current_setting('app.legal_entity_id', true), '');

CREATE INDEX IF NOT EXISTS idx_outbox_events_scope_pending
    ON reconforge.outbox_events
       (tenant_id, workspace_id, organization_id, legal_entity_id, status, available_at);

DROP POLICY IF EXISTS tenant_scope ON reconforge.outbox_events;
CREATE POLICY tenant_scope ON reconforge.outbox_events
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


def install_postgres_outbox_scope_schema(connection: Any) -> None:
    """Install outbox hierarchy attribution without rewriting existing events."""

    connection.execute(POSTGRES_OUTBOX_SCOPE_SCHEMA_SQL)
