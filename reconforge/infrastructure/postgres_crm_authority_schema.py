"""Forward-only provenance binding for new CRM quotations; no historical inference."""
from __future__ import annotations

UPGRADE_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.crm_quotation_authorities (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    identity_contract TEXT NOT NULL CHECK(identity_contract='canonical-user-v1'),
    PRIMARY KEY(tenant_id,workspace_id,quote_id),
    FOREIGN KEY(tenant_id,workspace_id,quote_id) REFERENCES reconforge.crm_quotations(tenant_id,workspace_id,quote_id),
    FOREIGN KEY(tenant_id,user_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
ALTER TABLE reconforge.crm_quotation_authorities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.crm_quotation_authorities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.crm_quotation_authorities;
CREATE POLICY tenant_scope ON reconforge.crm_quotation_authorities
    USING (tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true));
CREATE OR REPLACE FUNCTION reconforge.reject_crm_authority_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Quotation authority is immutable'; END;
$$;
DROP TRIGGER IF EXISTS crm_authority_immutable ON reconforge.crm_quotation_authorities;
CREATE TRIGGER crm_authority_immutable BEFORE UPDATE OR DELETE ON reconforge.crm_quotation_authorities
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_crm_authority_mutation();
"""

DOWNGRADE_SQL = r"""
DO $$ BEGIN
IF EXISTS (SELECT 1 FROM reconforge.crm_quotation_authorities) THEN
    RAISE EXCEPTION 'Populated CRM authority prevents downgrade; retain data and use forward recovery';
END IF;
END $$;
DROP TABLE reconforge.crm_quotation_authorities;
DROP FUNCTION reconforge.reject_crm_authority_mutation();
"""
