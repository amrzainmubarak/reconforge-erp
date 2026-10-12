"""Deny shared master-data writes from narrower selected authority.

Reference reads/locks and existing broader setup remain available. Downgrade
removes this mutation boundary without changing retained data.
"""
from alembic import op

revision = "0096_pg_master_authority"
down_revision = "0095_pg_finance_scope"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- SELECT/FOR SHARE must remain available to Finance canonical-parent checks.
-- Mutation guards preserve existing RLS and all five transaction-local GUCs.
CREATE OR REPLACE FUNCTION reconforge.guard_master_data_mutation_authority() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
DECLARE
 selected_organization TEXT := NULLIF(current_setting('app.organization_id',true),'');
 selected_entity TEXT := NULLIF(current_setting('app.legal_entity_id',true),'');
 entity_alias TEXT := NULLIF(current_setting('app.entity_id',true),'');
BEGIN
 IF selected_entity IS DISTINCT FROM entity_alias THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Master-data execution scope aliases disagree.';
 END IF;
 IF (TG_TABLE_NAME='organizations' AND selected_entity IS NOT NULL)
    OR (TG_TABLE_NAME IN ('currencies','fiscal_periods')
        AND (selected_organization IS NOT NULL OR selected_entity IS NOT NULL)) THEN
  RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='The selected authority cannot mutate shared master data.';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $reconforge$;

DROP TRIGGER IF EXISTS master_data_mutation_authority ON reconforge.currencies;
CREATE TRIGGER master_data_mutation_authority BEFORE INSERT OR UPDATE OR DELETE ON reconforge.currencies
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_master_data_mutation_authority();
DROP TRIGGER IF EXISTS master_data_mutation_authority ON reconforge.organizations;
CREATE TRIGGER master_data_mutation_authority BEFORE INSERT OR UPDATE OR DELETE ON reconforge.organizations
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_master_data_mutation_authority();
DROP TRIGGER IF EXISTS master_data_mutation_authority ON reconforge.fiscal_periods;
CREATE TRIGGER master_data_mutation_authority BEFORE INSERT OR UPDATE OR DELETE ON reconforge.fiscal_periods
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_master_data_mutation_authority();
"""

DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS master_data_mutation_authority ON reconforge.currencies;
DROP TRIGGER IF EXISTS master_data_mutation_authority ON reconforge.organizations;
DROP TRIGGER IF EXISTS master_data_mutation_authority ON reconforge.fiscal_periods;
DROP FUNCTION IF EXISTS reconforge.guard_master_data_mutation_authority();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
