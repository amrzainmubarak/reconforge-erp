"""Forward receipt admission repair; no retained financial history is rewritten."""
from typing import Any

POSTGRES_RECEIPT_ADMISSION_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.irp_admit(j JSONB) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE s JSONB:=j->'scope'; v JSONB:=j->'source'; m JSONB:=j->'mapping'; c JSONB:=j->'currency_policy'; t TEXT:=current_setting('app.tenant_id',true); period RECORD; reference RECORD; chart TEXT;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'currency_registry_binding',s->>'workspace_id')::text,0));
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt mutations require READ COMMITTED.'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'finance_dimensions',s->>'workspace_id')::text,0));
 SELECT * INTO period FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=v->>'period_id' FOR SHARE;
 IF period IS NULL OR period.status<>'Open' OR period.application_workspace_id IS DISTINCT FROM s->>'workspace_id'
 OR (v->>'posting_date')::date NOT BETWEEN period.start_date AND period.end_date THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt needs its current open scoped period.'; END IF;
 PERFORM 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=s->>'organization_id' AND e.id=s->>'legal_entity_id'
 AND o.application_workspace_id=s->>'workspace_id' AND o.organization_code=s->>'organization_code' AND e.entity_code=s->>'entity_code'
 AND o.active AND e.active AND e.currency_code=c->>'currency_code' FOR SHARE OF o,e;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt canonical authority or functional currency differs.'; END IF;
 PERFORM 1 FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
 WHERE i.tenant_id=t AND i.id=v->>'item_id' AND i.uom_id=v->>'uom_id' AND i.workspace_id=s->>'workspace_id'
 AND (i.organization_id IS NULL OR i.organization_id=s->>'organization_id') AND i.active AND u.active
 AND i.item_type IN ('Stock','Consumable') AND i.tracking_mode='None' AND u.decimal_places=(v->>'quantity_precision')::integer
 AND i.inventory_account_id=m->>'inventory_account_id' FOR SHARE OF i,u;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt stock master differs from its source.'; END IF;
 PERFORM 1 FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
 WHERE l.tenant_id=t AND l.id=v->>'location_id' AND l.active AND w.active AND l.location_type='Internal' AND NOT l.allow_negative
 AND w.workspace_id=s->>'workspace_id' AND w.organization_id=s->>'organization_id'
 AND (w.legal_entity_id IS NULL OR w.legal_entity_id=s->>'legal_entity_id') FOR SHARE OF l,w;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt location differs from its source scope.'; END IF;
 PERFORM 1 FROM reconforge.inventory_valuation_policies p WHERE p.tenant_id=t AND p.id=m->>'policy_id' AND p.active
 AND p.workspace_id=s->>'workspace_id' AND p.organization_id=s->>'organization_id' AND p.legal_entity_id=s->>'legal_entity_id'
 AND p.costing_method='FIFO' AND p.currency_code=c->>'currency_code' AND p.finance_journal_id=m->>'journal_id'
 AND p.receipt_clearing_account_id=m->>'receipt_clearing_account_id' AND p.cogs_account_id=m->>'cogs_account_id'
 AND p.adjustment_account_id=m->>'adjustment_account_id' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt current mapping differs from its retained mapping.'; END IF;
 SELECT chart_id INTO chart FROM reconforge.finance_journals WHERE tenant_id=t AND id=m->>'journal_id';
 FOR reference IN SELECT * FROM (VALUES ('finance_charts',chart),('finance_journals',m->>'journal_id'),
  ('finance_accounts',m->>'inventory_account_id'),('finance_accounts',m->>'receipt_clearing_account_id'),
  ('finance_accounts',m->>'cogs_account_id'),('finance_accounts',m->>'adjustment_account_id')) x(table_name,id)
  ORDER BY table_name COLLATE "C",id COLLATE "C" LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,reference.table_name,reference.id)::text,0));
 END LOOP;
 PERFORM 1 FROM reconforge.finance_journals jn JOIN reconforge.finance_charts ch ON ch.tenant_id=jn.tenant_id AND ch.id=jn.chart_id
 JOIN reconforge.finance_accounts a ON a.tenant_id=jn.tenant_id AND a.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts b ON b.tenant_id=jn.tenant_id AND b.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts acogs ON acogs.tenant_id=jn.tenant_id AND acogs.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts aadjust ON aadjust.tenant_id=jn.tenant_id AND aadjust.chart_id=jn.chart_id
 WHERE jn.tenant_id=t AND jn.id=m->>'journal_id' AND jn.active AND ch.active AND a.active AND b.active AND a.allow_posting AND b.allow_posting
 AND a.id=m->>'inventory_account_id' AND b.id=m->>'receipt_clearing_account_id' AND a.id<>b.id
 AND acogs.id=m->>'cogs_account_id' AND aadjust.id=m->>'adjustment_account_id' AND acogs.active AND aadjust.active AND acogs.allow_posting AND aadjust.allow_posting
 AND jn.workspace_id=s->>'workspace_id' AND jn.organization_code=s->>'organization_code' AND jn.currency_code=c->>'currency_code'
;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM reconforge.finance_dimensions WHERE tenant_id=t AND workspace_id=s->>'workspace_id'
 AND active AND required_on_entries AND organization_code IN ('',s->>'organization_code')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt requires its active journal/accounts and no required dimensions.'; END IF;
 PERFORM 1 FROM reconforge.currencies WHERE tenant_id=t AND code=c->>'currency_code' AND active AND minor_units=(c->>'currency_precision')::integer FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt current currency differs from retained precision.'; END IF;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_currency_registry_admission_lock() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $lock$
DECLARE row_scope JSONB;
BEGIN
 row_scope:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.workspace_id) IS DISTINCT FROM (OLD.tenant_id,OLD.workspace_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Currency binding identity is immutable.';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(row_scope->>'tenant_id','currency_registry_binding',row_scope->>'workspace_id')::text,0));
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $lock$;
DROP TRIGGER IF EXISTS currency_registry_admission_lock ON reconforge.currency_registry_bindings;
CREATE TRIGGER currency_registry_admission_lock BEFORE INSERT OR UPDATE OR DELETE ON reconforge.currency_registry_bindings
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_currency_registry_admission_lock();
"""

def install_postgres_receipt_admission(connection: Any) -> None:
    connection.execute(POSTGRES_RECEIPT_ADMISSION_SQL)

PREVIOUS_RECEIPT_ADMISSION_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.irp_admit(j JSONB) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE s JSONB:=j->'scope'; v JSONB:=j->'source'; m JSONB:=j->'mapping'; c JSONB:=j->'currency_policy'; t TEXT:=current_setting('app.tenant_id',true); period RECORD; reference RECORD; chart TEXT;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt mutations require READ COMMITTED.'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'finance_dimensions',s->>'workspace_id')::text,0));
 SELECT * INTO period FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=v->>'period_id' FOR SHARE;
 IF period IS NULL OR period.status<>'Open' OR period.application_workspace_id IS DISTINCT FROM s->>'workspace_id'
 OR (v->>'posting_date')::date NOT BETWEEN period.start_date AND period.end_date THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt needs its current open scoped period.'; END IF;
 PERFORM 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=s->>'organization_id' AND e.id=s->>'legal_entity_id'
 AND o.application_workspace_id=s->>'workspace_id' AND o.organization_code=s->>'organization_code' AND e.entity_code=s->>'entity_code'
 AND o.active AND e.active AND e.currency_code=c->>'currency_code' FOR SHARE OF o,e;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt canonical authority or functional currency differs.'; END IF;
 PERFORM 1 FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
 WHERE i.tenant_id=t AND i.id=v->>'item_id' AND i.uom_id=v->>'uom_id' AND i.workspace_id=s->>'workspace_id'
 AND (i.organization_id IS NULL OR i.organization_id=s->>'organization_id') AND i.active AND u.active
 AND i.item_type='Stock' AND i.tracking_mode='None' AND u.decimal_places=(v->>'quantity_precision')::integer
 AND i.inventory_account_id=m->>'inventory_account_id' FOR SHARE OF i,u;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt stock master differs from its source.'; END IF;
 PERFORM 1 FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
 WHERE l.tenant_id=t AND l.id=v->>'location_id' AND l.active AND w.active AND l.location_type='Internal' AND NOT l.allow_negative
 AND w.workspace_id=s->>'workspace_id' AND w.organization_id=s->>'organization_id'
 AND (w.legal_entity_id IS NULL OR w.legal_entity_id=s->>'legal_entity_id') FOR SHARE OF l,w;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt location differs from its source scope.'; END IF;
 PERFORM 1 FROM reconforge.inventory_valuation_policies p WHERE p.tenant_id=t AND p.id=m->>'policy_id' AND p.active
 AND p.workspace_id=s->>'workspace_id' AND p.organization_id=s->>'organization_id' AND p.legal_entity_id=s->>'legal_entity_id'
 AND p.costing_method='FIFO' AND p.currency_code=c->>'currency_code' AND p.finance_journal_id=m->>'journal_id'
 AND p.receipt_clearing_account_id=m->>'receipt_clearing_account_id' AND p.cogs_account_id=m->>'cogs_account_id'
 AND p.adjustment_account_id=m->>'adjustment_account_id' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt current mapping differs from its retained mapping.'; END IF;
 SELECT chart_id INTO chart FROM reconforge.finance_journals WHERE tenant_id=t AND id=m->>'journal_id';
 FOR reference IN SELECT * FROM (VALUES ('finance_charts',chart),('finance_journals',m->>'journal_id'),
  ('finance_accounts',m->>'inventory_account_id'),('finance_accounts',m->>'receipt_clearing_account_id'),
  ('finance_accounts',m->>'cogs_account_id'),('finance_accounts',m->>'adjustment_account_id')) x(table_name,id)
  ORDER BY table_name COLLATE "C",id COLLATE "C" LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,reference.table_name,reference.id)::text,0));
 END LOOP;
 PERFORM 1 FROM reconforge.finance_journals jn JOIN reconforge.finance_charts ch ON ch.tenant_id=jn.tenant_id AND ch.id=jn.chart_id
 JOIN reconforge.finance_accounts a ON a.tenant_id=jn.tenant_id AND a.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts b ON b.tenant_id=jn.tenant_id AND b.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts acogs ON acogs.tenant_id=jn.tenant_id AND acogs.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts aadjust ON aadjust.tenant_id=jn.tenant_id AND aadjust.chart_id=jn.chart_id
 WHERE jn.tenant_id=t AND jn.id=m->>'journal_id' AND jn.active AND ch.active AND a.active AND b.active AND a.allow_posting AND b.allow_posting
 AND a.id=m->>'inventory_account_id' AND b.id=m->>'receipt_clearing_account_id' AND a.id<>b.id
 AND acogs.id=m->>'cogs_account_id' AND aadjust.id=m->>'adjustment_account_id' AND acogs.active AND aadjust.active AND acogs.allow_posting AND aadjust.allow_posting
 AND jn.workspace_id=s->>'workspace_id' AND jn.organization_code=s->>'organization_code' AND jn.currency_code=c->>'currency_code'
;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM reconforge.finance_dimensions WHERE tenant_id=t AND workspace_id=s->>'workspace_id'
 AND active AND required_on_entries AND organization_code IN ('',s->>'organization_code')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt requires its active journal/accounts and no required dimensions.'; END IF;
 PERFORM 1 FROM reconforge.currencies WHERE tenant_id=t AND code=c->>'currency_code' AND active AND minor_units=(c->>'currency_precision')::integer FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt current currency differs from retained precision.'; END IF;
END $irp$;
"""
