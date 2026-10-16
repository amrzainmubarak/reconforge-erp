"""Native149 monetary origin, exact signed history and correction ownership.

All functions execute as the caller. Public report projections share their
outer SELECT snapshot; authoritative mutation/history functions are VOLATILE.
The seven relations and reversible legacy-function installation are separate.
"""

import re

from reconforge.infrastructure.postgres_customer_partial_return_zero_stock_hooks import (
    _stock_close as _retained_zero_stock_close,
)
from reconforge.infrastructure.postgres_monetary_inventory_native import NATIVE_FUNCTION_SQL as PHYSICAL_FUNCTION_SQL
from reconforge.infrastructure.postgres_monetary_inventory_transfer_schema import (
    NATIVE_FUNCTION_SQL as TRANSFER_FUNCTION_SQL,
)
from reconforge.infrastructure.postgres_monetary_stock_schema import DOWNGRADE_PREFLIGHT_SQL, TABLES
from reconforge.infrastructure.postgres_operational_fx_tax_schema import UPGRADE_SQL as ORIGINAL_FX_SQL
from reconforge.infrastructure.postgres_stock_sales_schema import POSTGRES_STOCK_SALES_SCHEMA_SQL as ORIGINAL_STOCK_SQL


def _replace_once(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("The retained original monetary owner contract differs.")
    return value.replace(old, new, 1)


def _original_equation() -> str:
    start = " FOREACH field IN ARRAY ARRAY['organization_code','entity_code','customer_code','invoice_number','journal_code','period_id','transaction_class',"
    end = " last_day:=q->>'posting_date';"
    if ORIGINAL_FX_SQL.count(start) != 1 or ORIGINAL_FX_SQL.count(end) != 1:
        raise ValueError("One exact retained FX original invoice equation is required.")
    value = ORIGINAL_FX_SQL[ORIGINAL_FX_SQL.index(start):ORIGINAL_FX_SQL.index(end)]
    value = _replace_once(value,
        "AND a->'foreign_policy'->>'currency_code'<>a->'functional_policy'->>'currency_code'",
        "AND(a->'foreign_policy'->>'currency_code'<>a->'functional_policy'->>'currency_code' OR(q->'original_rate'='null'::jsonb AND a->'foreign_policy'=a->'functional_policy'))")
    value = _replace_once(value, "rate:=reconforge.fx_rate(q->'original_rate',q->>'posting_date');",
        "rate:=CASE WHEN a#>>'{foreign_policy,currency_code}'=a#>>'{functional_policy,currency_code}' THEN NULL ELSE reconforge.fx_rate(q->'original_rate',q->>'posting_date') END;")
    value = _replace_once(value, "fn:=reconforge.fx_convert(net,rate,fp,lp);", "fn:=CASE WHEN rate IS NULL THEN net ELSE reconforge.fx_convert(net,rate,fp,lp) END;")
    value = _replace_once(value, "lt:=reconforge.fx_convert(fg,rate,fp,lp)-lg;", "lt:=(CASE WHEN rate IS NULL THEN fg ELSE reconforge.fx_convert(fg,rate,fp,lp) END)-lg;")
    value = _replace_once(value,
        "AND x.quantity=1 AND x.quantity_text='1' AND x.unit_price_minor=net AND x.line_total_minor=net AND x.tax_minor=fg-net AND x.description=q->>'reason'",
        "AND x.quantity=stock_owner.quantity_scaled::numeric/power(10::numeric,stock_owner.quantity_precision) "
        "AND x.quantity_text=stock_owner.source->>'quantity' AND x.unit_price_minor=(stock_owner.source->>'net_unit_price_minor')::bigint "
        "AND x.line_total_minor=net AND x.tax_minor=fg-net AND x.description=stock_owner.source->>'description'")
    return value


_ORIGINAL_EQUATION_PREFIX = r"""
CREATE FUNCTION reconforge.monetary_fx_original_equation(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE s RECORD;stock_owner RECORD;inv RECORD;customer RECORD;a JSONB;q JSONB;tax JSONB;field TEXT;
 fp INTEGER;lp INTEGER;net NUMERIC;fg NUMERIC;fn NUMERIC;lg NUMERIC;ft NUMERIC;lt NUMERIC;rate NUMERIC;
 expected JSONB;components JSONB:='[]';
BEGIN
 SELECT * INTO s FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=i;a:=s.payload;q:=a->'request';
 SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=a->>'stock_order_id';
 SELECT * INTO inv FROM reconforge.ar_invoices WHERE tenant_id=t AND id=s.invoice_id;
 SELECT * INTO customer FROM reconforge.ar_customers WHERE tenant_id=t AND id=inv.customer_id;
 PERFORM reconforge.monetary_return_assert(s.id IS NOT NULL AND stock_owner.id IS NOT NULL AND inv.id IS NOT NULL AND customer.id IS NOT NULL
 AND reconforge.irp_scope(t,s.workspace_id,s.organization_id,s.legal_entity_id)
 AND reconforge.fx_object(a,ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','request','foreign_policy','functional_policy',
  'foreign_net_minor','foreign_tax_minor','foreign_gross_minor','functional_net_minor','functional_gross_minor','tax_components',
  'functional_allocation_policy','lines','preparer_actor_id','invoice_id','source_digest','stock_order_id','stock_source_digest'])
 AND reconforge.fx_object(q,ARRAY['workspace_id','organization_id','legal_entity_id','organization_code','entity_code','customer_code','invoice_number',
  'posting_date','due_date','period_id','journal_code','foreign_currency_code','net_minor','original_rate','country_code','transaction_class','taxes',
  'receivable_account_code','revenue_account_code','cash_account_code','gain_account_code','loss_account_code','reason'])
 AND a->>'schema_version'='operational-fx-stock-source-v2' AND stock_owner.source->>'schema_version'='stock-sales-monetary-order-v2'
 AND a->>'source_digest'=reconforge.irp_digest(a-'source_digest') AND a->>'stock_source_digest'=stock_owner.source_digest
 AND a->>'stock_order_id'=stock_owner.id AND a->>'id'=s.id AND a->>'invoice_id'=s.invoice_id
 AND(stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id,stock_owner.customer_id,stock_owner.currency_code)
  =(s.workspace_id,s.organization_id,s.legal_entity_id,inv.customer_id,inv.currency_code)
 AND(a->>'workspace_id',a->>'organization_id',a->>'legal_entity_id')=(s.workspace_id,s.organization_id,s.legal_entity_id)
 AND(q->>'workspace_id',q->>'organization_id',q->>'legal_entity_id')=(s.workspace_id,s.organization_id,s.legal_entity_id)
 AND a->'foreign_policy'=reconforge.monetary_full_policy(stock_owner.source->'monetary_policy')
 AND a->'functional_policy'=reconforge.monetary_full_policy(stock_owner.source->'functional_policy')
 AND(stock_owner.invoice_id IS NULL OR stock_owner.invoice_id=s.invoice_id)
 AND(q->>'net_minor')::numeric=stock_owner.total_minor AND stock_owner.source->>'total_minor'=stock_owner.total_minor::text,
 'A monetary invoice must preserve its actual fixed Stock quantity, original transaction price, native AR line and FX source one-to-one');
 FOREACH field IN ARRAY ARRAY['foreign_net_minor','foreign_tax_minor','foreign_gross_minor','functional_net_minor','functional_gross_minor'] LOOP
  PERFORM reconforge.monetary_return_assert(reconforge.fx_minor(a->field),'Original foreign and functional monetary totals must be exact bounded integers');
 END LOOP;
"""
ORIGINAL_EQUATION_SQL = "".join((_ORIGINAL_EQUATION_PREFIX, _original_equation(), r"""
 RETURN a-ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','preparer_actor_id','invoice_id','source_digest','stock_order_id','stock_source_digest'];
END $mr149$;
"""))


def _stock_body(name: str, following: str) -> str:
    start = ORIGINAL_STOCK_SQL.index("CREATE FUNCTION reconforge." + name + "(")
    end = ORIGINAL_STOCK_SQL.index(following, start)
    definition = ORIGINAL_STOCK_SQL[start:end]
    return definition[definition.index("AS $$") + 5:definition.rindex("$$;")]


def _stock_physical() -> str:
    """Retain the accepted native issue proof, with an explicit L policy."""
    definition = _retained_zero_stock_close()
    body = definition[definition.index("AS $$") + 5:definition.rindex("$$;")]
    body = body[:body.index(" IF d.invoice_id IS NOT NULL THEN")]
    begin = body.index(" s:=reconforge.stock_sales_stage(d.status);")
    retained = body.index(" SELECT * INTO r FROM reconforge.stock_sales_reservations")
    body = body[:begin] + """
 s:=CASE WHEN d.movement_id IS NOT NULL THEN 6 WHEN d.issue_reviewer_id IS NOT NULL THEN 5
  WHEN d.issue_plan IS NOT NULL THEN 4 WHEN d.status='Reserved' THEN 3 ELSE reconforge.stock_sales_stage(d.status) END;
""" + body[retained:]
    body = body.replace("PERFORM reconforge.customer_partial_return_zero_stock_plan(t,target);", "PERFORM reconforge.monetary_stock_zero_plan(t,target);")
    body = _replace_once(body, " SELECT * INTO r FROM reconforge.stock_sales_reservations", """
 IF d.issue_plan ? 'cost_admission_policy' THEN PERFORM reconforge.monetary_stock_zero_plan(t,target);END IF;
 SELECT * INTO r FROM reconforge.stock_sales_reservations""")
    body = body.replace("d.source->'monetary_policy'", "d.source->'functional_policy'")
    body = re.sub(r"\bd\.currency_code\b", "(d.source#>>'{functional_policy,currency_code}')", body)
    body = body.replace("reconforge.sales_revenue_policy_matches(", "reconforge.monetary_stock_policy_matches(")
    body = body.replace("r IS NULL", "r.order_id IS NULL").replace("r IS NOT NULL", "r.order_id IS NOT NULL")
    body = body.replace("claim IS NULL", "claim.order_id IS NULL").replace("claim IS NOT NULL", "claim.order_id IS NOT NULL")
    body = body.replace("entry IS NULL", "entry.id IS NULL")
    body += """
 IF d.cogs_effect_id IS NOT NULL THEN PERFORM reconforge.monetary_posted_close(t,d.cogs_entry_id,d.cogs_effect_id,d.organization_id,d.legal_entity_id);END IF;
"""
    return "CREATE FUNCTION reconforge.monetary_stock_physical_close(t TEXT,target TEXT) RETURNS VOID LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$\n" + body + "END $mr149$;\n"


def _stock_admit() -> str:
    body = _stock_body("stock_sales_admit", "DO $$ DECLARE n TEXT; BEGIN FOREACH")
    body = _replace_once(body, "DECLARE d RECORD;", "DECLARE native_new RECORD;native_old RECORD;d RECORD;")
    descriptor = """
 CASE table_name
  WHEN 'stock_sales_orders' THEN
   SELECT * INTO native_new FROM jsonb_populate_record(NULL::reconforge.stock_sales_orders,new_row);
   SELECT * INTO native_old FROM jsonb_populate_record(NULL::reconforge.stock_sales_orders,old_row);
  WHEN 'stock_sales_reservations' THEN
   SELECT * INTO native_new FROM jsonb_populate_record(NULL::reconforge.stock_sales_reservations,new_row);
   SELECT * INTO native_old FROM jsonb_populate_record(NULL::reconforge.stock_sales_reservations,old_row);
  WHEN 'stock_sales_issue_claims' THEN
   SELECT * INTO native_new FROM jsonb_populate_record(NULL::reconforge.stock_sales_issue_claims,new_row);
   SELECT * INTO native_old FROM jsonb_populate_record(NULL::reconforge.stock_sales_issue_claims,old_row);
  WHEN 'stock_sales_events' THEN
   SELECT * INTO native_new FROM jsonb_populate_record(NULL::reconforge.stock_sales_events,new_row);
  WHEN 'stock_sales_commands' THEN
   SELECT * INTO native_new FROM jsonb_populate_record(NULL::reconforge.stock_sales_commands,new_row);
  ELSE PERFORM reconforge.monetary_return_assert(FALSE,'Unknown monetary Stock relation');
 END CASE;
 PERFORM reconforge.monetary_return_assert(operation<>'DELETE','Monetary Stock history cannot be deleted');
 IF operation='UPDATE' THEN
  IF table_name='stock_sales_orders' THEN
   PERFORM reconforge.monetary_return_assert(
    (new_row-ARRAY['status','approved_by','issue_plan','cogs_entry_id','issue_reviewer_id','movement_id','valuation_id','cogs_effect_id',
     'invoice_id','invoice_plan_id','invoice_parameters','collection_plan_id','collection_parameters','receipt_id','row_version','updated_at'])
    =(old_row-ARRAY['status','approved_by','issue_plan','cogs_entry_id','issue_reviewer_id','movement_id','valuation_id','cogs_effect_id',
     'invoice_id','invoice_plan_id','invoice_parameters','collection_plan_id','collection_parameters','receipt_id','row_version','updated_at'])
    AND native_new.row_version=native_old.row_version+1 AND native_new.row_version<=1024
    AND((reconforge.stock_sales_stage(native_new.status)=reconforge.stock_sales_stage(native_old.status)+1)
     OR(native_old.status IN('Invoiced','Paid') AND native_new.status='CollectionPrepared')
     OR(native_old.status='CollectionReviewed' AND native_new.status IN('Invoiced','Paid'))
     OR(native_new.status='Cancelled' AND native_old.status IN('Draft','Submitted','Approved','Reserved','IssueReviewed')))
    AND(native_old.approved_by IS NULL OR native_old.approved_by IS NOT DISTINCT FROM native_new.approved_by)
    AND(native_old.issue_plan IS NULL OR(native_old.issue_plan,native_old.cogs_entry_id) IS NOT DISTINCT FROM(native_new.issue_plan,native_new.cogs_entry_id))
    AND(native_old.movement_id IS NULL OR(native_old.movement_id,native_old.valuation_id,native_old.cogs_effect_id)
     IS NOT DISTINCT FROM(native_new.movement_id,native_new.valuation_id,native_new.cogs_effect_id))
    AND(native_old.invoice_id IS NULL OR(native_old.invoice_id,native_old.invoice_plan_id,native_old.invoice_parameters)
     IS NOT DISTINCT FROM(native_new.invoice_id,native_new.invoice_plan_id,native_new.invoice_parameters))
    AND(native_old.collection_plan_id IS NULL OR native_old.status IN('Invoiced','Paid')
     OR(native_old.collection_plan_id,native_old.collection_parameters) IS NOT DISTINCT FROM(native_new.collection_plan_id,native_new.collection_parameters)),
    'The fixed monetary Stock source and its reviewed native links are immutable');
  ELSE
   PERFORM reconforge.monetary_return_assert(table_name IN('stock_sales_reservations','stock_sales_issue_claims')
    AND old_row->>'state'='Active' AND new_row->>'state' IN('Consumed','Released') AND new_row-'state'=old_row-'state',
    'Only the exact active reservation or FIFO claim may be consumed or released');
  END IF;
 END IF;
"""
    body = _replace_once(body, "BEGIN\n", "BEGIN\n" + descriptor)
    body = body.replace("TG_TABLE_NAME", "table_name").replace("TG_OP", "operation").replace("NEW.", "native_new.").replace("d:=NEW;", "d:=native_new;")
    body = body.replace("RETURN NEW;", "RETURN;")
    body = body.replace("'stock-sales-order-v1'", "'stock-sales-monetary-order-v2'")
    body = _replace_once(body,
        "reconforge.sales_revenue_policy_matches(native_new.tenant_id,\n    q->'monetary_policy',c.currency_code,c.currency_precision,c.currency_rounding_policy,c.currency_registry_version,c.currency_registry_digest)",
        "reconforge.monetary_full_policy(q->'monetary_policy')=jsonb_build_object('currency_code',c.currency_code,"
        "'currency_precision',c.currency_precision,'currency_rounding_policy',c.currency_rounding_policy,"
        "'currency_registry_version',c.currency_registry_version,'currency_registry_digest',c.currency_registry_digest)")
    body = _replace_once(body, "q:=native_new.source;", """q:=native_new.source;
  PERFORM reconforge.monetary_return_assert(reconforge.fx_policy(native_new.tenant_id,reconforge.monetary_full_policy(q->'monetary_policy'))
   AND reconforge.fx_policy(native_new.tenant_id,reconforge.monetary_full_policy(q->'functional_policy'))
   AND q#>>'{functional_policy,registry_digest}'=q#>>'{monetary_policy,registry_digest}'
   AND EXISTS(SELECT 1 FROM reconforge.legal_entities entity_owner WHERE entity_owner.tenant_id=native_new.tenant_id
    AND entity_owner.id=native_new.legal_entity_id AND entity_owner.currency_code=q#>>'{functional_policy,currency_code}'),
   'Both captured policies and the actual entity functional currency are required');
""")
    return "CREATE FUNCTION reconforge.monetary_stock_admit(table_name TEXT,operation TEXT,old_row JSONB,new_row JSONB) RETURNS VOID LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$\n" + body + "$mr149$;\n"


STOCK_PHYSICAL_SQL = _stock_physical()
STOCK_ADMISSION_SQL = _stock_admit()

HISTORY_SQL = r"""
CREATE FUNCTION reconforge.monetary_return_assert(ok BOOLEAN,message TEXT) RETURNS VOID
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $mr149$
BEGIN IF ok IS DISTINCT FROM TRUE THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',MESSAGE=message;
END IF;END $mr149$;
CREATE FUNCTION reconforge.monetary_full_policy(compact JSONB) RETURNS JSONB
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $mr149$
 SELECT jsonb_build_object('currency_code',compact->'currency_code','currency_precision',compact->'precision',
  'currency_rounding_policy',compact->'rounding_policy','currency_registry_version',compact->'registry_version',
  'currency_registry_digest',compact->'registry_digest')
 WHERE reconforge.fx_object(compact,ARRAY['currency_code','precision','rounding_policy','registry_version','registry_digest'])
$mr149$;
CREATE FUNCTION reconforge.monetary_stock_policy_matches(t TEXT,q JSONB,c TEXT,p INTEGER,r TEXT,v TEXT,h TEXT) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $mr149$
 SELECT COALESCE(reconforge.fx_object(q,ARRAY['currency_code','precision','rounding_policy','registry_version','registry_digest'])
  AND reconforge.fx_policy(t,reconforge.monetary_full_policy(q))
  AND reconforge.monetary_full_policy(q)=jsonb_build_object('currency_code',c,'currency_precision',p,
   'currency_rounding_policy',r,'currency_registry_version',v,'currency_registry_digest',h),FALSE)
$mr149$;
CREATE FUNCTION reconforge.monetary_return_ratio(v NUMERIC,q NUMERIC,selected NUMERIC) RETURNS BIGINT
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $mr149$
DECLARE result NUMERIC;
BEGIN
 PERFORM reconforge.monetary_return_assert(v BETWEEN 0 AND 9000000000000000000 AND v=trunc(v)
 AND q BETWEEN 1 AND 9000000000000000000 AND q=trunc(q)
 AND selected BETWEEN 0 AND q AND selected=trunc(selected),'Exact bounded remaining-value arguments are required');
 IF selected=q THEN RETURN v::bigint;END IF;
 result:=div(v*selected,q)+CASE WHEN mod(v*selected,q)*2>=q THEN 1 ELSE 0 END;
 RETURN result::bigint;
END $mr149$;
CREATE FUNCTION reconforge.monetary_return_source_fingerprint(source JSONB) RETURNS TEXT
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $mr149$
 SELECT reconforge.irp_digest((source-'registry_snapshot')||jsonb_build_object(
 'schema_version','customer-partial-return-monetary-original-v3','registry_digest',source#>>'{registry_snapshot,digest}'))
$mr149$;
CREATE FUNCTION reconforge.monetary_return_initial(source JSONB) RETURNS JSONB
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $mr149$
 SELECT jsonb_build_object('remaining_quantity_scaled',source->'quantity_scaled',
 'component_transaction_minor',(SELECT jsonb_agg(component.value->'transaction_minor' ORDER BY component.ordinal)
   FROM jsonb_array_elements(source->'components') WITH ORDINALITY component(value,ordinal)),
 'component_functional_minor',(SELECT jsonb_agg(component.value->'functional_minor' ORDER BY component.ordinal)
   FROM jsonb_array_elements(source->'components') WITH ORDINALITY component(value,ordinal)),
 'consumption_quantity_scaled',(SELECT jsonb_agg(consumed.value->'quantity_scaled' ORDER BY consumed.ordinal)
   FROM jsonb_array_elements(source->'consumptions') WITH ORDINALITY consumed(value,ordinal)),
 'consumption_value_minor',(SELECT jsonb_agg(consumed.value->'value_minor' ORDER BY consumed.ordinal)
   FROM jsonb_array_elements(source->'consumptions') WITH ORDINALITY consumed(value,ordinal)),
 'transaction_outstanding_minor',(SELECT sum((component->>'transaction_minor')::numeric) FROM jsonb_array_elements(source->'components') component),
 'functional_outstanding_minor',(SELECT sum((component->>'functional_minor')::numeric) FROM jsonb_array_elements(source->'components') component),
 'transaction_refund_due_minor',0,'functional_refund_due_minor',0,'transaction_collected_minor',0,
 'transaction_credited_minor',0,'transaction_refunded_minor',0,'functional_refund_released_minor',0)
$mr149$;
CREATE FUNCTION reconforge.monetary_return_next(source JSONB,prefix JSONB,kind TEXT,quantity BIGINT,amount BIGINT,
 day TEXT,rate JSONB,original_sequence INTEGER) RETURNS JSONB LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $mr149$
DECLARE before_state JSONB;after_state JSONB;movement JSONB;components JSONB:='[]';portions JSONB:='[]';part JSONB;
 source_component JSONB;source_consumption JSONB;original_event JSONB;prior_event JSONB;active INTEGER[]:=ARRAY[]::integer[];
 remaining_q BIGINT;selected BIGINT;pending BIGINT;cost BIGINT:=0;allocated BIGINT;position INTEGER;idx INTEGER;sequence INTEGER;
 component_f JSONB;component_l JSONB;consumption_q JSONB;consumption_v JSONB;cut_f BIGINT;cut_l BIGINT;
 credit_f NUMERIC:=0;credit_l NUMERIC:=0;release_f BIGINT:=0;release_l BIGINT:=0;entitlement_f BIGINT:=0;entitlement_l BIGINT:=0;
 alignment NUMERIC:=0;cash BIGINT:=0;difference NUMERIC:=0;carrying_f BIGINT;carrying_l BIGINT;spot NUMERIC;
 source_fp TEXT;chain TEXT;field TEXT;
BEGIN
 PERFORM reconforge.monetary_return_assert(jsonb_typeof(prefix)='array' AND jsonb_array_length(prefix)<256
 AND kind IN('Return','Collection','Refund','ReverseReturn','ReverseRefund')
 AND quantity BETWEEN 0 AND 9000000000000000000 AND amount BETWEEN 0 AND 9000000000000000000
 AND day~'^\d{4}-\d{2}-\d{2}$' AND reconforge.irp_timestamp(day||'T00:00:00Z')
 AND day>=(source->>'posting_date'),'Exact bounded monetary operation and chronology are required');
 sequence:=jsonb_array_length(prefix)+1;source_fp:=reconforge.monetary_return_source_fingerprint(source);
 chain:=CASE WHEN sequence=1 THEN reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-monetary-original-v3',
 'source_fingerprint',source_fp,'allocation_policy','remaining-dual-currency-v1','alignment_policy','historical-carrying-component-alignment-v1'))
 ELSE reconforge.irp_digest(prefix->(sequence-2)) END;
 before_state:=CASE WHEN sequence=1 THEN reconforge.monetary_return_initial(source) ELSE prefix->(sequence-2)->'after' END;
 PERFORM reconforge.monetary_return_assert(sequence=1 OR day>=(prefix->(sequence-2)->>'posting_date'),
  'Monetary history cannot backdate an active or reversed prior operation');
 movement:=jsonb_build_object('transaction_net_minor',0,'transaction_tax_minor',0,'transaction_credit_minor',0,
 'functional_net_minor',0,'functional_tax_minor',0,'functional_credit_minor',0,'functional_cost_minor',0,
 'transaction_receivable_released_minor',0,'functional_receivable_released_minor',0,
 'transaction_refund_delta_minor',0,'functional_refund_delta_minor',0,'transaction_refund_minor',0,
 'functional_refund_released_minor',0,'functional_cash_minor',0,'functional_fx_gain_minor',0,'functional_fx_loss_minor',0,
 'functional_alignment_gain_minor',0,'functional_alignment_loss_minor',0,'functional_turnover_minor',0);
 IF kind IN('ReverseReturn','ReverseRefund') THEN
  PERFORM reconforge.monetary_return_assert(rate IS NULL AND original_sequence IS NOT NULL AND original_sequence>0,
   'An exact inverse cannot introduce a new settlement rate');
  FOR prior_event IN SELECT member.value FROM jsonb_array_elements(prefix) WITH ORDINALITY member(value,ordinal) ORDER BY member.ordinal LOOP
   IF prior_event->>'kind' LIKE'Reverse%' THEN
    PERFORM reconforge.monetary_return_assert(cardinality(active)>0 AND active[cardinality(active)]=(prior_event->>'original_sequence')::integer,
     'Every retained inverse must remove the latest active economic member');
    active:=active[1:cardinality(active)-1];
   ELSE active:=array_append(active,(prior_event->>'sequence')::integer);END IF;
  END LOOP;
  original_event:=prefix->(original_sequence-1);
  PERFORM reconforge.monetary_return_assert(cardinality(active)>0 AND active[cardinality(active)]=original_sequence
   AND kind='Reverse'||(original_event->>'kind') AND before_state=original_event->'after'
   AND quantity=(original_event->>'quantity_scaled')::bigint AND amount=(original_event->>'amount_minor')::bigint,
   'The inverse must copy the exact latest active same-source monetary event');
  after_state:=original_event->'before';movement:=original_event->'monetary';
  components:=original_event->'components';portions:=original_event->'portions';
 ELSIF kind='Return' THEN
  remaining_q:=(before_state->>'remaining_quantity_scaled')::bigint;
  PERFORM reconforge.monetary_return_assert(quantity>0 AND quantity<=remaining_q AND amount=0 AND rate IS NULL
   AND original_sequence IS NULL,'A merchandise credit requires an exact remaining original quantity');
  component_f:=before_state->'component_transaction_minor';component_l:=before_state->'component_functional_minor';
  FOR source_component,idx IN SELECT member.value,(member.ordinal-1)::integer
    FROM jsonb_array_elements(source->'components') WITH ORDINALITY member(value,ordinal) ORDER BY member.ordinal LOOP
   cut_f:=reconforge.monetary_return_ratio((component_f->>idx)::numeric,remaining_q,quantity);
   cut_l:=reconforge.monetary_return_ratio((component_l->>idx)::numeric,remaining_q,quantity);
   part:=jsonb_build_object('position',idx,'before_quantity_scaled',remaining_q,
    'before_transaction_minor',(component_f->>idx)::bigint,'before_functional_minor',(component_l->>idx)::bigint,
    'transaction_minor',cut_f,'functional_minor',cut_l);
   components:=components||jsonb_build_array(part);credit_f:=credit_f+cut_f;credit_l:=credit_l+cut_l;
   component_f:=jsonb_set(component_f,ARRAY[idx::text],to_jsonb((component_f->>idx)::bigint-cut_f));
   component_l:=jsonb_set(component_l,ARRAY[idx::text],to_jsonb((component_l->>idx)::bigint-cut_l));
  END LOOP;
  release_f:=least(credit_f,(before_state->>'transaction_outstanding_minor')::numeric)::bigint;
  IF release_f>0 THEN release_l:=reconforge.monetary_return_ratio((before_state->>'functional_outstanding_minor')::numeric,
   (before_state->>'transaction_outstanding_minor')::numeric,release_f);END IF;
  entitlement_f:=(credit_f-release_f)::bigint;
  IF entitlement_f>0 THEN entitlement_l:=reconforge.monetary_return_ratio(credit_l,credit_f,entitlement_f);END IF;
  alignment:=credit_l-release_l-entitlement_l;
  pending:=quantity;consumption_q:=before_state->'consumption_quantity_scaled';consumption_v:=before_state->'consumption_value_minor';
  FOR source_consumption,idx IN SELECT member.value,(member.ordinal-1)::integer
    FROM jsonb_array_elements(source->'consumptions') WITH ORDINALITY member(value,ordinal) ORDER BY member.ordinal LOOP
   EXIT WHEN pending=0;
   IF(consumption_q->>idx)::bigint=0 THEN CONTINUE;END IF;
   selected:=least(pending,(consumption_q->>idx)::bigint);
   allocated:=reconforge.customer_partial_return_v2_fifo((consumption_v->>idx)::bigint,(consumption_q->>idx)::bigint,selected);
   portions:=portions||jsonb_build_array(jsonb_build_object('position',idx+1,
    'original_consumption_id',source_consumption->>'original_consumption_id',
    'original_valuation_line_id',source_consumption->>'original_valuation_line_id','cost_layer_id',source_consumption->>'cost_layer_id',
    'before_quantity_scaled',(consumption_q->>idx)::bigint,'before_value_minor',(consumption_v->>idx)::bigint,
    'quantity_scaled',selected,'value_minor',allocated));
   consumption_q:=jsonb_set(consumption_q,ARRAY[idx::text],to_jsonb((consumption_q->>idx)::bigint-selected));
   consumption_v:=jsonb_set(consumption_v,ARRAY[idx::text],to_jsonb((consumption_v->>idx)::bigint-allocated));
   pending:=pending-selected;cost:=cost+allocated;
  END LOOP;
  PERFORM reconforge.monetary_return_assert(pending=0,'Every returned unit must restore its exact original reviewed FIFO consumption');
  movement:=movement||jsonb_build_object('transaction_net_minor',components->0->'transaction_minor',
   'transaction_tax_minor',credit_f-(components->0->>'transaction_minor')::numeric,'transaction_credit_minor',credit_f,
   'functional_net_minor',components->0->'functional_minor','functional_tax_minor',credit_l-(components->0->>'functional_minor')::numeric,
   'functional_credit_minor',credit_l,'functional_cost_minor',cost,'transaction_receivable_released_minor',release_f,
   'functional_receivable_released_minor',release_l,'transaction_refund_delta_minor',entitlement_f,'functional_refund_delta_minor',entitlement_l,
   'functional_alignment_gain_minor',greatest(alignment,0),'functional_alignment_loss_minor',greatest(-alignment,0),
   'functional_turnover_minor',credit_l+greatest(-alignment,0)+cost);
  after_state:=before_state||jsonb_build_object('remaining_quantity_scaled',remaining_q-quantity,
   'component_transaction_minor',component_f,'component_functional_minor',component_l,
   'consumption_quantity_scaled',consumption_q,'consumption_value_minor',consumption_v,
   'transaction_outstanding_minor',(before_state->>'transaction_outstanding_minor')::bigint-release_f,
   'functional_outstanding_minor',(before_state->>'functional_outstanding_minor')::bigint-release_l,
   'transaction_refund_due_minor',(before_state->>'transaction_refund_due_minor')::numeric+entitlement_f,
   'functional_refund_due_minor',(before_state->>'functional_refund_due_minor')::numeric+entitlement_l,
   'transaction_credited_minor',(before_state->>'transaction_credited_minor')::numeric+credit_f);
 ELSE
  PERFORM reconforge.monetary_return_assert(quantity=0 AND amount>0 AND original_sequence IS NULL,
   'Cash operations require positive exact transaction money without physical quantity');
  carrying_f:=(before_state->>(CASE WHEN kind='Refund' THEN'transaction_refund_due_minor' ELSE'transaction_outstanding_minor' END))::bigint;
  carrying_l:=(before_state->>(CASE WHEN kind='Refund' THEN'functional_refund_due_minor' ELSE'functional_outstanding_minor' END))::bigint;
  PERFORM reconforge.monetary_return_assert(amount<=carrying_f,'Cash exceeds its actual current historical receivable or refund entitlement');
  release_l:=reconforge.monetary_return_ratio(carrying_l,carrying_f,amount);
  IF source#>>'{transaction_policy,currency_code}'=source#>>'{functional_policy,currency_code}' THEN
   PERFORM reconforge.monetary_return_assert(rate IS NULL,'Identity currency cash cannot fabricate a foreign rate');cash:=amount;
  ELSE
   spot:=reconforge.fx_rate(rate,day);
   PERFORM reconforge.monetary_return_assert(spot IS NOT NULL,'Foreign cash requires exact captured rate provenance');
   cash:=reconforge.fx_convert(amount,spot,(source#>>'{transaction_policy,precision}')::integer,
       (source#>>'{functional_policy,precision}')::integer)::bigint;
  END IF;
  difference:=CASE WHEN kind='Refund' THEN release_l-cash ELSE cash-release_l END;
  movement:=movement||jsonb_build_object('transaction_refund_minor',CASE WHEN kind='Refund' THEN amount ELSE 0 END,
   'transaction_receivable_released_minor',CASE WHEN kind='Collection' THEN amount ELSE 0 END,
   'functional_receivable_released_minor',CASE WHEN kind='Collection' THEN release_l ELSE 0 END,
   'functional_refund_released_minor',CASE WHEN kind='Refund' THEN release_l ELSE 0 END,
   'functional_cash_minor',cash,'functional_fx_gain_minor',greatest(difference,0),'functional_fx_loss_minor',greatest(-difference,0),
   'functional_turnover_minor',greatest(cash,release_l));
  IF kind='Refund' THEN
   after_state:=before_state||jsonb_build_object('transaction_refund_due_minor',carrying_f-amount,'functional_refund_due_minor',carrying_l-release_l,
    'transaction_refunded_minor',(before_state->>'transaction_refunded_minor')::numeric+amount,
    'functional_refund_released_minor',(before_state->>'functional_refund_released_minor')::numeric+release_l);
  ELSE
   after_state:=before_state||jsonb_build_object('transaction_outstanding_minor',carrying_f-amount,'functional_outstanding_minor',carrying_l-release_l,
    'transaction_collected_minor',(before_state->>'transaction_collected_minor')::numeric+amount);
  END IF;
 END IF;
 FOR field IN SELECT jsonb_object_keys(movement) LOOP
  PERFORM reconforge.monetary_return_assert(reconforge.fx_minor(movement->field),'Every functional and transaction leg is a bounded exact nonnegative minor amount');
 END LOOP;
 FOR field IN SELECT native_field FROM jsonb_object_keys(after_state) native_field WHERE jsonb_typeof(after_state->native_field)='number' LOOP
  PERFORM reconforge.monetary_return_assert(reconforge.fx_minor(after_state->field),'Every remaining monetary state is a bounded exact nonnegative value');
 END LOOP;
 PERFORM reconforge.monetary_return_assert(((after_state->>'transaction_outstanding_minor')::bigint>0
  OR(after_state->>'functional_outstanding_minor')::bigint=0)
 AND((after_state->>'transaction_refund_due_minor')::bigint>0 OR(after_state->>'functional_refund_due_minor')::bigint=0),
 'Zero transaction carrying balances cannot hide functional residuals');
 RETURN jsonb_build_object('kind',kind,'sequence',sequence,'source_fingerprint',source_fp,'previous_history_fingerprint',chain,
 'posting_date',day,'quantity_scaled',quantity,'amount_minor',amount,'settlement_rate',rate,'original_sequence',original_sequence,
 'before',before_state,'after',after_state,'monetary',movement,'components',components,'portions',portions);
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_history(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE origin_owner RECORD;member RECORD;prefix JSONB:='[]';expected JSONB;source JSONB;chain TEXT;
BEGIN
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=i;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL
 AND reconforge.irp_scope(t,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id),
 'Complete visible Stock/FX monetary source ownership is required');
 source:=origin_owner.payload->'source';
 FOR member IN SELECT * FROM reconforge.customer_partial_return_monetary_history
  WHERE tenant_id=t AND origin_id=origin_owner.id ORDER BY sequence LOOP
  expected:=reconforge.monetary_return_next(source,prefix,member.kind,(member.payload->>'quantity_scaled')::bigint,
   (member.payload->>'amount_minor')::bigint,member.payload->>'posting_date',NULLIF(member.payload->'settlement_rate','null'::jsonb),member.original_sequence);
  PERFORM reconforge.monetary_return_assert(member.sequence=jsonb_array_length(prefix)+1 AND member.payload=expected
   AND member.previous_digest=expected->>'previous_history_fingerprint' AND member.event_digest=reconforge.irp_digest(expected)
   AND(member.workspace_id,member.organization_id,member.legal_entity_id)=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id),
   'Retained monetary history must independently reproduce every source, component, carrying and FIFO witness');
  prefix:=prefix||jsonb_build_array(expected);
 END LOOP;
 RETURN jsonb_build_object('source',source,'events',prefix);
END $mr149$;
"""

BALANCE_SQL = r"""
CREATE FUNCTION reconforge.monetary_stock_fx_state(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE origin_owner RECORD;native_plan RECORD;recognized BOOLEAN:=FALSE;active TEXT;next_sequence INTEGER:=0;last_day TEXT;
BEGIN
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=i;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL,'The exact native monetary origin is required');
 last_day:=origin_owner.payload#>>'{source,posting_date}';
 FOR native_plan IN SELECT * FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=origin_owner.fx_source_id ORDER BY sequence LOOP
  PERFORM reconforge.monetary_return_assert(native_plan.sequence=next_sequence AND(native_plan.sequence=0)=(native_plan.kind='recognize'),
   'The reused native FX lifecycle requires its exact contiguous recognition and operation order');
  IF native_plan.phase<2 THEN EXIT;END IF;
  IF native_plan.kind='recognize' THEN recognized:=TRUE;
  ELSIF native_plan.kind='revalue' THEN
   PERFORM reconforge.monetary_return_assert(active IS NULL,'Reverse the active closing valuation first');active:=native_plan.id;
  ELSIF native_plan.kind='reverse_revaluation' THEN
   PERFORM reconforge.monetary_return_assert(active=native_plan.payload#>>'{equation,original_revaluation_id}',
    'A closing inverse requires the exact still-active original native valuation');active:=NULL;
  END IF;
  last_day:=native_plan.payload->>'posting_date';next_sequence:=next_sequence+1;
 END LOOP;
 RETURN jsonb_build_object('recognized',recognized,'sequence',next_sequence,'last_posting_date',last_day,
  'active_revaluation_plan_id',active);
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_balance(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE origin_owner RECORD;history JSONB;position JSONB;source JSONB;version INTEGER;chain TEXT;pending TEXT;fx_state JSONB;
 fg NUMERIC;lg NUMERIC;collected NUMERIC;credited NUMERIC;refunded NUMERIC;released NUMERIC;due_f NUMERIC;due_l NUMERIC;
BEGIN
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=i;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL,'A monetary balance cannot infer absent original ownership');
 history:=reconforge.monetary_stock_history(t,i);source:=history->'source';version:=jsonb_array_length(history->'events');
 position:=CASE WHEN version=0 THEN reconforge.monetary_return_initial(source) ELSE history->'events'->(version-1)->'after' END;
 chain:=CASE WHEN version=0 THEN reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-monetary-original-v3',
  'source_fingerprint',reconforge.monetary_return_source_fingerprint(source),'allocation_policy','remaining-dual-currency-v1',
  'alignment_policy','historical-carrying-component-alignment-v1')) ELSE reconforge.irp_digest(history->'events'->(version-1)) END;
 SELECT sum((member->>'transaction_minor')::numeric),sum((member->>'functional_minor')::numeric) INTO fg,lg
  FROM jsonb_array_elements(source->'components') member;
 collected:=(position->>'transaction_collected_minor')::numeric;credited:=(position->>'transaction_credited_minor')::numeric;
 refunded:=(position->>'transaction_refunded_minor')::numeric;released:=(position->>'functional_refund_released_minor')::numeric;
 due_f:=(position->>'transaction_refund_due_minor')::numeric;due_l:=(position->>'functional_refund_due_minor')::numeric;
 PERFORM reconforge.monetary_return_assert(fg>0 AND lg>0 AND collected<=fg AND credited<=fg
 AND credited+collected-fg<=due_f+refunded AND greatest(credited+collected-fg,0)=due_f+refunded
 AND due_l+released<=lg AND(due_f+refunded>0 OR due_l+released=0) AND(refunded>0 OR released=0),
 'The active monetary prefix must conserve original gross, carrying and refund entitlements');
 SELECT min(pending_owner.id) INTO pending FROM(
  SELECT id FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=origin_owner.fx_source_id AND phase<2
  UNION ALL SELECT id FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND origin_id=origin_owner.id AND phase<2) pending_owner;
 PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM(
  SELECT id FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=origin_owner.fx_source_id AND phase<2
  UNION ALL SELECT id FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND origin_id=origin_owner.id AND phase<2) pending_owner)<=1,
  'Only one native FX or merchandise operation may be pending for the same monetary source');
 fx_state:=reconforge.monetary_stock_fx_state(t,i);
 RETURN jsonb_build_object('schema_version','stock-monetary-balance-v1','history_version',version,'history_fingerprint',chain,
  'transaction_original_gross_minor',fg::text,'functional_original_gross_minor',lg::text,
  'transaction_collected_minor',collected::text,'transaction_credited_minor',credited::text,
  'transaction_outstanding_minor',position->>'transaction_outstanding_minor','functional_outstanding_minor',
   CASE WHEN fx_state->>'active_revaluation_plan_id' IS NULL THEN position->>'functional_outstanding_minor'
    ELSE(SELECT payload#>>'{equation,valued_outstanding_minor}' FROM reconforge.operational_fx_plans
     WHERE tenant_id=t AND id=fx_state->>'active_revaluation_plan_id' AND phase=2 AND kind='revalue') END,
  'transaction_refund_entitlement_minor',(due_f+refunded)::text,'functional_refund_entitlement_minor',(due_l+released)::text,
  'transaction_refunded_minor',refunded::text,'functional_refund_released_minor',released::text,
  'transaction_refund_due_minor',due_f::text,'functional_refund_due_minor',due_l::text,
  'active_plan_id',pending,'active_revaluation_plan_id',fx_state->'active_revaluation_plan_id');
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_refresh_balance(t TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE origin_owner RECORD;invoice_owner RECORD;projection JSONB;recognized BOOLEAN;next_status TEXT;
BEGIN
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=i;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL,'Balance publication requires the exact owned source');
 projection:=reconforge.monetary_stock_balance(t,i);
 UPDATE reconforge.stock_sales_monetary_origins SET ar_balance=projection WHERE tenant_id=t AND id=origin_owner.id;
 recognized:=(reconforge.monetary_stock_fx_state(t,i)->>'recognized')::boolean;
 IF recognized THEN
  SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=t AND id=origin_owner.invoice_id;
  next_status:=CASE WHEN projection->>'transaction_outstanding_minor'='0' THEN'Paid'
   WHEN projection->>'transaction_collected_minor'='0' THEN'Approved' ELSE'PartiallyPaid' END;
  IF invoice_owner.status IS DISTINCT FROM next_status THEN
   UPDATE reconforge.ar_invoices SET status=next_status,row_version=row_version+1 WHERE tenant_id=t AND id=origin_owner.invoice_id;
  END IF;
 END IF;
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_invoice_balance(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $mr149$
DECLARE invoice_owner RECORD;origin_owner RECORD;projection JSONB;field TEXT;allocated NUMERIC;
 gf NUMERIC;gl NUMERIC;collected NUMERIC;credited NUMERIC;entitled_f NUMERIC;entitled_l NUMERIC;refunded NUMERIC;released NUMERIC;due_f NUMERIC;due_l NUMERIC;
BEGIN
 -- Only public AR columns and the safe immutable directory/projection columns
 -- are read here. No cost, private origin payload or financial history ACL is
 -- required by this function, and it takes no business locks.
 SELECT id,workspace_id,organization_id,legal_entity_id,total_minor,customer_partial_return_source_id INTO invoice_owner
  FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 PERFORM reconforge.monetary_return_assert(invoice_owner.id IS NOT NULL,'A visible actual native AR invoice is required');
 -- Legacy AR visibility can be tenant-wide. Establish the actual invoice's
 -- current full scope before origin RLS absence may classify it as unowned.
 -- A genuinely unscoped legacy invoice cannot be a new origin: the new
 -- directory requires all three non-null scope IDs and exact native affinity.
 PERFORM reconforge.monetary_return_assert(invoice_owner.organization_id IS NULL OR invoice_owner.legal_entity_id IS NULL
  OR reconforge.irp_scope(t,invoice_owner.workspace_id,invoice_owner.organization_id,invoice_owner.legal_entity_id),
  'A visible invoice outside the current full child scope cannot fall back to legacy monetary economics');
 SELECT id,workspace_id,organization_id,legal_entity_id,invoice_id,ar_balance INTO origin_owner
  FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND invoice_id=i;
 IF origin_owner.id IS NULL THEN RETURN NULL;END IF;
 PERFORM reconforge.monetary_return_assert((origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
  IS NOT DISTINCT FROM(invoice_owner.workspace_id,invoice_owner.organization_id,invoice_owner.legal_entity_id)
  AND invoice_owner.customer_partial_return_source_id IS NULL AND reconforge.irp_scope(t,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id),
  'An invoice must have one complete visible monetary owner without legacy partial ownership');
 projection:=origin_owner.ar_balance;
 PERFORM reconforge.monetary_return_assert(reconforge.fx_object(projection,ARRAY['schema_version','history_version','history_fingerprint',
  'transaction_original_gross_minor','functional_original_gross_minor','transaction_collected_minor','transaction_credited_minor',
  'transaction_outstanding_minor','functional_outstanding_minor','transaction_refund_entitlement_minor','functional_refund_entitlement_minor',
  'transaction_refunded_minor','functional_refund_released_minor','transaction_refund_due_minor','functional_refund_due_minor',
  'active_plan_id','active_revaluation_plan_id']) AND projection->>'schema_version'='stock-monetary-balance-v1'
  AND reconforge.fx_minor(projection->'history_version') AND(projection->>'history_version')::integer BETWEEN 0 AND 256
  AND projection->>'history_fingerprint'~'^[a-f0-9]{64}$','The monetary AR read projection requires its exact finite native schema');
 FOREACH field IN ARRAY ARRAY['transaction_original_gross_minor','functional_original_gross_minor','transaction_collected_minor','transaction_credited_minor',
  'transaction_outstanding_minor','functional_outstanding_minor','transaction_refund_entitlement_minor','functional_refund_entitlement_minor',
  'transaction_refunded_minor','functional_refund_released_minor','transaction_refund_due_minor','functional_refund_due_minor'] LOOP
  PERFORM reconforge.monetary_return_assert(jsonb_typeof(projection->field)='string' AND projection->>field~'^(0|[1-9][0-9]*)$'
   AND(projection->>field)::numeric BETWEEN 0 AND 9000000000000000000,'Public monetary minor units require exact bounded canonical strings');
 END LOOP;
 FOREACH field IN ARRAY ARRAY['active_plan_id','active_revaluation_plan_id'] LOOP
  PERFORM reconforge.monetary_return_assert(projection->field='null'::jsonb OR(jsonb_typeof(projection->field)='string'
   AND projection->>field~(CASE WHEN field='active_revaluation_plan_id' THEN'^FX1-[a-f0-9]{32}$' ELSE'^(FX1|CR3|CRF3|CR3R|CRF3R)-[a-f0-9]{32}$' END)),
   'Pending and active-closing identities require their exact native namespaces');
 END LOOP;
 gf:=(projection->>'transaction_original_gross_minor')::numeric;gl:=(projection->>'functional_original_gross_minor')::numeric;
 collected:=(projection->>'transaction_collected_minor')::numeric;credited:=(projection->>'transaction_credited_minor')::numeric;
 entitled_f:=(projection->>'transaction_refund_entitlement_minor')::numeric;entitled_l:=(projection->>'functional_refund_entitlement_minor')::numeric;
 refunded:=(projection->>'transaction_refunded_minor')::numeric;released:=(projection->>'functional_refund_released_minor')::numeric;
 due_f:=(projection->>'transaction_refund_due_minor')::numeric;due_l:=(projection->>'functional_refund_due_minor')::numeric;
 SELECT COALESCE(sum(amount_minor),0) INTO allocated FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=i;
 PERFORM reconforge.monetary_return_assert(gf=invoice_owner.total_minor AND gf>0 AND gl>0 AND collected=allocated AND collected<=gf AND credited<=gf
  AND(projection->>'transaction_outstanding_minor')::numeric=greatest(gf-collected-credited,0)
  AND entitled_f=greatest(collected+credited-gf,0) AND entitled_l<=gl AND refunded<=entitled_f AND released<=entitled_l
  AND due_f=entitled_f-refunded AND due_l=entitled_l-released AND(entitled_f>0 OR entitled_l=0) AND(refunded>0 OR released=0)
  AND((projection->>'transaction_outstanding_minor')::numeric>0 OR(projection->>'functional_outstanding_minor')::numeric=0)
  AND(due_f>0 OR due_l=0),'The public monetary read model must match actual AR cash and conserve both captured currencies');
 RETURN projection;
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_invoice_credit(t TEXT,i TEXT) RETURNS NUMERIC
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $mr149$
DECLARE projection JSONB;
BEGIN
 projection:=reconforge.monetary_stock_invoice_balance(t,i);
 IF projection IS NULL THEN RETURN 0::numeric;END IF;
 RETURN(projection->>'transaction_credited_minor')::numeric;
END $mr149$;
"""

POSTING_SQL = r"""
CREATE FUNCTION reconforge.monetary_return_line(account TEXT,debit NUMERIC,credit NUMERIC,dimensions JSONB) RETURNS JSONB
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $mr149$
BEGIN
 PERFORM reconforge.monetary_return_assert(account IS NOT NULL AND reconforge.fx_minor(to_jsonb(debit))
  AND reconforge.fx_minor(to_jsonb(credit)) AND NOT(debit>0 AND credit>0) AND jsonb_typeof(dimensions)='object',
  'Every native original accounting role requires its exact amount and explicit dimension set');
 IF debit=0 AND credit=0 THEN RETURN'[]'::jsonb;END IF;
 RETURN jsonb_build_array(jsonb_build_object('account_id',account,'debit_minor',debit,'credit_minor',credit,'dimensions',dimensions));
END $mr149$;
CREATE FUNCTION reconforge.monetary_return_journals(origin JSONB,event JSONB) RETURNS JSONB
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $mr149$
DECLARE result JSONB:='[]';lines JSONB:='[]';movement JSONB:=event->'monetary';roles JSONB:=origin->'roles';
 component JSONB;account TEXT;turnover NUMERIC:=0;
BEGIN
 PERFORM reconforge.monetary_return_assert(event->>'kind' IN('Return','Refund'),
  'Inverse journals must retain their actual original native posting effects');
 IF event->>'kind'='Return' THEN
  FOR component IN SELECT member.value FROM jsonb_array_elements(event->'components') WITH ORDINALITY member(value,ordinal) ORDER BY member.ordinal LOOP
   account:=origin->'source'->'components'->((component->>'position')::integer)->>'account_id';
   lines:=lines||reconforge.monetary_return_line(account,(component->>'functional_minor')::numeric,0,origin->'dimensions'->account);
  END LOOP;
  account:=roles->>'loss_account_id';lines:=lines||reconforge.monetary_return_line(account,(movement->>'functional_alignment_loss_minor')::numeric,0,origin->'dimensions'->account);
  account:=roles->>'receivable_account_id';lines:=lines||reconforge.monetary_return_line(account,0,(movement->>'functional_receivable_released_minor')::numeric,origin->'dimensions'->account);
  account:=roles->>'refund_liability_account_id';lines:=lines||reconforge.monetary_return_line(account,0,(movement->>'functional_refund_delta_minor')::numeric,origin->'dimensions'->account);
  account:=roles->>'gain_account_id';lines:=lines||reconforge.monetary_return_line(account,0,(movement->>'functional_alignment_gain_minor')::numeric,origin->'dimensions'->account);
  IF jsonb_array_length(lines)>0 THEN result:=result||jsonb_build_array(jsonb_build_object('purpose','MerchandiseCredit','lines',lines));END IF;
  account:=roles->>'inventory_account_id';lines:=reconforge.monetary_return_line(account,(movement->>'functional_cost_minor')::numeric,0,origin->'dimensions'->account);
  account:=roles->>'cogs_account_id';lines:=lines||reconforge.monetary_return_line(account,0,(movement->>'functional_cost_minor')::numeric,origin->'dimensions'->account);
  IF jsonb_array_length(lines)>0 THEN result:=result||jsonb_build_array(jsonb_build_object('purpose','CostRestoration','lines',lines));END IF;
 ELSE
  account:=roles->>'refund_liability_account_id';lines:=reconforge.monetary_return_line(account,(movement->>'functional_refund_released_minor')::numeric,0,origin->'dimensions'->account);
  account:=roles->>'loss_account_id';lines:=lines||reconforge.monetary_return_line(account,(movement->>'functional_fx_loss_minor')::numeric,0,origin->'dimensions'->account);
  account:=roles->>'cash_account_id';lines:=lines||reconforge.monetary_return_line(account,0,(movement->>'functional_cash_minor')::numeric,origin->'dimensions'->account);
  account:=roles->>'gain_account_id';lines:=lines||reconforge.monetary_return_line(account,0,(movement->>'functional_fx_gain_minor')::numeric,origin->'dimensions'->account);
  IF jsonb_array_length(lines)>0 THEN result:=jsonb_build_array(jsonb_build_object('purpose','Refund','lines',lines));END IF;
 END IF;
 FOR component IN SELECT value FROM jsonb_array_elements(result) LOOP
  PERFORM reconforge.monetary_return_assert((SELECT sum((line->>'debit_minor')::numeric-(line->>'credit_minor')::numeric)
   FROM jsonb_array_elements(component->'lines') line)=0,'Original-component correction journal must be independently balanced');
  turnover:=turnover+(SELECT sum((line->>'debit_minor')::numeric) FROM jsonb_array_elements(component->'lines') line);
 END LOOP;
 PERFORM reconforge.monetary_return_assert(turnover=(movement->>'functional_turnover_minor')::numeric,
  'Exact nonzero journal membership must preserve the complete governed functional turnover');
 RETURN result;
END $mr149$;
CREATE FUNCTION reconforge.monetary_partial_entry_close(t TEXT,i TEXT,purpose TEXT,expected JSONB) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;origin_owner RECORD;member RECORD;entry_owner RECORD;effect_owner RECORD;reviewer TEXT;poster TEXT;
 snapshot JSONB;part JSONB;number TEXT;slot TEXT;native_id TEXT;ordinal INTEGER:=0;actual_lines JSONB;original_member RECORD;
BEGIN
 SELECT * INTO plan_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND id=plan_owner.origin_id;
 SELECT * INTO member FROM reconforge.customer_partial_return_monetary_entries
  WHERE tenant_id=t AND plan_id=i AND customer_partial_return_monetary_entries.purpose=$3;
 PERFORM reconforge.monetary_return_assert(plan_owner.id IS NOT NULL AND origin_owner.id IS NOT NULL AND member.entry_id IS NOT NULL,
  'Every nonzero monetary journal requires its complete same-scope native owner');
 slot:=CASE purpose WHEN'MerchandiseCredit' THEN'R' WHEN'ReverseMerchandiseCredit' THEN'R'
  WHEN'CostRestoration' THEN'C' WHEN'ReverseCostRestoration' THEN'C' WHEN'Refund' THEN'F' WHEN'ReverseRefund' THEN'F' END;
 number:=upper(i)||'-'||slot;
 native_id:='GLE-'||left(encode(sha256(convert_to(origin_owner.workspace_id||'|'||number,'UTF8')),'hex'),16);
 SELECT * INTO entry_owner FROM reconforge.finance_entries WHERE tenant_id=t AND id=member.entry_id;
 IF plan_owner.phase=2 THEN
  snapshot:=reconforge.monetary_posted_close(t,member.entry_id,member.posting_effect_id,origin_owner.organization_id,origin_owner.legal_entity_id);
 ELSE snapshot:=reconforge.fr_snapshot(t,member.entry_id,origin_owner.organization_id,origin_owner.legal_entity_id);END IF;
 SELECT actor_id INTO reviewer FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT actor_id INTO poster FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 PERFORM reconforge.monetary_return_assert(slot IS NOT NULL AND member.entry_id=native_id AND entry_owner.id=native_id
  AND entry_owner.entry_number=number AND member.snapshot=snapshot
  AND member.validation_digest=(CASE WHEN plan_owner.phase=2 THEN entry_owner.validation_digest ELSE reconforge.irp_digest(snapshot) END)
  AND member.validation_digest=(SELECT item.value->>'validation_digest' FROM jsonb_array_elements(plan_owner.payload->'entries') item(value)
   WHERE item.value->>'purpose'=$3)
  AND(entry_owner.workspace_id,entry_owner.period_id,entry_owner.posting_date,entry_owner.journal_id)
   =(origin_owner.workspace_id,plan_owner.payload->>'period_id',plan_owner.payload->>'posting_date',origin_owner.payload->>'journal_id')
  AND entry_owner.preparer_actor_id=plan_owner.payload->>'preparer_actor_id'
  AND reconforge.fx_policy(t,origin_owner.payload->'functional_policy')
  AND(entry_owner.currency_code,entry_owner.currency_precision,entry_owner.currency_rounding_policy,entry_owner.currency_registry_version,entry_owner.currency_registry_digest)
   =(origin_owner.payload#>>'{functional_policy,currency_code}',(origin_owner.payload#>>'{functional_policy,currency_precision}')::integer,
    origin_owner.payload#>>'{functional_policy,currency_rounding_policy}',origin_owner.payload#>>'{functional_policy,currency_registry_version}',
    origin_owner.payload#>>'{functional_policy,currency_registry_digest}')
  AND entry_owner.status=(CASE plan_owner.phase WHEN 0 THEN'Draft' WHEN 3 THEN'Voided' ELSE'Validated' END),
  'Native correction number, identity, scope, reviewed snapshot, policy and lifecycle must remain exact');
 IF plan_owner.operation LIKE'Reverse%' THEN
  SELECT * INTO original_member FROM reconforge.customer_partial_return_monetary_entries original
   WHERE original.tenant_id=t AND original.plan_id=plan_owner.original_id AND original.purpose=substring($3 FROM 8);
  PERFORM reconforge.monetary_return_assert(original_member.posting_effect_id IS NOT NULL
   AND member.original_effect_id=original_member.posting_effect_id AND entry_owner.reverses_posting_id=original_member.posting_effect_id
   AND entry_owner.external_reference=original_member.posting_effect_id AND entry_owner.source_type='Generated',
   'An inverse must retain its exact same-source original journal effect and purpose');
 ELSE
  PERFORM reconforge.monetary_return_assert(member.original_effect_id IS NULL AND entry_owner.reverses_posting_id IS NULL
   AND entry_owner.external_reference=i AND entry_owner.source_type='Manual','Forward corrections cannot masquerade as generic original-sale inverses');
 END IF;
 actual_lines:=snapshot->'lines';
 PERFORM reconforge.monetary_return_assert(jsonb_array_length(actual_lines)=jsonb_array_length(expected),
  'The complete nonzero correction line membership must equal the original-account template');
 FOR part IN SELECT value FROM jsonb_array_elements(expected) LOOP
  ordinal:=ordinal+1;
  PERFORM reconforge.monetary_return_assert(actual_lines->(ordinal-1)->>'line_number'=ordinal::text
   AND((actual_lines->(ordinal-1))-ARRAY['line_number','description'])=part,
   'Native correction lines require exact ordered original accounts, dimensions and monetary magnitudes');
 END LOOP;
 IF plan_owner.phase IN(1,2) THEN
  PERFORM reconforge.monetary_return_assert(reviewer IS NOT NULL AND reviewer<>entry_owner.preparer_actor_id
   AND entry_owner.validator_actor_id=reviewer AND entry_owner.validation_digest=member.validation_digest,
   'The native journal must retain its exact independent current-owner review');
 END IF;
 IF plan_owner.phase<>2 THEN
  PERFORM reconforge.monetary_return_assert(member.posting_effect_id IS NULL
   AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects effect WHERE effect.tenant_id=t AND effect.entry_id=member.entry_id),
   'Unposted or cancelled correction plans cannot have financial effects');
 ELSE
  SELECT * INTO effect_owner FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=member.posting_effect_id;
  PERFORM reconforge.monetary_return_assert(effect_owner.id IS NOT NULL AND effect_owner.entry_id=member.entry_id
   AND effect_owner.snapshot_json=snapshot AND effect_owner.validation_digest=member.validation_digest
   AND effect_owner.posted_actor_id=poster AND poster<>reviewer AND poster<>entry_owner.preparer_actor_id
   AND effect_owner.source_id=COALESCE(entry_owner.reverses_posting_id,entry_owner.id) AND effect_owner.purpose='operational_posting'
   AND effect_owner.source_kind=(CASE WHEN member.original_effect_id IS NULL THEN'Manual' ELSE'Reversal' END)
   AND effect_owner.validation_contract_version='finance-entry-review-v1' AND entry_owner.validation_contract_version='finance-entry-review-v1'
   AND(effect_owner.workspace_id,effect_owner.organization_id,effect_owner.legal_entity_id)=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
   AND effect_owner.reverses_effect_id IS NOT DISTINCT FROM member.original_effect_id
   AND(effect_owner.currency_code,effect_owner.currency_precision,effect_owner.currency_rounding_policy,effect_owner.currency_registry_version,effect_owner.currency_registry_digest)
    =(entry_owner.currency_code,entry_owner.currency_precision,entry_owner.currency_rounding_policy,entry_owner.currency_registry_version,entry_owner.currency_registry_digest),
   'Posted correction effects require exact seals, all three humans and original inverse affinity');
  PERFORM reconforge.monetary_return_assert(NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse
   WHERE inverse.tenant_id=t AND inverse.reverses_effect_id=effect_owner.id AND NOT EXISTS(
    SELECT 1 FROM reconforge.customer_partial_return_monetary_entries inverse_member
    JOIN reconforge.customer_partial_return_monetary_plans inverse_plan ON(inverse_plan.tenant_id,inverse_plan.id)=(inverse_member.tenant_id,inverse_member.plan_id)
    WHERE inverse_member.tenant_id=t AND inverse_member.posting_effect_id=inverse.id AND inverse_member.original_effect_id=effect_owner.id
    AND inverse_plan.origin_id=plan_owner.origin_id AND inverse_plan.original_id=i AND inverse_plan.phase=2
    AND inverse_plan.operation='Reverse'||plan_owner.operation AND inverse_member.purpose='Reverse'||$3)),
   'Generic inverse posting cannot bypass the exact governed monetary correction owner');
 END IF;
END $mr149$;
"""

ORIGIN_SQL = r"""
CREATE FUNCTION reconforge.monetary_stock_origin_birth(t TEXT,stock_id TEXT,fx_id TEXT,recognition_id TEXT,declared JSONB) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE stock_owner RECORD;fx_source RECORD;recognition RECORD;invoice_owner RECORD;journal_owner RECORD;account_owner RECORD;
 allocation JSONB;consumed RECORD;line_owner RECORD;cost_snapshot JSONB;recognition_snapshot JSONB;registry JSONB;equation JSONB;
 roles JSONB:='{}';dimensions JSONB:='{}';components JSONB:='[]';consumptions JSONB:='[]';evidence JSONB;source JSONB;payload JSONB;
 policy JSONB;part JSONB;code TEXT;kind TEXT;field TEXT;account_id TEXT;origin_id TEXT;position INTEGER:=0;total_q NUMERIC:=0;total_v NUMERIC:=0;
 fg NUMERIC;lg NUMERIC;balance JSONB;cost_admission TEXT;actor TEXT:=current_setting('app.stock_sales_actor_id',true);
BEGIN
 SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=stock_id;
 SELECT * INTO fx_source FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=fx_id;
 SELECT * INTO recognition FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=recognition_id;
 SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=t AND id=fx_source.invoice_id;
 PERFORM reconforge.monetary_return_assert(stock_owner.id IS NOT NULL AND fx_source.id IS NOT NULL AND recognition.id IS NOT NULL
  AND reconforge.fx_object(declared,ARRAY['refund_liability_account_code']) AND stock_owner.status='Delivered'
  AND stock_owner.invoice_id IS NULL AND stock_owner.invoice_plan_id IS NULL
  AND recognition.source_id=fx_id AND recognition.kind='recognize' AND recognition.sequence=0 AND recognition.phase=0
  AND actor IS NOT NULL AND actor=fx_source.payload->>'preparer_actor_id'
  AND actor=recognition.payload->>'preparer_actor_id'
  AND reconforge.sales_revenue_actor(t,actor,'sales.manage') AND reconforge.sales_revenue_actor(t,actor,'receivables.manage')
  AND reconforge.sales_revenue_actor(t,actor,'finance_core.manage')
  AND NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t
   AND(stock_order_id=stock_id OR invoice_id=fx_source.invoice_id OR fx_source_id=fx_id OR recognition_plan_id=recognition_id))
  AND invoice_owner.customer_partial_return_source_id IS NULL,
  'Monetary origin birth must atomically own a new fixed Stock invoice before review without retrofit or competing ownership');
 equation:=reconforge.monetary_fx_original_equation(t,fx_id);
 recognition_snapshot:=recognition.payload->'snapshot';
 PERFORM reconforge.monetary_return_assert(recognition.entry_id IS NOT NULL
  AND recognition_snapshot=reconforge.fr_snapshot(t,recognition.entry_id,stock_owner.organization_id,stock_owner.legal_entity_id)
  AND recognition.payload->>'validation_digest'=reconforge.irp_digest(recognition_snapshot)
  AND recognition.payload->>'plan_digest'=reconforge.irp_digest(recognition.payload-ARRAY['plan_digest','validation_digest'])
  AND recognition.payload->>'source_digest'=fx_source.payload->>'source_digest'
  AND recognition.payload->'equation'=jsonb_build_object('lines',equation->'lines'),
  'Original monetary recognition must retain the actual native reviewed snapshot and exact existing FX invoice equation');
 SELECT * INTO journal_owner FROM reconforge.finance_journals WHERE tenant_id=t AND id=recognition_snapshot#>>'{entry,journal_id}';
 PERFORM reconforge.monetary_return_assert(journal_owner.id IS NOT NULL AND journal_owner.workspace_id=stock_owner.workspace_id,
  'The original recognition journal must belong to the exact native source workspace');
 FOREACH field IN ARRAY ARRAY['receivable','revenue','cash','gain','loss','refund_liability'] LOOP
  code:=CASE WHEN field='refund_liability' THEN declared->>'refund_liability_account_code'
   ELSE equation->'request'->>(field||'_account_code') END;
  kind:=CASE WHEN field IN('receivable','cash') THEN'Asset' WHEN field IN('revenue','gain') THEN'Income'
   WHEN field='loss' THEN'Expense' ELSE'Liability' END;
  SELECT * INTO account_owner FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=stock_owner.workspace_id
   AND chart_id=journal_owner.chart_id AND account_code=code AND account_type=kind AND active AND allow_posting AND allow_manual_posting;
  PERFORM reconforge.monetary_return_assert(account_owner.id IS NOT NULL,'Every declared original monetary account role requires its current native classification');
  roles:=roles||jsonb_build_object(field||'_account_id',account_owner.id);
  dimensions:=dimensions||jsonb_build_object(account_owner.id,'{}'::jsonb);
 END LOOP;
 PERFORM reconforge.monetary_return_assert((SELECT count(DISTINCT value) FROM jsonb_each_text(roles))=6,
  'Original monetary roles must be distinct and cannot be caller-forged account substitutions');
 FOREACH field IN ARRAY ARRAY['inventory','cogs'] LOOP
  account_id:=stock_owner.issue_plan->>(field||'_account_id');
  SELECT * INTO account_owner FROM reconforge.finance_accounts WHERE tenant_id=t AND id=account_id AND workspace_id=stock_owner.workspace_id
   AND account_type=(CASE WHEN field='inventory' THEN'Asset' ELSE'Expense' END);
  PERFORM reconforge.monetary_return_assert(account_owner.id IS NOT NULL,'Original FIFO accounting roles must bind the actual reviewed Stock issue');
  roles:=roles||jsonb_build_object(field||'_account_id',account_id);
  dimensions:=dimensions||jsonb_build_object(account_id,'{}'::jsonb);
 END LOOP;
 PERFORM reconforge.monetary_return_assert((SELECT count(DISTINCT value) FROM jsonb_each_text(roles))=8,
  'The new monetary origin keeps FIFO, cash, receivable, revenue, refund and FX roles distinct without merging their original dimensions');
 IF stock_owner.cogs_entry_id IS NOT NULL THEN
  cost_snapshot:=reconforge.fr_snapshot(t,stock_owner.cogs_entry_id,stock_owner.organization_id,stock_owner.legal_entity_id);
  FOR part IN SELECT value FROM jsonb_array_elements(cost_snapshot->'lines') LOOP
   dimensions:=dimensions||jsonb_build_object(part->>'account_id',part->'dimensions');
  END LOOP;
 ELSE
  PERFORM reconforge.monetary_return_assert(stock_owner.cogs_effect_id IS NULL
   AND stock_owner.issue_plan->>'cost_admission_policy'='partial-return-restituted-v1'
   AND stock_owner.issue_plan->'total_cost_minor'='0'::jsonb,'Absent original COGS requires explicit native restituted-cost admission');
 END IF;
 components:=jsonb_build_array(jsonb_build_object('position',0,'kind','Net','account_id',roles->>'revenue_account_id',
  'transaction_minor',equation->'foreign_net_minor','functional_minor',equation->'functional_net_minor',
  'policy_digest',reconforge.irp_digest(jsonb_build_object('stock_source_digest',stock_owner.source_digest,'discount_policy',stock_owner.source->'discount_policy'))));
 FOR part IN SELECT value FROM jsonb_array_elements(equation->'tax_components') LOOP
  position:=position+1;
  SELECT id INTO account_id FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=stock_owner.workspace_id
   AND chart_id=journal_owner.chart_id AND account_code=part->>'account_code' AND account_type='Liability';
  PERFORM reconforge.monetary_return_assert(account_id IS NOT NULL
   AND NOT EXISTS(SELECT 1 FROM jsonb_each_text(roles) role WHERE role.value=account_id),
   'Original tax components require their exact native liability account, distinct from economic roles');
  components:=components||jsonb_build_array(jsonb_build_object('position',position,'kind','Tax','account_id',account_id,
   'transaction_minor',part->'foreign_tax_minor','functional_minor',part->'functional_tax_minor','policy_digest',part->>'policy_digest'));
  dimensions:=dimensions||jsonb_build_object(account_id,'{}'::jsonb);
 END LOOP;
 position:=0;
 FOR allocation IN SELECT selected.value FROM jsonb_array_elements(stock_owner.issue_plan->'allocations') WITH ORDINALITY selected(value,ordinal) ORDER BY selected.ordinal LOOP
  position:=position+1;
  SELECT consumed_row.* INTO consumed FROM reconforge.inventory_layer_consumptions consumed_row
   JOIN reconforge.inventory_valuation_lines valuation_line ON(valuation_line.tenant_id,valuation_line.id)=(consumed_row.tenant_id,consumed_row.valuation_line_id)
   WHERE consumed_row.tenant_id=t AND valuation_line.valuation_document_id=stock_owner.valuation_id
   AND consumed_row.cost_layer_id=allocation->>'cost_layer_id'
   AND consumed_row.quantity_scaled=(allocation->>'quantity_scaled')::bigint AND consumed_row.value_minor=(allocation->>'value_minor')::bigint;
  PERFORM reconforge.monetary_return_assert(position<=32 AND consumed.id IS NOT NULL,
   'Every immutable original FIFO slice must bind its actual native consumption in reviewed issue order');
  consumptions:=consumptions||jsonb_build_array(jsonb_build_object('position',position,'original_consumption_id',consumed.id,
   'original_valuation_line_id',consumed.valuation_line_id,'cost_layer_id',consumed.cost_layer_id,
   'quantity_scaled',consumed.quantity_scaled,'value_minor',consumed.value_minor));
  total_q:=total_q+consumed.quantity_scaled;total_v:=total_v+consumed.value_minor;
 END LOOP;
 PERFORM reconforge.monetary_return_assert(position>0 AND total_q=stock_owner.quantity_scaled
  AND total_v=(stock_owner.issue_plan->>'total_cost_minor')::numeric
  AND(SELECT count(*) FROM reconforge.inventory_layer_consumptions consumed_row JOIN reconforge.inventory_valuation_lines valuation_line
    ON(valuation_line.tenant_id,valuation_line.id)=(consumed_row.tenant_id,consumed_row.valuation_line_id)
    WHERE consumed_row.tenant_id=t AND valuation_line.valuation_document_id=stock_owner.valuation_id)=position,
  'Original quantity, COGS and exact native consumption membership must be conserved');
 SELECT snapshot_json::jsonb INTO registry FROM reconforge.currency_registry_snapshots WHERE tenant_id=t
  AND registry_digest=equation#>>'{foreign_policy,currency_registry_digest}';
 PERFORM reconforge.monetary_return_assert(registry IS NOT NULL AND registry->>'digest'=equation#>>'{functional_policy,currency_registry_digest}',
  'Both original currencies require the same preserved verified registry context');
 SELECT * INTO line_owner FROM reconforge.ar_invoice_lines WHERE tenant_id=t AND invoice_id=invoice_owner.id;
 evidence:=jsonb_build_object('stock_order_id',stock_owner.id,'stock_source',stock_owner.source,'stock_source_digest',stock_owner.source_digest,
  'issue_plan',stock_owner.issue_plan,'movement_id',stock_owner.movement_id,'valuation_id',stock_owner.valuation_id,
  'cogs_entry_id',stock_owner.cogs_entry_id,'cogs_effect_id',stock_owner.cogs_effect_id,'cogs_snapshot',cost_snapshot,
  'fx_source',fx_source.payload,'recognition_plan_id',recognition.id,'recognition_snapshot',recognition_snapshot,
  'invoice_id',invoice_owner.id,'invoice_original',jsonb_build_object('customer_id',invoice_owner.customer_id,
   'currency_code',invoice_owner.currency_code,'invoice_number',invoice_owner.invoice_number,
   'invoice_date',invoice_owner.invoice_date::text,'due_date',invoice_owner.due_date::text,
   'subtotal_minor',invoice_owner.subtotal_minor,'tax_minor',invoice_owner.tax_minor,'total_minor',invoice_owner.total_minor),
  'invoice_line',jsonb_build_object('id',line_owner.id,'invoice_id',line_owner.invoice_id,'line_number',line_owner.line_number,
   'quantity_text',line_owner.quantity_text,'quantity_native_text',line_owner.quantity::text,'unit_price_minor',line_owner.unit_price_minor,
   'line_total_minor',line_owner.line_total_minor,'tax_minor',line_owner.tax_minor,'description',line_owner.description),
  'consumptions',consumptions,'roles',roles,'dimensions',dimensions);
 origin_id:='MSO-'||left(reconforge.irp_digest(jsonb_build_array(stock_owner.workspace_id,stock_id)),32);
 cost_admission:=CASE WHEN stock_owner.issue_plan ?'cost_admission_policy' THEN reconforge.irp_digest(stock_owner.issue_plan) ELSE NULL END;
 source:=jsonb_build_object('source_id',origin_id,'source_order_id',stock_id,'invoice_id',invoice_owner.id,
  'posting_date',equation#>>'{request,posting_date}','native_origin_digest',reconforge.irp_digest(evidence),
  'quantity_scaled',stock_owner.quantity_scaled,'quantity_precision',stock_owner.quantity_precision,
  'transaction_policy',stock_owner.source->'monetary_policy','functional_policy',stock_owner.source->'functional_policy',
  'registry_snapshot',registry,'components',components,'consumptions',consumptions,'original_cost_admission_digest',cost_admission,
  'allocation_policy','remaining-dual-currency-v1','alignment_policy','historical-carrying-component-alignment-v1');
 payload:=jsonb_build_object('evidence',evidence,'source',source,'equation',equation,'roles',roles,'dimensions',dimensions,
  'journal_id',journal_owner.id,'functional_policy',equation->'functional_policy','refund_liability_account_code',declared->>'refund_liability_account_code');
 fg:=(equation->>'foreign_gross_minor')::numeric;lg:=(equation->>'functional_gross_minor')::numeric;
 balance:=jsonb_build_object('schema_version','stock-monetary-balance-v1','history_version',0,
  'history_fingerprint',reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-monetary-original-v3',
   'source_fingerprint',reconforge.monetary_return_source_fingerprint(source),'allocation_policy','remaining-dual-currency-v1',
   'alignment_policy','historical-carrying-component-alignment-v1')),
  'transaction_original_gross_minor',fg::text,'functional_original_gross_minor',lg::text,'transaction_collected_minor','0','transaction_credited_minor','0',
  'transaction_outstanding_minor',fg::text,'functional_outstanding_minor',lg::text,'transaction_refund_entitlement_minor','0',
  'functional_refund_entitlement_minor','0','transaction_refunded_minor','0','functional_refund_released_minor','0',
  'transaction_refund_due_minor','0','functional_refund_due_minor','0','active_plan_id',recognition_id,'active_revaluation_plan_id',NULL);
 INSERT INTO reconforge.stock_sales_monetary_origins(tenant_id,id,workspace_id,organization_id,legal_entity_id,stock_order_id,invoice_id,
  fx_source_id,recognition_plan_id,payload,source_digest,ar_balance)
  VALUES(t,origin_id,stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id,stock_id,invoice_owner.id,fx_id,
   recognition_id,payload,reconforge.irp_digest(payload),balance);
END $mr149$;
"""


def _origin_functions(template: str) -> str:
    """Use the identical row assembler at birth and historical reclosure."""
    assembler = _replace_once(template,
        "monetary_stock_origin_birth(t TEXT,stock_id TEXT,fx_id TEXT,recognition_id TEXT,declared JSONB) RETURNS VOID",
        "monetary_stock_origin_payload(t TEXT,stock_id TEXT,fx_id TEXT,recognition_id TEXT,declared JSONB,birth BOOLEAN) RETURNS JSONB")
    first = assembler.index(" PERFORM reconforge.monetary_return_assert(stock_owner.id")
    last = assembler.index(" equation:=reconforge.monetary_fx_original_equation", first)
    birth_assertion = r"""
 PERFORM reconforge.monetary_return_assert(stock_owner.id IS NOT NULL AND fx_source.id IS NOT NULL AND recognition.id IS NOT NULL
  AND reconforge.fx_object(declared,ARRAY['refund_liability_account_code'])
  AND stock_owner.source->>'schema_version'='stock-sales-monetary-order-v2'
  AND recognition.source_id=fx_id AND recognition.kind='recognize' AND recognition.sequence=0
  AND invoice_owner.customer_partial_return_source_id IS NULL
  AND reconforge.irp_scope(t,stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id),
  'The immutable monetary origin must bind the exact visible Stock, original invoice and native recognition');
 IF birth THEN
  PERFORM reconforge.monetary_return_assert(stock_owner.status='Delivered' AND stock_owner.invoice_id IS NULL
   AND stock_owner.invoice_plan_id IS NULL AND recognition.phase=0 AND actor IS NOT NULL
   AND actor=fx_source.payload->>'preparer_actor_id' AND actor=recognition.payload->>'preparer_actor_id'
   AND reconforge.sales_revenue_actor(t,actor,'sales.manage') AND reconforge.sales_revenue_actor(t,actor,'receivables.manage')
   AND reconforge.sales_revenue_actor(t,actor,'finance_core.manage')
   AND NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_monetary_origins existing WHERE existing.tenant_id=t
    AND(existing.stock_order_id=stock_id OR existing.invoice_id=fx_source.invoice_id OR existing.fx_source_id=fx_id OR existing.recognition_plan_id=recognition_id)),
   'Only the current native maker may atomically create a monetary origin before invoice review; legacy retrofit is forbidden');
 END IF;
"""
    assembler = "".join((assembler[:first], birth_assertion, assembler[last:]))
    assembler = _replace_once(assembler,
        "AND chart_id=journal_owner.chart_id AND account_code=code AND account_type=kind AND active AND allow_posting AND allow_manual_posting;",
        "AND chart_id=journal_owner.chart_id AND account_code=code AND account_type=kind AND(NOT birth OR(active AND allow_posting AND allow_manual_posting));")
    stop = assembler.index(" fg:=(equation->>'foreign_gross_minor')")
    assembler = assembler[:stop] + " RETURN payload;\nEND $mr149$;\n"
    wrapper = r"""
CREATE FUNCTION reconforge.monetary_stock_origin_birth(t TEXT,stock_id TEXT,fx_id TEXT,recognition_id TEXT,declared JSONB) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE payload JSONB;balance JSONB;source JSONB;fg NUMERIC;lg NUMERIC;stock_owner RECORD;origin_id TEXT;
BEGIN
 payload:=reconforge.monetary_stock_origin_payload(t,stock_id,fx_id,recognition_id,declared,TRUE);source:=payload->'source';
 SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=stock_id;
 origin_id:=source->>'source_id';
 fg:=(payload#>>'{equation,foreign_gross_minor}')::numeric;lg:=(payload#>>'{equation,functional_gross_minor}')::numeric;
 balance:=jsonb_build_object('schema_version','stock-monetary-balance-v1','history_version',0,
  'history_fingerprint',reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-monetary-original-v3',
   'source_fingerprint',reconforge.monetary_return_source_fingerprint(source),'allocation_policy','remaining-dual-currency-v1',
   'alignment_policy','historical-carrying-component-alignment-v1')),
  'transaction_original_gross_minor',fg::text,'functional_original_gross_minor',lg::text,'transaction_collected_minor','0','transaction_credited_minor','0',
  'transaction_outstanding_minor',fg::text,'functional_outstanding_minor',lg::text,'transaction_refund_entitlement_minor','0',
  'functional_refund_entitlement_minor','0','transaction_refunded_minor','0','functional_refund_released_minor','0',
  'transaction_refund_due_minor','0','functional_refund_due_minor','0','active_plan_id',recognition_id,'active_revaluation_plan_id',NULL);
 INSERT INTO reconforge.stock_sales_monetary_origins(tenant_id,id,workspace_id,organization_id,legal_entity_id,stock_order_id,invoice_id,
  fx_source_id,recognition_plan_id,payload,source_digest,ar_balance)
 VALUES(t,origin_id,stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id,stock_id,source->>'invoice_id',fx_id,
  recognition_id,payload,reconforge.irp_digest(payload),balance);
END $mr149$;
"""
    return assembler + wrapper


ORIGIN_SQL = _origin_functions(ORIGIN_SQL)

FX_SQL = r"""
CREATE FUNCTION reconforge.monetary_stock_prefix(t TEXT,i TEXT,version INTEGER) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE history JSONB;result JSONB;
BEGIN
 history:=reconforge.monetary_stock_history(t,i);
 PERFORM reconforge.monetary_return_assert(version BETWEEN 0 AND jsonb_array_length(history->'events'),
  'The exact retained monetary prefix must exist');
 SELECT COALESCE(jsonb_agg(member.value ORDER BY member.ordinal),'[]') INTO result
  FROM jsonb_array_elements(history->'events') WITH ORDINALITY member(value,ordinal) WHERE member.ordinal<=version;
 RETURN result;
END $mr149$;
CREATE FUNCTION reconforge.monetary_fx_valuation_equation(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;origin_owner RECORD;source_owner RECORD;prior RECORD;original_owner RECORD;original_link RECORD;
 source JSONB;request JSONB;equation JSONB;prefix JSONB;position JSONB;expected JSONB;member JSONB;basis JSONB;
 active TEXT;version INTEGER;foreign_amount NUMERIC;local_amount NUMERIC;valued NUMERIC;delta NUMERIC;code TEXT;kind TEXT;
BEGIN
 SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO source_owner FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=plan_owner.source_id;
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND fx_source_id=source_owner.id;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL AND plan_owner.kind IN('revalue','reverse_revaluation'),
  'Closing valuation requires its exact monetary Stock origin');
 source:=origin_owner.payload->'source';request:=plan_owner.payload->'command_request';
 FOR prior IN SELECT previous_plan.* FROM reconforge.operational_fx_plans previous_plan
  WHERE previous_plan.tenant_id=t AND previous_plan.source_id=source_owner.id AND previous_plan.sequence<plan_owner.sequence ORDER BY previous_plan.sequence LOOP
  PERFORM reconforge.monetary_return_assert(prior.phase=2 AND prior.payload->>'posting_date'<=plan_owner.payload->>'posting_date',
   'Closing valuation follows complete posted native FX chronology');
  IF prior.kind='revalue' THEN
   PERFORM reconforge.monetary_return_assert(active IS NULL,'Only one closing valuation may be active');active:=prior.id;
  ELSIF prior.kind='reverse_revaluation' THEN
   PERFORM reconforge.monetary_return_assert(active=prior.payload#>>'{equation,original_revaluation_id}','Closing inverse must close the exact active valuation');active:=NULL;
  ELSE PERFORM reconforge.monetary_return_assert(active IS NULL,'Cash cannot consume a still-valued historical receivable');END IF;
 END LOOP;
 PERFORM reconforge.monetary_return_assert(request->>'kind'=plan_owner.kind AND request->>'source_id'=source_owner.id
  AND(request->>'period_id',request->>'posting_date',request->>'reason')=(plan_owner.payload->>'period_id',plan_owner.payload->>'posting_date',plan_owner.payload->>'reason'),
  'The exact closing request must preserve its source, accounting date and reason');
 IF plan_owner.kind='reverse_revaluation' THEN
  PERFORM reconforge.monetary_return_assert(reconforge.fx_object(request,ARRAY['kind','source_id','original_revaluation_id','period_id','posting_date','reason'])
   AND active=request->>'original_revaluation_id','A closing inverse requires its exact still-active original');
  SELECT * INTO original_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=active;
  SELECT * INTO original_link FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=active;
  PERFORM reconforge.monetary_return_assert(original_owner.kind='revalue' AND original_owner.phase=2 AND original_owner.source_id=source_owner.id
   AND original_link.posting_effect_id IS NOT NULL,'The original closing valuation must have its real native posted effect');
  SELECT jsonb_agg(jsonb_build_object('account_code',line.value->>'account_code','debit_minor',line.value->'credit_minor',
    'credit_minor',line.value->'debit_minor') ORDER BY line.ordinal) INTO expected
   FROM jsonb_array_elements(original_owner.payload#>'{equation,lines}') WITH ORDINALITY line(value,ordinal);
  RETURN jsonb_build_object('original_revaluation_id',active,'original_plan_digest',original_owner.payload->>'plan_digest',
   'original_posting_effect_id',original_link.posting_effect_id,'original_equation_digest',reconforge.irp_digest(original_owner.payload->'equation'),
   'unrealized_fx_minor',-(original_owner.payload#>>'{equation,unrealized_fx_minor}')::numeric,
   'amount_minor',original_owner.payload->'amount_minor','lines',expected);
 END IF;
 PERFORM reconforge.monetary_return_assert(active IS NULL AND reconforge.fx_object(request,ARRAY['kind','source_id','closing_rate',
  'unrealized_gain_account_code','unrealized_loss_account_code','period_id','posting_date','reason'])
  AND source#>>'{transaction_policy,currency_code}'<>source#>>'{functional_policy,currency_code}',
  'A new closing valuation requires a foreign source and no active prior closing');
 basis:=plan_owner.payload#>'{equation,monetary_history_basis}';
 PERFORM reconforge.monetary_return_assert(reconforge.fx_object(basis,ARRAY['source_fingerprint','history_version','history_fingerprint'])
  AND reconforge.fx_minor(basis->'history_version'),'Closing carrying must preserve an exact monetary history witness');
 version:=(basis->>'history_version')::integer;prefix:=reconforge.monetary_stock_prefix(t,origin_owner.stock_order_id,version);
 position:=CASE WHEN version=0 THEN reconforge.monetary_return_initial(source) ELSE prefix->(version-1)->'after' END;
 PERFORM reconforge.monetary_return_assert(basis->>'source_fingerprint'=reconforge.monetary_return_source_fingerprint(source)
  AND basis->>'history_fingerprint'=(CASE WHEN version=0 THEN reconforge.irp_digest(jsonb_build_object(
    'contract','customer-partial-return-monetary-original-v3','source_fingerprint',basis->>'source_fingerprint',
    'allocation_policy','remaining-dual-currency-v1','alignment_policy','historical-carrying-component-alignment-v1')) ELSE reconforge.irp_digest(prefix->(version-1)) END)
  AND(version=0 OR prefix->(version-1)->>'posting_date'<=plan_owner.payload->>'posting_date'),
  'The closing witness must bind the actual credit-adjusted historical carrying prefix');
 foreign_amount:=(position->>'transaction_outstanding_minor')::numeric;local_amount:=(position->>'functional_outstanding_minor')::numeric;
 valued:=reconforge.fx_convert(foreign_amount,reconforge.fx_rate(request->'closing_rate',request->>'posting_date'),
  (source#>>'{transaction_policy,precision}')::integer,(source#>>'{functional_policy,precision}')::integer);delta:=valued-local_amount;
 PERFORM reconforge.monetary_return_assert(foreign_amount>0 AND reconforge.fx_minor(to_jsonb(valued)) AND abs(delta) BETWEEN 1 AND 9000000000000000000
  AND request->>'unrealized_gain_account_code'<>request->>'unrealized_loss_account_code'
  AND NOT EXISTS(SELECT 1 FROM jsonb_each_text(source_owner.payload->'request') role WHERE role.key LIKE '%_account_code'
   AND role.value IN(request->>'unrealized_gain_account_code',request->>'unrealized_loss_account_code'))
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(source_owner.payload#>'{request,taxes}') tax
   WHERE tax->>'account_code' IN(request->>'unrealized_gain_account_code',request->>'unrealized_loss_account_code')),
  'Closing roles must remain distinct from original tax, cash, revenue and realized FX roles');
 FOREACH kind IN ARRAY ARRAY['gain','loss'] LOOP
  code:=request->>('unrealized_'||kind||'_account_code');
  PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.finance_accounts account_owner
   JOIN reconforge.finance_journals journal_owner ON(journal_owner.tenant_id,journal_owner.chart_id)=(account_owner.tenant_id,account_owner.chart_id)
   WHERE account_owner.tenant_id=t AND account_owner.workspace_id=origin_owner.workspace_id AND journal_owner.id=origin_owner.payload->>'journal_id'
   AND account_owner.account_code=code AND account_owner.account_type=(CASE kind WHEN'gain' THEN'Income' ELSE'Expense' END)),
   'Closing accounts require their exact native classification and original chart');
 END LOOP;
 expected:=jsonb_build_array(jsonb_build_object('account_code',source_owner.payload#>>'{request,receivable_account_code}',
  'debit_minor',greatest(delta,0),'credit_minor',greatest(-delta,0)),jsonb_build_object('account_code',
  request->>(CASE WHEN delta>0 THEN'unrealized_gain_account_code' ELSE'unrealized_loss_account_code' END),
  'debit_minor',greatest(-delta,0),'credit_minor',greatest(delta,0)));
 RETURN jsonb_build_object('foreign_before_minor',(source_owner.payload->>'foreign_gross_minor')::numeric-foreign_amount,
  'historical_before_minor',(source_owner.payload->>'functional_gross_minor')::numeric-local_amount,
  'foreign_outstanding_minor',foreign_amount,'historical_outstanding_minor',local_amount,'valued_outstanding_minor',valued,
  'unrealized_fx_minor',delta,'closing_rate',request->'closing_rate','unrealized_gain_account_code',request->>'unrealized_gain_account_code',
  'unrealized_loss_account_code',request->>'unrealized_loss_account_code','amount_minor',abs(delta),'lines',expected,'monetary_history_basis',basis);
END $mr149$;
CREATE FUNCTION reconforge.monetary_fx_equation(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;origin_owner RECORD;source_owner RECORD;request JSONB;event JSONB;expected_event JSONB;prefix JSONB;lines JSONB:='[]';
 role TEXT;debit NUMERIC;credit NUMERIC;amount NUMERIC;
BEGIN
 SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO source_owner FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=plan_owner.source_id;
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND fx_source_id=source_owner.id;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL,'FX phases require the immutable monetary Stock origin');
 IF plan_owner.kind='recognize' THEN
  PERFORM reconforge.monetary_return_assert(plan_owner.payload->'command_request'=(source_owner.payload->'request')||jsonb_build_object('kind','recognize'),
   'Recognition must preserve its exact captured original request');
  RETURN jsonb_build_object('lines',source_owner.payload->'lines');
 ELSIF plan_owner.kind<>'settle' THEN RETURN reconforge.monetary_fx_valuation_equation(t,i);END IF;
 request:=plan_owner.payload->'command_request';event:=plan_owner.payload#>'{equation,monetary_event}';
 PERFORM reconforge.monetary_return_assert(reconforge.fx_object(request,ARRAY['kind','source_id','receipt_number','receipt_date','period_id','amount_minor','settlement_rate','reason'])
  AND request->>'kind'='settle' AND request->>'source_id'=source_owner.id AND reconforge.fx_minor(request->'amount_minor')
  AND(request->>'receipt_date',request->>'period_id',request->>'reason')=(plan_owner.payload->>'posting_date',plan_owner.payload->>'period_id',plan_owner.payload->>'reason')
  AND reconforge.irp_text(request->>'receipt_number',60),'Collection requires its exact positive transaction amount and original document intent');
 prefix:=reconforge.monetary_stock_prefix(t,origin_owner.stock_order_id,(event->>'sequence')::integer-1);
 expected_event:=reconforge.monetary_return_next(origin_owner.payload->'source',prefix,'Collection',0,(request->>'amount_minor')::bigint,
  request->>'receipt_date',NULLIF(request->'settlement_rate','null'::jsonb),NULL);
 PERFORM reconforge.monetary_return_assert(event=expected_event,'Collection carrying must be derived from the actual complete monetary prefix');
 FOREACH role IN ARRAY ARRAY['cash','receivable','gain','loss'] LOOP
  debit:=CASE role WHEN'cash' THEN(event#>>'{monetary,functional_cash_minor}')::numeric
   WHEN'loss' THEN(event#>>'{monetary,functional_fx_loss_minor}')::numeric ELSE 0 END;
  credit:=CASE role WHEN'receivable' THEN(event#>>'{monetary,functional_receivable_released_minor}')::numeric
   WHEN'gain' THEN(event#>>'{monetary,functional_fx_gain_minor}')::numeric ELSE 0 END;
  IF debit+credit>0 THEN lines:=lines||jsonb_build_array(jsonb_build_object('account_code',source_owner.payload->'request'->>(role||'_account_code'),
   'debit_minor',debit,'credit_minor',credit));END IF;
 END LOOP;
 RETURN jsonb_build_object('foreign_minor',request->'amount_minor','monetary_event',event,'lines',lines);
END $mr149$;
CREATE FUNCTION reconforge.monetary_fx_close(t TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;source_owner RECORD;origin_owner RECORD;entry_owner RECORD;review_owner RECORD;link_owner RECORD;effect_owner RECORD;
 receipt_owner RECORD;prior RECORD;command_owner RECORD;account_owner RECORD;v JSONB;equation JSONB;snapshot JSONB;line JSONB;actual JSONB;policy JSONB;
 expected_lines JSONB;turnover NUMERIC;sequence INTEGER:=0;ordinal INTEGER:=0;active TEXT;actor TEXT;expected_response JSONB;inverse_effect TEXT;
BEGIN
 SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO source_owner FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=plan_owner.source_id;
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND fx_source_id=source_owner.id;
 SELECT * INTO entry_owner FROM reconforge.finance_entries WHERE tenant_id=t AND id=plan_owner.entry_id;
 SELECT * INTO review_owner FROM reconforge.operational_fx_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO link_owner FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=i;
 v:=plan_owner.payload;policy:=source_owner.payload->'functional_policy';
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL AND plan_owner.id~'^FX1-[0-9a-f]{32}$'
  AND reconforge.irp_scope(t,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
  AND source_owner.payload->>'schema_version'='operational-fx-stock-source-v2'
  AND reconforge.fx_object(v,ARRAY['schema_version','id','source_id','workspace_id','organization_id','legal_entity_id','kind','sequence','period_id','posting_date','reason',
   'currency_code','currency_precision','source_digest','entry_id','equation','amount_minor','snapshot','preparer_actor_id','command_request','plan_digest','validation_digest'])
  AND v->>'plan_digest'=reconforge.irp_digest(v-ARRAY['plan_digest','validation_digest'])
  AND v->>'source_digest'=source_owner.payload->>'source_digest'
  AND(v->>'id',v->>'source_id',v->>'kind',v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id')=
   (i,source_owner.id,plan_owner.kind,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
  AND(plan_owner.workspace_id,plan_owner.organization_id,plan_owner.legal_entity_id)=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
  AND v->'entry_id' IS NOT DISTINCT FROM COALESCE(to_jsonb(plan_owner.entry_id),'null'::jsonb) AND reconforge.fx_minor(v->'amount_minor')
  AND reconforge.fx_minor(v->'sequence') AND(v->>'sequence')::integer=plan_owner.sequence
  AND v->>'currency_code'=policy->>'currency_code' AND v->'currency_precision'=policy->'currency_precision',
  'The reused FX plan must preserve its exact fixed source, scope, identity and immutable financial seal');
 FOR prior IN SELECT previous_plan.* FROM reconforge.operational_fx_plans previous_plan
  WHERE previous_plan.tenant_id=t AND previous_plan.source_id=source_owner.id AND previous_plan.sequence<plan_owner.sequence ORDER BY previous_plan.sequence LOOP
  PERFORM reconforge.monetary_return_assert(prior.sequence=sequence AND prior.phase=2 AND prior.payload->>'posting_date'<=v->>'posting_date',
   'Native FX operations require contiguous posted prior ownership');sequence:=sequence+1;
  IF prior.kind='revalue' THEN active:=prior.id;ELSIF prior.kind='reverse_revaluation' THEN active:=NULL;END IF;
 END LOOP;
 PERFORM reconforge.monetary_return_assert(sequence=plan_owner.sequence AND(plan_owner.sequence=0)=(plan_owner.kind='recognize')
  AND(plan_owner.kind NOT IN('recognize','settle') OR active IS NULL),'An active closing valuation cannot be consumed by a historical collection');
 equation:=reconforge.monetary_fx_equation(t,i);expected_lines:=equation->'lines';
 SELECT COALESCE(sum((detail->>'debit_minor')::numeric),0) INTO turnover FROM jsonb_array_elements(expected_lines) detail;
 PERFORM reconforge.monetary_return_assert(equation=v->'equation' AND turnover=(v->>'amount_minor')::numeric,
  'Native FX accounting must match independently recomputed original or current carrying');
 IF turnover=0 THEN
  PERFORM reconforge.monetary_return_assert(plan_owner.kind='settle' AND v->>'schema_version'='operational-fx-stock-plan-v2'
   AND plan_owner.entry_id IS NULL AND v->'entry_id'='null'::jsonb AND v->'snapshot'='null'::jsonb AND v->'validation_digest'='null'::jsonb
   AND jsonb_array_length(expected_lines)=0 AND link_owner.posting_effect_id IS NULL,
   'Only an exact zero-turnover foreign collection may omit its functional journal');
 ELSE
  IF plan_owner.phase=2 THEN
   snapshot:=reconforge.monetary_posted_close(t,plan_owner.entry_id,link_owner.posting_effect_id,origin_owner.organization_id,origin_owner.legal_entity_id);
  ELSE snapshot:=reconforge.fr_snapshot(t,plan_owner.entry_id,origin_owner.organization_id,origin_owner.legal_entity_id);END IF;
  inverse_effect:=CASE WHEN plan_owner.kind='reverse_revaluation' THEN equation->>'original_posting_effect_id' ELSE NULL END;
  PERFORM reconforge.monetary_return_assert(entry_owner.id IS NOT NULL AND entry_owner.entry_number=upper(i)
   AND v->>'schema_version'=(CASE WHEN plan_owner.kind IN('revalue','reverse_revaluation') THEN'operational-fx-plan-v2' ELSE'operational-fx-plan-v1' END)
   AND v->'snapshot'=snapshot
   AND v->>'validation_digest'=(CASE WHEN plan_owner.phase=2 THEN entry_owner.validation_digest ELSE reconforge.irp_digest(snapshot) END)
   AND entry_owner.external_reference=(CASE WHEN inverse_effect IS NOT NULL THEN inverse_effect ELSE'FX:'||source_owner.id||':'||plan_owner.kind END)
   AND entry_owner.source_type=(CASE WHEN inverse_effect IS NOT NULL THEN'Generated' ELSE'Manual' END)
   AND entry_owner.reverses_posting_id IS NOT DISTINCT FROM inverse_effect
   AND(entry_owner.workspace_id,entry_owner.period_id,entry_owner.posting_date,entry_owner.preparer_actor_id)=
    (origin_owner.workspace_id,v->>'period_id',v->>'posting_date',v->>'preparer_actor_id')
   AND(entry_owner.currency_code,entry_owner.currency_precision,entry_owner.currency_rounding_policy,entry_owner.currency_registry_version,entry_owner.currency_registry_digest)=
    (policy->>'currency_code',(policy->>'currency_precision')::integer,policy->>'currency_rounding_policy',policy->>'currency_registry_version',policy->>'currency_registry_digest')
   AND entry_owner.journal_id=origin_owner.payload->>'journal_id' AND entry_owner.total_debit_minor=turnover AND entry_owner.total_credit_minor=turnover
   AND entry_owner.status=(CASE WHEN plan_owner.phase=0 THEN'Draft' ELSE'Validated' END)
   AND jsonb_array_length(snapshot->'lines')=jsonb_array_length(expected_lines),
   'Actual FX journal identity, scope, captured policy, snapshot and financial turnover must be exact');
  FOR line IN SELECT value FROM jsonb_array_elements(expected_lines) LOOP
   SELECT * INTO account_owner FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=origin_owner.workspace_id
    AND chart_id=(SELECT chart_id FROM reconforge.finance_journals WHERE tenant_id=t AND id=entry_owner.journal_id) AND account_code=line->>'account_code';
   actual:=snapshot->'lines'->ordinal;ordinal:=ordinal+1;
   PERFORM reconforge.monetary_return_assert(account_owner.id IS NOT NULL AND actual->>'line_number'=ordinal::text
    AND actual->>'account_id'=account_owner.id AND actual->'debit_minor'=line->'debit_minor' AND actual->'credit_minor'=line->'credit_minor'
    AND actual->'dimensions'='{}'::jsonb,'Every FX journal line must retain the complete ordered native account and exact amount');
  END LOOP;
 END IF;
 PERFORM reconforge.monetary_return_assert(reconforge.fx_event(t,i,plan_owner.audit_event_id,plan_owner.outbox_event_id,v->>'preparer_actor_id',
  'operational_fx_prepared',jsonb_build_object('plan_digest',v->>'plan_digest')),'Preparation requires the actual native audit and outbox');
 IF plan_owner.phase=0 THEN PERFORM reconforge.monetary_return_assert(review_owner.plan_id IS NULL AND link_owner.plan_id IS NULL,'Prepared FX cannot have later phase evidence');END IF;
 IF plan_owner.phase>=1 THEN
  PERFORM reconforge.monetary_return_assert(review_owner.plan_id IS NOT NULL AND review_owner.reviewer_actor_id<>v->>'preparer_actor_id'
   AND(turnover=0 OR(entry_owner.validator_actor_id=review_owner.reviewer_actor_id AND entry_owner.validation_digest=v->>'validation_digest'))
   AND reconforge.fx_event(t,i,review_owner.audit_event_id,review_owner.outbox_event_id,review_owner.reviewer_actor_id,
    'operational_fx_reviewed',jsonb_build_object('plan_digest',v->>'plan_digest')),'The exact independent review must govern both zero and real journals');
 END IF;
 IF plan_owner.phase<2 THEN
  PERFORM reconforge.monetary_return_assert(link_owner.plan_id IS NULL AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects effect WHERE effect.tenant_id=t AND effect.entry_id=plan_owner.entry_id),
   'Unposted FX cannot have financial or receipt effects');
 ELSE
  PERFORM reconforge.monetary_return_assert(link_owner.plan_id IS NOT NULL AND link_owner.posted_actor_id<>v->>'preparer_actor_id'
   AND link_owner.posted_actor_id<>review_owner.reviewer_actor_id AND reconforge.fx_event(t,i,link_owner.audit_event_id,link_owner.outbox_event_id,
   link_owner.posted_actor_id,'operational_fx_posted',jsonb_build_object('plan_digest',v->>'plan_digest','posting_effect_id',link_owner.posting_effect_id)),
   'Publication requires its exact third human, audit and outbox even without a journal');
  IF turnover>0 THEN
   SELECT * INTO effect_owner FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=link_owner.posting_effect_id;
   PERFORM reconforge.monetary_return_assert(effect_owner.id IS NOT NULL AND effect_owner.entry_id=entry_owner.id AND effect_owner.snapshot_json=snapshot
    AND effect_owner.validation_digest=v->>'validation_digest' AND effect_owner.posted_actor_id=link_owner.posted_actor_id
    AND(effect_owner.workspace_id,effect_owner.organization_id,effect_owner.legal_entity_id)=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
    AND effect_owner.source_id=COALESCE(entry_owner.reverses_posting_id,entry_owner.id) AND effect_owner.purpose='operational_posting'
    AND effect_owner.source_kind=(CASE WHEN inverse_effect IS NULL THEN'Manual' ELSE'Reversal' END)
    AND effect_owner.validation_contract_version='finance-entry-review-v1' AND entry_owner.validation_contract_version='finance-entry-review-v1'
    AND(effect_owner.currency_code,effect_owner.currency_precision,effect_owner.currency_rounding_policy,effect_owner.currency_registry_version,effect_owner.currency_registry_digest)=
     (entry_owner.currency_code,entry_owner.currency_precision,entry_owner.currency_rounding_policy,entry_owner.currency_registry_version,entry_owner.currency_registry_digest)
    AND effect_owner.reverses_effect_id IS NOT DISTINCT FROM inverse_effect
    AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse WHERE inverse.tenant_id=t AND inverse.reverses_effect_id=effect_owner.id
     AND NOT EXISTS(SELECT 1 FROM reconforge.operational_fx_plans inverse_plan JOIN reconforge.operational_fx_links inverse_link
      ON(inverse_link.tenant_id,inverse_link.plan_id)=(inverse_plan.tenant_id,inverse_plan.id)
      WHERE inverse_plan.tenant_id=t AND inverse_plan.source_id=source_owner.id AND inverse_plan.kind='reverse_revaluation' AND inverse_plan.phase=2
      AND inverse_plan.payload#>>'{equation,original_revaluation_id}'=i AND inverse_link.posting_effect_id=inverse.id)),
    'Posted FX must retain its exact real sealed effect; generic inverse ownership is forbidden');
  END IF;
  IF plan_owner.kind='settle' THEN
   SELECT * INTO receipt_owner FROM reconforge.ar_receipts WHERE tenant_id=t AND id=link_owner.receipt_id;
   PERFORM reconforge.monetary_return_assert(receipt_owner.id IS NOT NULL AND receipt_owner.receipt_number='FX1-'||(v#>>'{command_request,receipt_number}')
    AND receipt_owner.receipt_date::text=v->>'posting_date' AND receipt_owner.status='Posted'
    AND receipt_owner.amount_minor=(equation->>'foreign_minor')::numeric
    AND(receipt_owner.workspace_id,receipt_owner.organization_id,receipt_owner.legal_entity_id,receipt_owner.customer_id,receipt_owner.currency_code)=
     (origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id,
      (SELECT customer_id FROM reconforge.ar_invoices WHERE tenant_id=t AND id=origin_owner.invoice_id),source_owner.payload#>>'{foreign_policy,currency_code}')
    AND receipt_owner.posted_by=(SELECT username FROM reconforge.identity_users WHERE tenant_id=t AND id=link_owner.posted_actor_id)
    AND receipt_owner.created_by=receipt_owner.posted_by AND receipt_owner.posted_at IS NOT NULL
    AND(SELECT count(*) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND receipt_id=receipt_owner.id)=1
    AND EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations allocation WHERE allocation.tenant_id=t AND allocation.receipt_id=receipt_owner.id
     AND allocation.invoice_id=origin_owner.invoice_id AND allocation.amount_minor=receipt_owner.amount_minor)
    AND EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_history history_owner WHERE history_owner.tenant_id=t
     AND history_owner.origin_id=origin_owner.id AND history_owner.stock_fx_plan_id=i AND history_owner.kind='Collection' AND history_owner.payload=equation->'monetary_event'),
    'Collection must bind its exact posted foreign receipt, allocation and chronological monetary history');
  ELSE PERFORM reconforge.monetary_return_assert(link_owner.receipt_id IS NULL,'Recognition and closing cannot fabricate cash receipts');END IF;
 END IF;
 FOR command_owner IN SELECT * FROM reconforge.operational_fx_commands WHERE tenant_id=t AND plan_id=i LOOP
  actor:=CASE command_owner.operation WHEN'prepare' THEN v->>'preparer_actor_id' WHEN'review' THEN review_owner.reviewer_actor_id ELSE link_owner.posted_actor_id END;
  expected_response:=v||jsonb_build_object('phase',CASE command_owner.operation WHEN'prepare' THEN 0 WHEN'review' THEN 1 ELSE 2 END,
   'status',CASE command_owner.operation WHEN'prepare' THEN'Prepared' WHEN'review' THEN'Reviewed' ELSE'Posted' END,
   'reviewer_actor_id',CASE WHEN command_owner.operation='prepare' THEN NULL ELSE review_owner.reviewer_actor_id END,
   'posting_effect_id',CASE WHEN command_owner.operation='post' THEN link_owner.posting_effect_id ELSE NULL END,
   'receipt_id',CASE WHEN command_owner.operation='post' THEN link_owner.receipt_id ELSE NULL END);
  PERFORM reconforge.monetary_return_assert(command_owner.actor_id=actor AND command_owner.request_digest=reconforge.irp_digest(command_owner.request_json)
   AND command_owner.request_json=jsonb_build_object('operation',command_owner.operation,'actor_id',actor,'request',
    CASE WHEN command_owner.operation='prepare' THEN v->'command_request' ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',v->>'plan_digest',
     'reason',CASE WHEN command_owner.operation='review' THEN review_owner.reason ELSE link_owner.reason END) END)
   AND command_owner.response_json=expected_response,'Every FX acknowledgement must retain its exact actor, request and historical phase response');
 END LOOP;
 PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM reconforge.operational_fx_commands WHERE tenant_id=t AND plan_id=i)=plan_owner.phase+1,
  'Every FX phase requires exactly one immutable command');
END $mr149$;
"""

PARTIAL_SQL = r"""
CREATE FUNCTION reconforge.monetary_partial_public_at(t TEXT,i TEXT,stage INTEGER) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;v JSONB;money JSONB;entries JSONB;reviewer TEXT;poster TEXT;cancelled TEXT;
BEGIN
 SELECT * INTO plan_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=i;v:=plan_owner.payload;
 PERFORM reconforge.monetary_return_assert(plan_owner.id IS NOT NULL AND stage BETWEEN 0 AND 3,'The exact partial plan and phase are required');
 SELECT jsonb_object_agg(key,to_jsonb(value#>>'{}')) INTO money FROM jsonb_each(v->'monetary');
 SELECT COALESCE(jsonb_agg(jsonb_build_object('purpose',detail.value->>'purpose','entry_id',detail.value->>'entry_id',
  'validation_digest',detail.value->>'validation_digest','posting_effect_id',CASE WHEN stage=2 THEN native.posting_effect_id ELSE NULL END)
  ORDER BY detail.ordinal),'[]') INTO entries
  FROM jsonb_array_elements(v->'entries') WITH ORDINALITY detail(value,ordinal)
  LEFT JOIN reconforge.customer_partial_return_monetary_entries native ON native.tenant_id=t AND native.plan_id=i AND native.purpose=detail.value->>'purpose';
 IF stage IN(1,2,3) THEN SELECT actor_id INTO reviewer FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='review';END IF;
 IF stage=2 THEN SELECT actor_id INTO poster FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='post';END IF;
 IF stage=3 THEN SELECT actor_id INTO cancelled FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='cancel';END IF;
 RETURN(v-ARRAY['organization_code','entity_code','request','monetary_event','entries','movement_id','quantity_scaled','monetary'])||jsonb_build_object(
  'status',CASE stage WHEN 0 THEN'Prepared' WHEN 1 THEN'Reviewed' WHEN 2 THEN'Posted' ELSE'Cancelled' END,'phase',stage,
  'quantity_scaled',v->>'quantity_scaled','monetary',money,'entries',entries,
  'transaction_policy',reconforge.monetary_full_policy(v->'transaction_policy'),'functional_policy',reconforge.monetary_full_policy(v->'functional_policy'),
  'movement_id',CASE WHEN stage=2 THEN v->>'movement_id' ELSE NULL END,'reviewer_actor_id',reviewer,'posted_actor_id',poster,'cancelled_actor_id',cancelled);
END $mr149$;
CREATE FUNCTION reconforge.monetary_partial_public(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE stage INTEGER;
BEGIN
 SELECT phase INTO stage FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=i;
 RETURN reconforge.monetary_partial_public_at(t,i,stage);
END $mr149$;
CREATE FUNCTION reconforge.monetary_partial_balance(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE origin_owner RECORD;balance JSONB;history JSONB;remaining NUMERIC;
BEGIN
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND id=i;
 balance:=reconforge.monetary_stock_balance(t,origin_owner.stock_order_id);history:=reconforge.monetary_stock_history(t,origin_owner.stock_order_id);
 remaining:=CASE WHEN jsonb_array_length(history->'events')=0 THEN(origin_owner.payload#>>'{source,quantity_scaled}')::numeric
  ELSE(history->'events'->(jsonb_array_length(history->'events')-1)#>>'{after,remaining_quantity_scaled}')::numeric END;
 RETURN balance||jsonb_build_object('schema_version','customer-partial-return-monetary-balance-v3','source_id',i,
  'source_order_id',origin_owner.stock_order_id,'invoice_id',origin_owner.invoice_id,'workspace_id',origin_owner.workspace_id,
  'organization_id',origin_owner.organization_id,'legal_entity_id',origin_owner.legal_entity_id,
  'source_fingerprint',reconforge.monetary_return_source_fingerprint(origin_owner.payload->'source'),
  'transaction_policy',reconforge.monetary_full_policy(origin_owner.payload#>'{source,transaction_policy}'),
  'functional_policy',reconforge.monetary_full_policy(origin_owner.payload#>'{source,functional_policy}'),
  'quantity_precision',origin_owner.payload#>'{source,quantity_precision}','original_quantity_scaled',origin_owner.payload#>>'{source,quantity_scaled}',
  'returned_quantity_scaled',((origin_owner.payload#>>'{source,quantity_scaled}')::numeric-remaining)::text,'remaining_quantity_scaled',remaining::text);
END $mr149$;
CREATE FUNCTION reconforge.monetary_partial_close(t TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;origin_owner RECORD;original_owner RECORD;event_owner RECORD;command_owner RECORD;entry_member RECORD;
 v JSONB;source JSONB;prefix JSONB;event JSONB;expected_event JSONB;journals JSONB;part JSONB;lines JSONB;original_event JSONB;
 reviewer TEXT;poster TEXT;preparer TEXT;cancelled TEXT;expected_command TEXT;expected_request JSONB;expected_response JSONB;stage INTEGER;ordinal INTEGER:=0;
BEGIN
 SELECT * INTO plan_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=i;v:=plan_owner.payload;
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND id=plan_owner.origin_id;
 PERFORM reconforge.monetary_return_assert(plan_owner.id IS NOT NULL AND origin_owner.id IS NOT NULL
  AND reconforge.irp_scope(t,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
  AND reconforge.fx_object(v,ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','organization_code','entity_code',
   'source_id','source_order_id','invoice_id','operation','quantity_scaled','quantity_precision','period_id','posting_date','reason',
   'source_fingerprint','history_fingerprint','expected_history_version','allocation_policy','transaction_policy','functional_policy',
   'monetary','monetary_event','entries','movement_id','original_id','request','preparer_actor_id','plan_digest'])
  AND v->>'schema_version'='customer-partial-return-monetary-v3' AND v->>'allocation_policy'='remaining-dual-currency-v1'
  AND v->>'plan_digest'=reconforge.irp_digest(v-'plan_digest') AND plan_owner.plan_digest=v->>'plan_digest'
  AND(v->>'id',v->>'operation',v->>'source_id',v->>'source_order_id',v->>'invoice_id',v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id')=
   (i,plan_owner.operation,origin_owner.id,origin_owner.stock_order_id,origin_owner.invoice_id,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
  AND v->>'original_id' IS NOT DISTINCT FROM plan_owner.original_id
  AND reconforge.fx_minor(v->'expected_history_version') AND(v->>'expected_history_version')::integer=plan_owner.expected_history_version,
  'The monetary correction must retain its exact bounded native source, scope, version and sealed request');
 source:=origin_owner.payload->'source';event:=v->'monetary_event';preparer:=v->>'preparer_actor_id';
 prefix:=reconforge.monetary_stock_prefix(t,origin_owner.stock_order_id,plan_owner.expected_history_version);
 expected_event:=reconforge.monetary_return_next(source,prefix,plan_owner.operation,(v->>'quantity_scaled')::bigint,
  (event->>'amount_minor')::bigint,v->>'posting_date',NULLIF(event->'settlement_rate','null'::jsonb),(event->>'original_sequence')::integer);
 PERFORM reconforge.monetary_return_assert(event=expected_event AND v->'monetary'=expected_event->'monetary'
  AND v->>'source_fingerprint'=reconforge.monetary_return_source_fingerprint(source)
  AND v->>'history_fingerprint'=event->>'previous_history_fingerprint' AND v->'transaction_policy'=source->'transaction_policy'
  AND v->'functional_policy'=source->'functional_policy' AND v->'quantity_precision'=source->'quantity_precision'
  AND reconforge.irp_text(v->>'reason',500),'Every component, carrying release, entitlement, alignment and FIFO witness must independently replay');
 PERFORM reconforge.monetary_return_assert(v#>>'{request,period_id}'=v->>'period_id' AND v#>>'{request,posting_date}'=v->>'posting_date'
  AND v#>>'{request,reason}'=v->>'reason' AND v#>'{request,expected_history_version}'=v->'expected_history_version'
  AND((plan_owner.operation='Return' AND v#>'{request,quantity_scaled}'=v->'quantity_scaled' AND v#>>'{request,source_order_id}'=origin_owner.stock_order_id
    AND(v#>>'{request,workspace_id}',v#>>'{request,organization_id}',v#>>'{request,legal_entity_id}')=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id))
   OR(plan_owner.operation='Refund' AND v#>>'{request,return_id}'=plan_owner.original_id AND v#>'{request,amount_minor}'=event->'amount_minor'
    AND v#>'{request,settlement_rate}'=event->'settlement_rate')
   OR(plan_owner.operation LIKE'Reverse%' AND v#>>'{request,original_id}'=plan_owner.original_id)),
  'The immutable preparation intent must bind its exact source, quantity or cash amount, period and date');
 IF plan_owner.original_id IS NOT NULL THEN
  SELECT * INTO original_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=plan_owner.original_id;
  PERFORM reconforge.monetary_return_assert(original_owner.id IS NOT NULL AND original_owner.origin_id=origin_owner.id AND original_owner.phase=2
   AND original_owner.operation=(CASE WHEN plan_owner.operation='Refund' THEN'Return' ELSE substring(plan_owner.operation FROM 8) END),
   'Refund and inverse parents must be actual posted native plans of the same source and exact operation');
 END IF;
 IF plan_owner.operation LIKE'Reverse%' THEN
  PERFORM reconforge.monetary_return_assert(event->>'original_sequence'=original_owner.payload#>>'{monetary_event,sequence}'
   AND v->'quantity_scaled'=original_owner.payload->'quantity_scaled' AND v->'monetary'=original_owner.payload->'monetary'
   AND event->'components'=original_owner.payload#>'{monetary_event,components}' AND event->'portions'=original_owner.payload#>'{monetary_event,portions}',
   'An inverse must copy exact original magnitudes and all original component and FIFO witnesses');
  SELECT COALESCE(jsonb_agg(jsonb_build_object('purpose','Reverse'||native.purpose,'lines',(
   SELECT jsonb_agg((line.value-ARRAY['line_number','description','debit_minor','credit_minor'])||
    jsonb_build_object('debit_minor',line.value->'credit_minor','credit_minor',line.value->'debit_minor') ORDER BY line.ordinal)
   FROM jsonb_array_elements(native.snapshot->'lines') WITH ORDINALITY line(value,ordinal)))
   ORDER BY CASE native.purpose WHEN'MerchandiseCredit' THEN 1 WHEN'CostRestoration' THEN 2 ELSE 1 END),'[]') INTO journals
   FROM reconforge.customer_partial_return_monetary_entries native WHERE native.tenant_id=t AND native.plan_id=plan_owner.original_id;
 ELSE journals:=reconforge.monetary_return_journals(origin_owner.payload,event);END IF;
 PERFORM reconforge.monetary_return_assert(jsonb_array_length(v->'entries')=jsonb_array_length(journals)
  AND(SELECT count(*) FROM reconforge.customer_partial_return_monetary_entries WHERE tenant_id=t AND plan_id=i)=jsonb_array_length(journals),
  'Only the complete nonzero original-account correction journal set may exist');
 FOR part IN SELECT member.value FROM jsonb_array_elements(journals) WITH ORDINALITY member(value,ordinal) ORDER BY member.ordinal LOOP
  SELECT * INTO entry_member FROM reconforge.customer_partial_return_monetary_entries native
   WHERE native.tenant_id=t AND native.plan_id=i AND native.purpose=part->>'purpose';
  PERFORM reconforge.monetary_return_assert(v->'entries'->ordinal=jsonb_build_object('purpose',entry_member.purpose,'entry_id',entry_member.entry_id,
   'snapshot',entry_member.snapshot,'validation_digest',entry_member.validation_digest,'original_effect_id',entry_member.original_effect_id),
   'The exact ordered plan journal evidence must equal every persisted native member');ordinal:=ordinal+1;
  PERFORM reconforge.monetary_partial_entry_close(t,i,part->>'purpose',part->'lines');
 END LOOP;
 FOR event_owner IN SELECT * FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i LOOP
  PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit_owner
   JOIN reconforge.outbox_events outbox_owner ON outbox_owner.tenant_id=audit_owner.tenant_id
   WHERE audit_owner.tenant_id=t AND audit_owner.id=event_owner.audit_event_id AND outbox_owner.event_id=event_owner.outbox_event_id
   AND audit_owner.actor_user_id=event_owner.actor_id AND audit_owner.object_type='operational_finance' AND audit_owner.object_id=i
   AND audit_owner.action='customer_partial_return_monetary_'||event_owner.operation
   AND audit_owner.metadata_json=jsonb_build_object('plan_digest',plan_owner.plan_digest,'reason',event_owner.reason)
   AND outbox_owner.event_type=audit_owner.action AND outbox_owner.aggregate_type='operational_finance' AND outbox_owner.aggregate_id=i
   AND(outbox_owner.workspace_id,outbox_owner.organization_id,outbox_owner.legal_entity_id)=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
   AND outbox_owner.payload=audit_owner.metadata_json||jsonb_build_object('audit_event_id',audit_owner.id)),
   'Every partial lifecycle phase requires the exact immutable native audit and outbox membership');
  IF event_owner.operation='prepare' THEN PERFORM reconforge.monetary_return_assert(event_owner.actor_id=preparer AND event_owner.reason=v->>'reason','The actual maker must own the immutable preparation');
  ELSIF event_owner.operation='review' THEN reviewer:=event_owner.actor_id;
  ELSIF event_owner.operation='post' THEN poster:=event_owner.actor_id;
  ELSE cancelled:=event_owner.actor_id;END IF;
 END LOOP;
 PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i)=
  (CASE plan_owner.phase WHEN 0 THEN 1 WHEN 1 THEN 2 WHEN 2 THEN 3 ELSE CASE WHEN reviewer IS NULL THEN 2 ELSE 3 END END)
  AND(plan_owner.phase<>0 OR(reviewer IS NULL AND poster IS NULL AND cancelled IS NULL))
  AND(plan_owner.phase NOT IN(1,2) OR(reviewer IS NOT NULL AND reviewer<>preparer))
  AND(plan_owner.phase<>2 OR(poster IS NOT NULL AND poster<>preparer AND poster<>reviewer AND cancelled IS NULL))
  AND(plan_owner.phase<>3 OR(cancelled IS NOT NULL AND cancelled<>preparer AND cancelled IS DISTINCT FROM reviewer AND poster IS NULL)),
  'Zero and nonzero financial operations require complete independent human lifecycle phases');
 IF plan_owner.phase=2 THEN
  PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_history history_owner
   WHERE history_owner.tenant_id=t AND history_owner.origin_id=origin_owner.id AND history_owner.partial_plan_id=i
   AND history_owner.kind=plan_owner.operation AND history_owner.payload=event),'Posted partials require exact immutable chronological history');
  IF plan_owner.operation IN('Return','ReverseReturn') THEN
   PERFORM reconforge.monetary_return_physical(t,i,FALSE);
   PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=t AND plan_id=i)=jsonb_array_length(event->'portions'),
    'Every physical portion must have exactly one immutable native signed restoration');
   FOR part IN SELECT value FROM jsonb_array_elements(event->'portions') LOOP
    PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations restored
     WHERE restored.tenant_id=t AND restored.plan_id=i AND restored.position=(part->>'position')::integer AND restored.origin_id=origin_owner.id
     AND(restored.workspace_id,restored.organization_id,restored.legal_entity_id)=(origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id)
     AND(restored.original_consumption_id,restored.original_valuation_line_id,restored.cost_layer_id,restored.before_quantity_scaled,restored.before_value_minor,restored.quantity_scaled,restored.value_minor)=
      (part->>'original_consumption_id',part->>'original_valuation_line_id',part->>'cost_layer_id',(part->>'before_quantity_scaled')::bigint,
       (part->>'before_value_minor')::bigint,(part->>'quantity_scaled')::bigint,(part->>'value_minor')::bigint)
     AND restored.direction=(CASE plan_owner.operation WHEN'Return' THEN 1 ELSE -1 END) AND restored.physical_movement_id=v->>'movement_id'
     AND restored.original_restoration_plan_id IS NOT DISTINCT FROM(CASE WHEN plan_owner.operation='ReverseReturn' THEN plan_owner.original_id ELSE NULL END)
     AND restored.correction_effect_id IS NOT DISTINCT FROM(SELECT posting_effect_id FROM reconforge.customer_partial_return_monetary_entries
      WHERE tenant_id=t AND plan_id=i AND purpose IN('CostRestoration','ReverseCostRestoration'))
     AND(plan_owner.operation='Return' OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations original_restoration
      WHERE original_restoration.tenant_id=t AND original_restoration.plan_id=plan_owner.original_id AND original_restoration.position=restored.position
      AND original_restoration.consumption_count_at_restore=restored.consumption_count_at_restore))),
     'Actual restoration identity, before-value, signed history, native movement and total-cost effect must remain exact');
   END LOOP;
  ELSE
   PERFORM reconforge.monetary_return_assert(NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=t AND plan_id=i)
    AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements WHERE tenant_id=t AND source_reference=i),'Cash operations cannot invent physical movements');
  END IF;
 ELSE
  PERFORM reconforge.monetary_return_assert(NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_history WHERE tenant_id=t AND partial_plan_id=i)
   AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=t AND plan_id=i)
   AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements WHERE tenant_id=t AND source_reference=i),
   'Unposted or cancelled partials cannot retain physical or economic effects');
 END IF;
 FOR command_owner IN SELECT * FROM reconforge.customer_partial_return_monetary_commands WHERE tenant_id=t AND plan_id=i LOOP
  expected_command:=CASE command_owner.operation WHEN'prepare' THEN'prepare' WHEN'prepare_refund' THEN'prepare'
   WHEN'prepare_reversal' THEN'prepare' ELSE command_owner.operation END;
  SELECT * INTO event_owner FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation=expected_command;
  stage:=CASE expected_command WHEN'prepare' THEN 0 WHEN'review' THEN 1 WHEN'post' THEN 2 ELSE 3 END;
  expected_request:=CASE WHEN expected_command='prepare' THEN v->'request' ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',plan_owner.plan_digest,'reason',event_owner.reason) END;
  PERFORM reconforge.monetary_return_assert(command_owner.actor_id=event_owner.actor_id
   AND(expected_command<>'prepare' OR command_owner.operation=(CASE plan_owner.operation WHEN'Return' THEN'prepare' WHEN'Refund' THEN'prepare_refund' ELSE'prepare_reversal' END))
   AND command_owner.request_json=jsonb_build_object('protocol_version',3,'operation',command_owner.operation,'actor_id',command_owner.actor_id,'request',expected_request)
   AND command_owner.request_digest=reconforge.irp_digest(command_owner.request_json)
   AND command_owner.response_json=reconforge.monetary_partial_public_at(t,i,stage),
   'Historical partial acknowledgements must preserve their exact current-authority actor, request and original phase');
 END LOOP;
 PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM reconforge.customer_partial_return_monetary_commands WHERE tenant_id=t AND plan_id=i)=
  (SELECT count(*) FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i),
  'Every partial native lifecycle event requires its unique immutable acknowledgement');
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_append(t TEXT,i TEXT,owner_id TEXT,event JSONB,collection BOOLEAN) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE origin_owner RECORD;plan_owner RECORD;prefix JSONB;expected JSONB;actor TEXT;poster TEXT;native_kind TEXT;
BEGIN
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=i;
 PERFORM reconforge.monetary_return_assert(origin_owner.id IS NOT NULL,'An economic append requires its complete original native owner');
 IF collection THEN
  SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=owner_id;
  SELECT posted_actor_id INTO poster FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=owner_id;
  actor:=current_setting('app.stock_sales_actor_id',true);native_kind:='Collection';
  PERFORM reconforge.monetary_return_assert(plan_owner.source_id=origin_owner.fx_source_id AND plan_owner.kind='settle' AND plan_owner.phase=2
   AND plan_owner.payload#>'{equation,monetary_event}'=event,'Collection history must bind its real posted native FX owner');
 ELSE
  SELECT * INTO plan_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=owner_id;
  SELECT actor_id INTO poster FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=owner_id AND operation='post';
  actor:=current_setting('app.customer_partial_return_monetary_actor_id',true);native_kind:=plan_owner.operation;
  PERFORM reconforge.monetary_return_assert(plan_owner.origin_id=origin_owner.id AND plan_owner.phase=2 AND plan_owner.payload->'monetary_event'=event,
   'Partial history must bind its real posted native correction owner');
 END IF;
 PERFORM reconforge.monetary_return_assert(actor=poster AND reconforge.sales_revenue_actor(t,actor,'finance_core.post'),
  'Only the actual current native posting human may append the exact economic event');
 prefix:=reconforge.monetary_stock_prefix(t,i,(event->>'sequence')::integer-1);
 PERFORM reconforge.monetary_return_assert(jsonb_array_length(reconforge.monetary_stock_history(t,i)->'events')=jsonb_array_length(prefix),
  'A source may append only at its exact next immutable economic version');
 expected:=reconforge.monetary_return_next(origin_owner.payload->'source',prefix,native_kind,(event->>'quantity_scaled')::bigint,
  (event->>'amount_minor')::bigint,event->>'posting_date',NULLIF(event->'settlement_rate','null'::jsonb),(event->>'original_sequence')::integer);
 PERFORM reconforge.monetary_return_assert(expected=event,'The append must reproduce every native prefix-time monetary witness');
 INSERT INTO reconforge.customer_partial_return_monetary_history(tenant_id,workspace_id,organization_id,legal_entity_id,origin_id,sequence,kind,
  stock_fx_plan_id,partial_plan_id,original_sequence,payload,previous_digest,event_digest)
 VALUES(t,origin_owner.workspace_id,origin_owner.organization_id,origin_owner.legal_entity_id,origin_owner.id,(event->>'sequence')::integer,native_kind,
  CASE WHEN collection THEN owner_id ELSE NULL END,CASE WHEN collection THEN NULL ELSE owner_id END,(event->>'original_sequence')::integer,event,
  event->>'previous_history_fingerprint',reconforge.irp_digest(event));
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_append_collection(t TEXT,i TEXT,p TEXT,event JSONB) RETURNS VOID
 LANGUAGE sql VOLATILE SET search_path=pg_catalog AS $mr149$ SELECT reconforge.monetary_stock_append(t,i,p,event,TRUE) $mr149$;
CREATE FUNCTION reconforge.monetary_stock_append_partial(t TEXT,i TEXT,p TEXT,event JSONB) RETURNS VOID
 LANGUAGE sql VOLATILE SET search_path=pg_catalog AS $mr149$ SELECT reconforge.monetary_stock_append(t,i,p,event,FALSE) $mr149$;
"""

PUBLIC_SQL = r"""
CREATE FUNCTION reconforge.monetary_stock_public(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE stock_owner RECORD;origin_owner RECORD;recognition RECORD;review_owner RECORD;link_owner RECORD;collection_owner RECORD;
 collection_review RECORD;collection_link RECORD;invoice_owner RECORD;origin JSONB;collection JSONB;taxes JSONB;events JSONB;balance JSONB;
 equation JSONB;request JSONB;money JSONB;
BEGIN
 SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=i;
 PERFORM reconforge.monetary_return_assert(stock_owner.id IS NOT NULL AND stock_owner.source->>'schema_version'='stock-sales-monetary-order-v2'
  AND reconforge.irp_scope(t,stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id),'The exact visible fixed monetary Stock source is required');
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=i;
 IF origin_owner.id IS NOT NULL THEN
  SELECT * INTO recognition FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=origin_owner.recognition_plan_id;
  SELECT * INTO review_owner FROM reconforge.operational_fx_reviews WHERE tenant_id=t AND plan_id=recognition.id;
  SELECT * INTO link_owner FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=recognition.id;
  SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=t AND id=origin_owner.invoice_id;
  equation:=origin_owner.payload->'equation';request:=equation->'request';
  SELECT COALESCE(jsonb_agg((part.value-ARRAY['foreign_tax_minor','functional_tax_minor'])||jsonb_build_object(
   'transaction_tax_minor',part.value->>'foreign_tax_minor','functional_tax_minor',part.value->>'functional_tax_minor') ORDER BY part.ordinal),'[]') INTO taxes
   FROM jsonb_array_elements(equation->'tax_components') WITH ORDINALITY part(value,ordinal);
  origin:=jsonb_build_object('schema_version','stock-monetary-origin-v1','id',origin_owner.id,'fx_source_id',origin_owner.fx_source_id,
   'recognition_plan_id',recognition.id,'invoice_id',invoice_owner.id,'source_digest',origin_owner.source_digest,
   'country_code',request->>'country_code','transaction_class',request->>'transaction_class','original_rate',request->'original_rate',
   'transaction_net_minor',equation->>'foreign_net_minor','transaction_tax_minor',equation->>'foreign_tax_minor',
   'transaction_gross_minor',equation->>'foreign_gross_minor','functional_net_minor',equation->>'functional_net_minor',
   'functional_tax_minor',((equation->>'functional_gross_minor')::numeric-(equation->>'functional_net_minor')::numeric)::text,
   'functional_gross_minor',equation->>'functional_gross_minor','tax_components',taxes,
   'receivable_account_code',request->>'receivable_account_code','revenue_account_code',request->>'revenue_account_code',
   'cash_account_code',request->>'cash_account_code','refund_liability_account_code',origin_owner.payload->>'refund_liability_account_code',
   'gain_account_code',request->>'gain_account_code','loss_account_code',request->>'loss_account_code',
   'journal_code',request->>'journal_code','period_id',request->>'period_id','invoice_number',invoice_owner.invoice_number,
   'invoice_date',request->>'posting_date','due_date',request->>'due_date','preparer_actor_id',recognition.payload->>'preparer_actor_id',
   'reviewer_actor_id',review_owner.reviewer_actor_id,'posted_actor_id',link_owner.posted_actor_id,'entry_id',recognition.entry_id,
   'posting_effect_id',link_owner.posting_effect_id);
  IF recognition.phase=2 THEN balance:=origin_owner.ar_balance;END IF;
 END IF;
 IF stock_owner.collection_plan_id IS NOT NULL THEN
  SELECT * INTO collection_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=stock_owner.collection_plan_id;
  SELECT * INTO collection_review FROM reconforge.operational_fx_reviews WHERE tenant_id=t AND plan_id=collection_owner.id;
  SELECT * INTO collection_link FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=collection_owner.id;
  money:=collection_owner.payload#>'{equation,monetary_event,monetary}';request:=collection_owner.payload->'command_request';
  collection:=jsonb_build_object('id',collection_owner.id,'sequence',collection_owner.sequence,
   'status',CASE collection_owner.phase WHEN 0 THEN'Prepared' WHEN 1 THEN'Reviewed' ELSE'Posted' END,
   'plan_digest',collection_owner.payload->>'plan_digest','amount_minor',request->>'amount_minor',
   'functional_cash_minor',money->>'functional_cash_minor','functional_receivable_released_minor',money->>'functional_receivable_released_minor',
   'functional_fx_gain_minor',money->>'functional_fx_gain_minor','functional_fx_loss_minor',money->>'functional_fx_loss_minor',
   'settlement_rate',request->'settlement_rate','receipt_number','FX1-'||(request->>'receipt_number'),'receipt_date',request->>'receipt_date',
   'period_id',request->>'period_id','preparer_actor_id',collection_owner.payload->>'preparer_actor_id',
   'reviewer_actor_id',collection_review.reviewer_actor_id,'posted_actor_id',collection_link.posted_actor_id,
   'entry_id',collection_owner.entry_id,'posting_effect_id',collection_link.posting_effect_id,'receipt_id',collection_link.receipt_id);
 END IF;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('version',event_owner.version,'actor_id',event_owner.actor_id,'operation',event_owner.operation,
   'reason',event_owner.reason,'status',event_owner.status,'audit_event_id',event_owner.audit_event_id) ORDER BY event_owner.version),'[]') INTO events
  FROM reconforge.stock_sales_events event_owner WHERE event_owner.tenant_id=t AND event_owner.order_id=i;
 RETURN jsonb_build_object('schema_version','stock-sales-monetary-v2','id',i,'workspace_id',stock_owner.workspace_id,
  'organization_id',stock_owner.organization_id,'legal_entity_id',stock_owner.legal_entity_id,'number',stock_owner.number,
  'status',stock_owner.status,'row_version',stock_owner.row_version,'source_digest',stock_owner.source_digest,
  'customer_code',stock_owner.source->>'customer_code','customer_reference',stock_owner.source->>'customer_reference',
  'item_code',stock_owner.source->>'item_code','warehouse_code',stock_owner.source->>'warehouse_code','location_code',stock_owner.source->>'location_code',
  'quantity',stock_owner.source->>'quantity','quantity_scaled',stock_owner.quantity_scaled::text,'quantity_precision',stock_owner.quantity_precision,
  'unit_price_minor',stock_owner.source->>'unit_price_minor','discount_basis_points',stock_owner.source->'discount_basis_points',
  'net_unit_price_minor',stock_owner.source->>'net_unit_price_minor','transaction_net_minor',stock_owner.total_minor::text,
  'description',stock_owner.source->>'description','order_date',stock_owner.source->>'order_date',
  'transaction_policy',reconforge.monetary_full_policy(stock_owner.source->'monetary_policy'),
  'functional_policy',reconforge.monetary_full_policy(stock_owner.source->'functional_policy'),
  'created_by',stock_owner.created_by,'approved_by',stock_owner.approved_by,'issue_preparer_id',stock_owner.issue_plan->>'preparer_actor_id',
  'issue_reviewer_id',stock_owner.issue_reviewer_id,'issue_digest',CASE WHEN stock_owner.issue_plan IS NOT NULL THEN reconforge.irp_digest(stock_owner.issue_plan) ELSE NULL END,
  'functional_cogs_minor',stock_owner.issue_plan->>'total_cost_minor','cogs_entry_id',stock_owner.cogs_entry_id,'cogs_effect_id',stock_owner.cogs_effect_id,
  'movement_id',stock_owner.movement_id,'valuation_id',stock_owner.valuation_id,'cost_admission_policy',stock_owner.issue_plan->>'cost_admission_policy',
  'monetary_origin',origin,'balance',balance,'collection',collection,'events',events);
END $mr149$;
CREATE FUNCTION reconforge.monetary_stock_close(t TEXT,target TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
<<monetary_stock_close>>
DECLARE stock_owner RECORD;origin_owner RECORD;invoice_owner RECORD;member RECORD;command_owner RECORD;prior_event RECORD;
 source JSONB;actual JSONB;balance JSONB;history JSONB;recognition RECORD;initial_review RECORD;collection_owner RECORD;
 expected_status TEXT;next_status TEXT;version INTEGER:=0;stage INTEGER;
BEGIN
 SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=target;source:=stock_owner.source;
 PERFORM reconforge.monetary_return_assert(stock_owner.id IS NOT NULL AND reconforge.irp_scope(t,stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id)
  AND source->>'schema_version'='stock-sales-monetary-order-v2' AND reconforge.irp_digest(source)=stock_owner.source_digest
  AND reconforge.fx_object(source,ARRAY['schema_version','number','customer_code','customer_reference','item_code','warehouse_code','location_code','quantity',
   'unit_price_minor','currency_code','order_date','description','discount_basis_points','net_unit_price_minor','total_minor','tax_minor','discount_policy',
   'monetary_policy','functional_policy','quantity_scaled'])
  AND source->>'number'=stock_owner.number AND source->>'currency_code'=stock_owner.currency_code
  AND source->>'tax_minor'='0' AND source->>'discount_policy'='per-unit-minor-half-up-v1'
  AND reconforge.fx_minor(source->'quantity_scaled') AND(source->>'quantity_scaled')::numeric=stock_owner.quantity_scaled
  AND(source->>'quantity')::numeric*power(10::numeric,stock_owner.quantity_precision)=stock_owner.quantity_scaled
  AND source->>'total_minor'=stock_owner.total_minor::text
  AND round((source->>'unit_price_minor')::numeric*(10000-(source->>'discount_basis_points')::integer)/10000,0)=(source->>'net_unit_price_minor')::numeric
  AND round((source->>'quantity')::numeric*(source->>'net_unit_price_minor')::numeric,0)=stock_owner.total_minor,
  'The fixed original Stock source must reproduce its actual exact transaction quantity, discounted price and net');
 stage:=reconforge.stock_sales_stage(stock_owner.status);
 IF stock_owner.status<>'Cancelled' THEN
  PERFORM reconforge.monetary_return_assert((stage>=2)=(stock_owner.approved_by IS NOT NULL)
   AND(stage>=4)=(stock_owner.issue_plan IS NOT NULL) AND(stage>=5)=(stock_owner.issue_reviewer_id IS NOT NULL)
   AND(stage>=6)=(stock_owner.movement_id IS NOT NULL AND stock_owner.valuation_id IS NOT NULL)
   AND(stage>=7)=(stock_owner.invoice_id IS NOT NULL AND stock_owner.invoice_plan_id IS NOT NULL AND stock_owner.invoice_parameters IS NOT NULL)
   AND(stage<10 OR(stock_owner.collection_plan_id IS NOT NULL AND stock_owner.collection_parameters IS NOT NULL)),
   'Actual native Stock links must exist exactly at their governed source stage');
 END IF;
 PERFORM reconforge.monetary_stock_physical_close(t,target);
 FOR member IN SELECT event_order.* FROM reconforge.stock_sales_events event_order
  WHERE event_order.tenant_id=t AND event_order.order_id=target ORDER BY event_order.version LOOP
  version:=version+1;SELECT * INTO command_owner FROM reconforge.stock_sales_commands WHERE tenant_id=t AND order_id=target AND stock_sales_commands.version=member.version;
  next_status:=CASE member.operation WHEN'create' THEN'Draft' WHEN'submit' THEN'Submitted' WHEN'approve' THEN'Approved' WHEN'reserve' THEN'Reserved'
   WHEN'prepare-issue' THEN'IssuePrepared' WHEN'review-issue' THEN'IssueReviewed' WHEN'deliver' THEN'Delivered'
   WHEN'prepare-invoice' THEN'InvoicePrepared' WHEN'review-invoice' THEN'InvoiceReviewed' WHEN'invoice' THEN'Invoiced'
   WHEN'prepare-collection' THEN'CollectionPrepared' WHEN'review-collection' THEN'CollectionReviewed' WHEN'collect' THEN member.status WHEN'cancel' THEN'Cancelled' END;
  PERFORM reconforge.monetary_return_assert(member.version=version AND command_owner.order_id=target
   AND command_owner.actor_id=member.actor_id AND command_owner.operation=member.operation AND command_owner.request_digest=reconforge.irp_digest(command_owner.request)
   AND command_owner.request->>'id'=target AND command_owner.request->>'actor_id'=member.actor_id AND command_owner.request->>'operation'=member.operation
   AND command_owner.request#>>'{scope,workspace_id}'=stock_owner.workspace_id AND command_owner.request#>>'{scope,organization_id}'=stock_owner.organization_id
   AND command_owner.request#>>'{scope,legal_entity_id}'=stock_owner.legal_entity_id
   AND command_owner.result->>'source_digest'=stock_owner.source_digest AND command_owner.result->>'transaction_net_minor'=stock_owner.total_minor::text
   AND command_owner.result->>'id'=target AND command_owner.result->>'row_version'=member.version::text AND command_owner.result->>'status'=member.status
   AND member.status=next_status AND(member.operation<>'collect' OR member.status IN('Invoiced','Paid'))
   AND((version=1 AND member.operation='create' AND member.actor_id=stock_owner.created_by)
    OR(version>1 AND(command_owner.request#>>'{payload,expected_version}')::integer=version-1 AND command_owner.request#>>'{payload,reason}'=member.reason))
   AND EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit_owner WHERE audit_owner.tenant_id=t AND audit_owner.id=member.audit_event_id
    AND audit_owner.actor_user_id=member.actor_id AND audit_owner.object_type='stock_sales' AND audit_owner.object_id=target
    AND audit_owner.action='stock_sales.'||member.operation AND audit_owner.metadata_json=jsonb_build_object('source_digest',stock_owner.source_digest,'version',version,'status',member.status))
   AND jsonb_array_length(command_owner.result->'events')=version AND NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(command_owner.result->'events') saved WHERE NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_events actual_event
     WHERE actual_event.tenant_id=t AND actual_event.order_id=target AND actual_event.version<=monetary_stock_close.version
     AND saved=jsonb_build_object('version',actual_event.version,'actor_id',actual_event.actor_id,'operation',actual_event.operation,
      'reason',actual_event.reason,'status',actual_event.status,'audit_event_id',actual_event.audit_event_id))),
   'Every Stock lifecycle version must retain its exact native actor, immutable request, public acknowledgement and audit prefix');
 END LOOP;
 PERFORM reconforge.monetary_return_assert(version=stock_owner.row_version AND version BETWEEN 1 AND 1024
  AND(SELECT count(*) FROM reconforge.stock_sales_commands WHERE tenant_id=t AND order_id=target)=version
  AND member.status=stock_owner.status,'The current Stock lifecycle must close its complete native version chain');
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND stock_order_id=target;
 IF origin_owner.id IS NULL THEN
  PERFORM reconforge.monetary_return_assert(stock_owner.invoice_id IS NULL AND stock_owner.invoice_plan_id IS NULL
   AND stock_owner.invoice_parameters IS NULL AND stock_owner.status IN('Draft','Submitted','Approved','Reserved','IssuePrepared','IssueReviewed','Delivered','Cancelled')
   AND NOT EXISTS(SELECT 1 FROM reconforge.operational_fx_sources fx_owner WHERE fx_owner.tenant_id=t AND fx_owner.payload->>'stock_order_id'=target),
   'An absent monetary origin cannot conceal invoice, FX or later-stage ownership');RETURN;
 END IF;
 actual:=reconforge.monetary_stock_origin_payload(t,target,origin_owner.fx_source_id,origin_owner.recognition_plan_id,
  jsonb_build_object('refund_liability_account_code',origin_owner.payload->>'refund_liability_account_code'),FALSE);
 PERFORM reconforge.monetary_return_assert(actual=origin_owner.payload AND reconforge.irp_digest(actual)=origin_owner.source_digest
  AND stock_owner.invoice_id=origin_owner.invoice_id AND stock_owner.invoice_plan_id=origin_owner.recognition_plan_id
  AND NOT EXISTS(SELECT 1 FROM reconforge.customer_return_plans old_owner WHERE old_owner.tenant_id=t AND old_owner.source_order_id=target)
  AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources old_owner WHERE old_owner.tenant_id=t AND old_owner.source_order_id=target),
  'The immutable bridge, typed source and factual source must exactly match real original native rows without legacy double ownership');
 FOR member IN SELECT id FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=origin_owner.fx_source_id ORDER BY sequence LOOP
  PERFORM reconforge.monetary_fx_close(t,member.id);
 END LOOP;
 FOR member IN SELECT id FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND origin_id=origin_owner.id ORDER BY expected_history_version,id LOOP
  PERFORM reconforge.monetary_partial_close(t,member.id);
 END LOOP;
 balance:=reconforge.monetary_stock_balance(t,target);history:=reconforge.monetary_stock_history(t,target);
 PERFORM reconforge.monetary_return_assert(balance=origin_owner.ar_balance,'Published safe AR balances must exactly close the immutable authoritative source and pending identities');
 SELECT * INTO recognition FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=origin_owner.recognition_plan_id;
 SELECT * INTO initial_review FROM reconforge.operational_fx_reviews WHERE tenant_id=t AND plan_id=recognition.id;
 SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=t AND id=origin_owner.invoice_id;
 PERFORM reconforge.monetary_return_assert(recognition.phase=(CASE stock_owner.status WHEN'InvoicePrepared' THEN 0 WHEN'InvoiceReviewed' THEN 1 ELSE 2 END)
  AND stock_owner.status IN('InvoicePrepared','InvoiceReviewed','Invoiced','CollectionPrepared','CollectionReviewed','Paid'),
  'The real original recognition phase must agree with the immutable Stock event lifecycle');
 IF stock_owner.collection_plan_id IS NOT NULL THEN
  SELECT * INTO collection_owner FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=stock_owner.collection_plan_id;
  PERFORM reconforge.monetary_return_assert(collection_owner.source_id=origin_owner.fx_source_id AND collection_owner.kind='settle'
   AND collection_owner.sequence=(SELECT max(sequence) FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=origin_owner.fx_source_id AND kind='settle')
   AND collection_owner.phase=(CASE stock_owner.status WHEN'CollectionPrepared' THEN 0 WHEN'CollectionReviewed' THEN 1 ELSE 2 END)
   AND((collection_owner.payload->'command_request')-ARRAY['kind','source_id','reason'])=stock_owner.collection_parameters,
   'Repeated Stock cash must retain its exact latest native collection owner and request');
 END IF;
 expected_status:=CASE WHEN recognition.phase=0 THEN'Submitted' WHEN balance->>'transaction_outstanding_minor'='0' THEN'Paid'
  WHEN balance->>'transaction_collected_minor'='0' THEN'Approved' ELSE'PartiallyPaid' END;
 PERFORM reconforge.monetary_return_assert(invoice_owner.customer_partial_return_source_id IS NULL AND invoice_owner.customer_return_owner_id IS NULL
  AND invoice_owner.status=expected_status
  AND(SELECT COALESCE(sum(amount_minor),0) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=invoice_owner.id)=(balance->>'transaction_collected_minor')::numeric
  AND NOT EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations allocation WHERE allocation.tenant_id=t AND allocation.invoice_id=invoice_owner.id
   AND NOT EXISTS(SELECT 1 FROM reconforge.operational_fx_links native_link JOIN reconforge.operational_fx_plans native_plan
    ON(native_plan.tenant_id,native_plan.id)=(native_link.tenant_id,native_link.plan_id) WHERE native_plan.tenant_id=t AND native_plan.source_id=origin_owner.fx_source_id
    AND native_plan.kind='settle' AND native_plan.phase=2 AND native_link.receipt_id=allocation.receipt_id))
  AND((recognition.phase=0 AND invoice_owner.approved_by='' AND invoice_owner.approved_at IS NULL)
   OR(recognition.phase>=1 AND invoice_owner.approved_by=(SELECT username FROM reconforge.identity_users WHERE tenant_id=t AND id=initial_review.reviewer_actor_id)
    AND invoice_owner.approved_at IS NOT NULL)),
  'Actual native AR state and complete cash membership must preserve exact credit-adjusted ownership without generic allocation bypass');
END $mr149$;
"""

GUARD_SQL = r"""
CREATE FUNCTION reconforge.monetary_fx_command_actor(table_name TEXT,operation TEXT,old_row JSONB,new_row JSONB) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;source_owner RECORD;stock_owner RECORD;customer_owner RECORD;period_owner RECORD;actor TEXT;permission TEXT;ar_permission TEXT;
BEGIN
 actor:=new_row->>'actor_id';
 SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=new_row->>'tenant_id' AND id=new_row->>'plan_id';
 SELECT * INTO source_owner FROM reconforge.operational_fx_sources WHERE tenant_id=plan_owner.tenant_id AND id=plan_owner.source_id;
 SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=plan_owner.tenant_id AND id=source_owner.payload->>'stock_order_id';
 permission:=CASE new_row->>'operation' WHEN'prepare' THEN'finance_core.manage' WHEN'review' THEN'finance_core.validate' ELSE'finance_core.post' END;
 ar_permission:=CASE new_row->>'operation' WHEN'review' THEN'receivables.approve' ELSE'receivables.manage' END;
 PERFORM reconforge.monetary_return_assert(table_name='operational_fx_commands' AND operation='INSERT'
  AND stock_owner.id IS NOT NULL AND stock_owner.source->>'schema_version'='stock-sales-monetary-order-v2'
  AND actor=current_setting('app.stock_sales_actor_id',true) AND reconforge.sales_revenue_actor(plan_owner.tenant_id,actor,permission)
  AND reconforge.sales_revenue_actor(plan_owner.tenant_id,actor,ar_permission)
  AND reconforge.sales_revenue_actor(plan_owner.tenant_id,actor,'sales.read')
  AND(new_row->>'workspace_id',new_row->>'organization_id',new_row->>'legal_entity_id')=
   (stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id)
  AND(plan_owner.kind<>'reverse_revaluation' OR reconforge.sales_revenue_actor(plan_owner.tenant_id,actor,'finance_core.reverse')),
  'FX commands require the exact fixed Stock owner and current persisted finance, AR, sales and inverse authority');
 SELECT * INTO period_owner FROM reconforge.fiscal_periods WHERE tenant_id=plan_owner.tenant_id AND id=plan_owner.payload->>'period_id' FOR SHARE;
 SELECT * INTO customer_owner FROM reconforge.ar_customers WHERE tenant_id=plan_owner.tenant_id AND id=stock_owner.customer_id;
 PERFORM reconforge.monetary_return_assert(period_owner.id IS NOT NULL AND period_owner.status='Open'
  AND(plan_owner.payload->>'posting_date')::date BETWEEN period_owner.start_date AND period_owner.end_date
  AND customer_owner.status='Active' AND reconforge.irp_scope(plan_owner.tenant_id,stock_owner.workspace_id,stock_owner.organization_id,stock_owner.legal_entity_id),
  'Every FX phase requires current open-period and active native customer authority');
 IF plan_owner.kind='recognize' AND new_row->>'operation'='review' THEN
  PERFORM reconforge.monetary_return_assert(NOT customer_owner.credit_hold AND customer_owner.credit_limit_minor>=(
   SELECT COALESCE(sum(greatest(invoice.total_minor::numeric-
    COALESCE((SELECT sum(allocation.amount_minor) FROM reconforge.ar_receipt_allocations allocation WHERE allocation.tenant_id=invoice.tenant_id AND allocation.invoice_id=invoice.id),0)
    -reconforge.monetary_stock_invoice_credit(invoice.tenant_id,invoice.id)
    -CASE WHEN invoice.customer_partial_return_source_id IS NOT NULL THEN reconforge.customer_partial_return_credit(invoice.tenant_id,invoice.id) ELSE 0 END,0)),0)
   FROM reconforge.ar_invoices invoice WHERE invoice.tenant_id=plan_owner.tenant_id AND invoice.customer_id=customer_owner.id AND invoice.status IN('Approved','PartiallyPaid')),
   'Recognition review must enforce the actual native credit limit against gross current credit-adjusted exposure');
 END IF;
END $mr149$;
CREATE FUNCTION reconforge.monetary_return_authority(t TEXT,actor TEXT,operation TEXT,period_id TEXT,day TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE period_owner RECORD;
BEGIN
 PERFORM reconforge.monetary_return_assert(actor IS NOT NULL AND reconforge.customer_return_authority(t,actor,operation),
  'Monetary corrections require current persisted independent human authority');
 SELECT * INTO period_owner FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=period_id FOR SHARE;
 PERFORM reconforge.monetary_return_assert(period_owner.id IS NOT NULL AND period_owner.status='Open'
  AND day::date BETWEEN period_owner.start_date AND period_owner.end_date,'Monetary corrections require the actual current open posting period');
END $mr149$;
CREATE FUNCTION reconforge.monetary_return_protect() RETURNS TRIGGER
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE changed JSONB;previous JSONB;plan_owner RECORD;origin_owner RECORD;stock_owner RECORD;part JSONB;
 actor TEXT:=current_setting('app.customer_partial_return_monetary_actor_id',true);stock_actor TEXT:=current_setting('app.stock_sales_actor_id',true);
 kind TEXT;operation TEXT;expected JSONB;prefix JSONB;poster TEXT;reviewer TEXT;
BEGIN
 IF TG_OP='DELETE' THEN PERFORM reconforge.monetary_return_assert(FALSE,'Monetary original, command, financial and physical history is immutable');END IF;
 changed:=to_jsonb(NEW);IF TG_OP='UPDATE' THEN previous:=to_jsonb(OLD);END IF;
 IF TG_TABLE_NAME='stock_sales_monetary_origins' THEN
  IF TG_OP='INSERT' THEN
   expected:=reconforge.monetary_stock_origin_payload(NEW.tenant_id,NEW.stock_order_id,NEW.fx_source_id,NEW.recognition_plan_id,
    jsonb_build_object('refund_liability_account_code',NEW.payload->>'refund_liability_account_code'),TRUE);
   PERFORM reconforge.monetary_return_assert(expected=NEW.payload AND reconforge.irp_digest(expected)=NEW.source_digest
    AND NEW.id=expected#>>'{source,source_id}' AND NEW.invoice_id=expected#>>'{source,invoice_id}',
    'New monetary origin rows require the actual before-review native Stock/FX/AR/FIFO birth proof');
  ELSE
   PERFORM reconforge.monetary_return_assert(changed-'ar_balance'=previous-'ar_balance'
    AND NEW.ar_balance=reconforge.monetary_stock_balance(NEW.tenant_id,NEW.stock_order_id)
    AND((actor IS NOT NULL AND(reconforge.customer_return_authority(NEW.tenant_id,actor,'prepare')
     OR reconforge.customer_return_authority(NEW.tenant_id,actor,'review') OR reconforge.customer_return_authority(NEW.tenant_id,actor,'post')
     OR reconforge.customer_return_authority(NEW.tenant_id,actor,'cancel')))
     OR(stock_actor IS NOT NULL AND(reconforge.sales_revenue_actor(NEW.tenant_id,stock_actor,'finance_core.manage')
      OR reconforge.sales_revenue_actor(NEW.tenant_id,stock_actor,'finance_core.validate') OR reconforge.sales_revenue_actor(NEW.tenant_id,stock_actor,'finance_core.post')))),
    'Only exact governed pending identity or monetary prefix publication may change the safe AR projection');
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='customer_partial_return_monetary_plans' THEN
  SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=NEW.tenant_id AND id=NEW.origin_id;
  IF TG_OP='INSERT' THEN operation:='prepare';
   PERFORM reconforge.monetary_return_assert(NEW.phase=0 AND NEW.payload->>'preparer_actor_id'=actor
    AND NEW.expected_history_version=jsonb_array_length(reconforge.monetary_stock_history(NEW.tenant_id,origin_owner.stock_order_id)->'events')
    AND(reconforge.monetary_stock_fx_state(NEW.tenant_id,origin_owner.stock_order_id)->>'recognized')::boolean
    AND reconforge.monetary_stock_fx_state(NEW.tenant_id,origin_owner.stock_order_id)->>'active_revaluation_plan_id' IS NULL
    AND NOT EXISTS(SELECT 1 FROM reconforge.operational_fx_plans competing WHERE competing.tenant_id=NEW.tenant_id AND competing.source_id=origin_owner.fx_source_id AND competing.phase<2),
    'Only the next current source prefix without pending cash or closing valuation may prepare a monetary correction');
  ELSE
   operation:=CASE NEW.phase WHEN 1 THEN'review' WHEN 2 THEN'post' ELSE'cancel' END;
   PERFORM reconforge.monetary_return_assert(changed-'phase'=previous-'phase' AND((OLD.phase=0 AND NEW.phase IN(1,3)) OR(OLD.phase=1 AND NEW.phase IN(2,3))),
    'The exact immutable monetary plan permits only its next governed phase or cancellation');
  END IF;
  PERFORM reconforge.monetary_return_authority(NEW.tenant_id,actor,operation,NEW.payload->>'period_id',NEW.payload->>'posting_date');
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='customer_partial_return_monetary_history' THEN
  SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=NEW.tenant_id AND id=NEW.origin_id;
  PERFORM reconforge.monetary_return_assert(TG_OP='INSERT','Ordered monetary history cannot be replaced');
  IF NEW.kind='Collection' THEN
   SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.stock_fx_plan_id;
   SELECT posted_actor_id INTO poster FROM reconforge.operational_fx_links WHERE tenant_id=NEW.tenant_id AND plan_id=plan_owner.id;
   PERFORM reconforge.monetary_return_assert(plan_owner.kind='settle' AND plan_owner.phase=2 AND plan_owner.source_id=origin_owner.fx_source_id
    AND plan_owner.payload#>'{equation,monetary_event}'=NEW.payload AND stock_actor=poster
    AND reconforge.sales_revenue_actor(NEW.tenant_id,poster,'finance_core.post') AND reconforge.sales_revenue_actor(NEW.tenant_id,poster,'receivables.manage'),
    'Collection history requires the real current native cash poster and exact owned source effect');
  ELSE
   SELECT * INTO plan_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.partial_plan_id;
   SELECT actor_id INTO poster FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=NEW.tenant_id AND plan_id=plan_owner.id AND customer_partial_return_monetary_events.operation='post';
   PERFORM reconforge.monetary_return_assert(plan_owner.phase=2 AND plan_owner.origin_id=origin_owner.id AND plan_owner.operation=NEW.kind
    AND plan_owner.payload->'monetary_event'=NEW.payload AND actor=poster,'Partial history requires its exact actual current native poster and plan');
   PERFORM reconforge.monetary_return_authority(NEW.tenant_id,actor,'post',plan_owner.payload->>'period_id',plan_owner.payload->>'posting_date');
  END IF;
  prefix:=reconforge.monetary_stock_history(NEW.tenant_id,origin_owner.stock_order_id)->'events';
  expected:=reconforge.monetary_return_next(origin_owner.payload->'source',prefix,NEW.kind,(NEW.payload->>'quantity_scaled')::bigint,
   (NEW.payload->>'amount_minor')::bigint,NEW.payload->>'posting_date',NULLIF(NEW.payload->'settlement_rate','null'::jsonb),NEW.original_sequence);
  PERFORM reconforge.monetary_return_assert(expected=NEW.payload AND NEW.sequence=jsonb_array_length(prefix)+1
   AND NEW.previous_digest=expected->>'previous_history_fingerprint' AND NEW.event_digest=reconforge.irp_digest(expected),
   'An immutable economic event must exactly derive from the currently visible ordered original prefix');
  RETURN NEW;
 END IF;
 SELECT * INTO plan_owner FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'plan_id';
 SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=plan_owner.tenant_id AND id=plan_owner.origin_id;
 PERFORM reconforge.monetary_return_assert(plan_owner.id IS NOT NULL,'Every monetary child requires its complete visible native plan');
 IF TG_TABLE_NAME='customer_partial_return_monetary_entries' THEN
  operation:=CASE TG_OP WHEN'INSERT' THEN'prepare' ELSE'post' END;
  PERFORM reconforge.monetary_return_assert((TG_OP='INSERT' AND plan_owner.phase=0 AND plan_owner.payload->>'preparer_actor_id'=actor)
   OR(TG_OP='UPDATE' AND plan_owner.phase=1 AND OLD.posting_effect_id IS NULL AND NEW.posting_effect_id IS NOT NULL
    AND changed-'posting_effect_id'=previous-'posting_effect_id'),'Financial membership and original snapshots are immutable after native birth');
 ELSIF TG_TABLE_NAME='customer_partial_return_monetary_events' THEN
  operation:=NEW.operation;
  PERFORM reconforge.monetary_return_assert(TG_OP='INSERT' AND NEW.actor_id=actor
   AND plan_owner.phase=(CASE operation WHEN'prepare' THEN 0 WHEN'review' THEN 0 WHEN'post' THEN 1 ELSE plan_owner.phase END)
   AND(operation<>'cancel' OR plan_owner.phase IN(0,1)),'Lifecycle evidence requires its exact current native actor and phase');
 ELSIF TG_TABLE_NAME='customer_partial_return_monetary_commands' THEN
  operation:=CASE WHEN NEW.operation LIKE'prepare%' THEN'prepare' ELSE NEW.operation END;
  PERFORM reconforge.monetary_return_assert(TG_OP='INSERT' AND NEW.actor_id=actor
   AND NEW.response_json=reconforge.monetary_partial_public(NEW.tenant_id,plan_owner.id),
   'Native command birth must capture the complete exact current public acknowledgement');
 ELSE
  operation:='post';
  SELECT value INTO part FROM jsonb_array_elements(plan_owner.payload#>'{monetary_event,portions}') WHERE(value->>'position')::integer=NEW.position;
  PERFORM reconforge.monetary_return_assert(TG_OP='INSERT' AND plan_owner.phase=1 AND part IS NOT NULL
   AND NEW.direction=(CASE plan_owner.operation WHEN'Return' THEN 1 WHEN'ReverseReturn' THEN -1 ELSE 0 END)
   AND NEW.origin_id=plan_owner.origin_id AND NEW.physical_movement_id=plan_owner.payload->>'movement_id'
   AND(NEW.original_consumption_id,NEW.original_valuation_line_id,NEW.cost_layer_id,NEW.before_quantity_scaled,NEW.before_value_minor,NEW.quantity_scaled,NEW.value_minor)=
    (part->>'original_consumption_id',part->>'original_valuation_line_id',part->>'cost_layer_id',(part->>'before_quantity_scaled')::bigint,
     (part->>'before_value_minor')::bigint,(part->>'quantity_scaled')::bigint,(part->>'value_minor')::bigint)
   AND NEW.consumption_count_at_restore=(SELECT count(*) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id)
   AND NEW.original_restoration_plan_id IS NOT DISTINCT FROM(CASE WHEN NEW.direction=-1 THEN plan_owner.original_id ELSE NULL END)
   AND NEW.correction_effect_id IS NOT DISTINCT FROM(SELECT posting_effect_id FROM reconforge.customer_partial_return_monetary_entries
    WHERE tenant_id=NEW.tenant_id AND plan_id=plan_owner.id AND purpose IN('CostRestoration','ReverseCostRestoration')),
   'Each immutable restoration requires the exact original consumption, before-value witness, signed owner and actual cost effect');
  IF NEW.direction=-1 THEN
   PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations original
    WHERE original.tenant_id=NEW.tenant_id AND original.plan_id=plan_owner.original_id AND original.position=NEW.position
    AND original.direction=1 AND original.consumption_count_at_restore=NEW.consumption_count_at_restore),
    'Any later native consumption prevents reversal of the original restored pool');
  END IF;
  PERFORM reconforge.monetary_return_physical(NEW.tenant_id,plan_owner.id,TRUE);
 END IF;
 PERFORM reconforge.monetary_return_authority(plan_owner.tenant_id,actor,operation,plan_owner.payload->>'period_id',plan_owner.payload->>'posting_date');
 RETURN NEW;
END $mr149$;
"""

NAMESPACE_SQL = r"""
CREATE FUNCTION reconforge.monetary_namespace() RETURNS TRIGGER
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE changed JSONB;origin_owner RECORD;source_owner RECORD;plan_owner RECORD;stock_owner RECORD;review_owner RECORD;invoice_owner RECORD;
 actor TEXT:=current_setting('app.stock_sales_actor_id',true);partial_actor TEXT:=current_setting('app.customer_partial_return_monetary_actor_id',true);
 expected JSONB;prefix JSONB;amount NUMERIC;
BEGIN
 IF TG_OP='DELETE' THEN
  IF TG_TABLE_NAME IN('ar_invoice_lines','ar_receipt_allocations') THEN
   SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND id=OLD.invoice_id;
   IF invoice_owner.organization_id IS NOT NULL AND invoice_owner.legal_entity_id IS NOT NULL THEN
    PERFORM reconforge.monetary_return_assert(reconforge.irp_scope(invoice_owner.tenant_id,invoice_owner.workspace_id,invoice_owner.organization_id,invoice_owner.legal_entity_id),
     'Deleting a native invoice child cannot hide original ownership under another current scope');
   END IF;
   SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=OLD.tenant_id AND invoice_id=OLD.invoice_id;
   PERFORM reconforge.monetary_return_assert(origin_owner.id IS NULL,'Original monetary invoice lines and receipt allocations are immutable history');
  END IF;
  RETURN OLD;
 END IF;
 changed:=to_jsonb(NEW);
 IF TG_TABLE_NAME IN('ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations') THEN
  IF TG_TABLE_NAME='ar_invoices' THEN SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
  ELSIF TG_TABLE_NAME IN('ar_invoice_lines','ar_receipt_allocations') THEN SELECT * INTO invoice_owner FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.invoice_id;
  END IF;
  IF TG_TABLE_NAME='ar_receipts' THEN
   IF NEW.organization_id IS NOT NULL AND NEW.legal_entity_id IS NOT NULL THEN
    PERFORM reconforge.monetary_return_assert(reconforge.irp_scope(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),
     'A fully scoped native receipt cannot conceal source ownership under another child scope');
   END IF;
  ELSIF TG_TABLE_NAME='ar_invoices' THEN
   IF NEW.organization_id IS NOT NULL AND NEW.legal_entity_id IS NOT NULL THEN
    PERFORM reconforge.monetary_return_assert(reconforge.irp_scope(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),
     'A fully scoped native invoice cannot conceal source ownership under another child scope');
   END IF;
  ELSE
   IF invoice_owner.organization_id IS NOT NULL AND invoice_owner.legal_entity_id IS NOT NULL THEN
    PERFORM reconforge.monetary_return_assert(reconforge.irp_scope(invoice_owner.tenant_id,invoice_owner.workspace_id,invoice_owner.organization_id,invoice_owner.legal_entity_id),
     'A native invoice child cannot hide monetary ownership by choosing another current scope');
   END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='finance_entries' THEN
  IF upper(NEW.entry_number)~'^(CR3|CRF3|CR3R|CRF3R)-[A-F0-9]{32}-[RCF]$' THEN
   PERFORM reconforge.monetary_return_assert(partial_actor IS NOT NULL
    AND((TG_OP='INSERT' AND reconforge.sales_revenue_actor(NEW.tenant_id,partial_actor,'finance_core.manage'))
     OR(TG_OP='UPDATE' AND(reconforge.sales_revenue_actor(NEW.tenant_id,partial_actor,'finance_core.manage')
      OR reconforge.sales_revenue_actor(NEW.tenant_id,partial_actor,'finance_core.validate') OR reconforge.sales_revenue_actor(NEW.tenant_id,partial_actor,'finance_core.post')))),
    'Reserved monetary correction journals require their current governed source actor');
  END IF;
 ELSIF TG_TABLE_NAME='operational_fx_sources' THEN
  IF NEW.payload->>'schema_version'='operational-fx-stock-source-v2' THEN
   SELECT * INTO stock_owner FROM reconforge.stock_sales_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.payload->>'stock_order_id';
   PERFORM reconforge.monetary_return_assert(TG_OP='INSERT' AND stock_owner.id IS NOT NULL
    AND stock_owner.source->>'schema_version'='stock-sales-monetary-order-v2' AND stock_owner.status='Delivered'
    AND NEW.payload->>'stock_source_digest'=stock_owner.source_digest AND actor=NEW.payload->>'preparer_actor_id'
    AND reconforge.sales_revenue_actor(NEW.tenant_id,actor,'sales.manage') AND reconforge.sales_revenue_actor(NEW.tenant_id,actor,'finance_core.manage')
    AND reconforge.sales_revenue_actor(NEW.tenant_id,actor,'receivables.manage'),
    'Monetary FX source birth cannot retrofit or bypass the actual fixed delivered Stock owner');
  END IF;
 ELSIF TG_TABLE_NAME='operational_fx_plans' THEN
  IF NEW.entry_id IS NULL THEN
   SELECT * INTO source_owner FROM reconforge.operational_fx_sources WHERE tenant_id=NEW.tenant_id AND id=NEW.source_id;
   SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=NEW.tenant_id AND fx_source_id=NEW.source_id;
   PERFORM reconforge.monetary_return_assert(source_owner.payload->>'schema_version'='operational-fx-stock-source-v2'
    AND origin_owner.id IS NOT NULL AND NEW.kind='settle' AND NEW.payload->>'schema_version'='operational-fx-stock-plan-v2'
    AND NEW.payload->'amount_minor'='0'::jsonb AND NEW.payload#>'{equation,lines}'='[]'::jsonb,
    'Legacy or nonzero FX plans cannot omit their native functional journal');
   prefix:=reconforge.monetary_stock_prefix(NEW.tenant_id,origin_owner.stock_order_id,(NEW.payload#>>'{equation,monetary_event,sequence}')::integer-1);
   expected:=reconforge.monetary_return_next(origin_owner.payload->'source',prefix,'Collection',0,
    (NEW.payload#>>'{command_request,amount_minor}')::bigint,NEW.payload->>'posting_date',
    NULLIF(NEW.payload#>'{command_request,settlement_rate}','null'::jsonb),NULL);
   PERFORM reconforge.monetary_return_assert(expected=NEW.payload#>'{equation,monetary_event}'
    AND expected#>'{monetary,functional_turnover_minor}'='0'::jsonb,'Absent journal admission must retain the exact actual zero-turnover prefix');
  END IF;
 ELSIF TG_TABLE_NAME='operational_fx_links' THEN
  IF NEW.posting_effect_id IS NULL THEN
   SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
   SELECT * INTO source_owner FROM reconforge.operational_fx_sources WHERE tenant_id=NEW.tenant_id AND id=plan_owner.source_id;
   PERFORM reconforge.monetary_return_assert(source_owner.payload->>'schema_version'='operational-fx-stock-source-v2'
    AND plan_owner.entry_id IS NULL AND plan_owner.kind='settle' AND plan_owner.phase=1
    AND plan_owner.payload->'amount_minor'='0'::jsonb AND NEW.receipt_id IS NOT NULL
    AND NEW.posted_actor_id=actor AND reconforge.sales_revenue_actor(NEW.tenant_id,actor,'finance_core.post'),
    'A missing FX effect requires the exact actual zero-turnover collection and current posting human');
  END IF;
 ELSIF TG_TABLE_NAME='ar_receipt_allocations' THEN
  SELECT * INTO origin_owner FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=NEW.tenant_id AND invoice_id=NEW.invoice_id;
  IF origin_owner.id IS NOT NULL THEN
   PERFORM reconforge.monetary_return_assert(TG_OP='INSERT','Owned monetary receipt allocations cannot be changed after original posting');
   SELECT * INTO plan_owner FROM reconforge.operational_fx_plans WHERE tenant_id=NEW.tenant_id AND source_id=origin_owner.fx_source_id AND kind='settle' AND phase=1;
   SELECT * INTO review_owner FROM reconforge.operational_fx_reviews WHERE tenant_id=NEW.tenant_id AND plan_id=plan_owner.id;
   PERFORM reconforge.monetary_return_assert(plan_owner.id IS NOT NULL AND NEW.amount_minor=(plan_owner.payload#>>'{equation,foreign_minor}')::numeric
    AND actor<>plan_owner.payload->>'preparer_actor_id' AND actor<>review_owner.reviewer_actor_id
    AND reconforge.sales_revenue_actor(NEW.tenant_id,actor,'finance_core.post') AND reconforge.sales_revenue_actor(NEW.tenant_id,actor,'receivables.manage'),
    'Generic AR allocation cannot bypass the exact reviewed monetary Stock collection and its third human');
  END IF;
 END IF;
 RETURN NEW;
END $mr149$;
CREATE FUNCTION reconforge.monetary_return_native_close() RETURNS TRIGGER
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
<<monetary_return_native_close>>
DECLARE changed JSONB;previous JSONB;current_row JSONB;tenant TEXT;stock_id TEXT;entry_id TEXT;movement_id TEXT;invoice_id TEXT;plan_id TEXT;origin_id TEXT;
 member RECORD;origin_owner RECORD;candidate RECORD;reference TEXT;affected JSONB:='[]'::jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN previous:=to_jsonb(OLD);END IF;IF TG_OP<>'DELETE' THEN current_row:=to_jsonb(NEW);END IF;
 IF TG_TABLE_NAME='outbox_events' AND TG_OP='UPDATE'
 AND(previous-ARRAY['status','attempt_count','available_at','claimed_at','claimed_by','published_at','last_error','dead_lettered_at','lease_generation'])
  IS NOT DISTINCT FROM(current_row-ARRAY['status','attempt_count','available_at','claimed_at','claimed_by','published_at','last_error','dead_lettered_at','lease_generation']) THEN
  RETURN NEW;
 END IF;
 FOR changed IN SELECT previous WHERE previous IS NOT NULL UNION SELECT current_row WHERE current_row IS NOT NULL LOOP
  tenant:=changed->>'tenant_id';entry_id:=NULL;movement_id:=NULL;invoice_id:=NULL;plan_id:=NULL;origin_id:=NULL;stock_id:=NULL;
  IF(TG_TABLE_NAME='domain_audit_events' AND COALESCE(changed->>'object_type','') NOT IN('operational_finance','stock_sales'))
   OR(TG_TABLE_NAME='outbox_events' AND COALESCE(changed->>'aggregate_type','') NOT IN('operational_finance','stock_sales')) THEN
   CONTINUE;
  END IF;
  IF TG_TABLE_NAME='stock_sales_monetary_origins' THEN stock_id:=changed->>'stock_order_id';
  ELSIF TG_TABLE_NAME='customer_partial_return_monetary_plans' THEN origin_id:=changed->>'origin_id';
  ELSIF TG_TABLE_NAME IN('customer_partial_return_monetary_history','customer_partial_return_monetary_restorations') THEN origin_id:=changed->>'origin_id';
  ELSIF TG_TABLE_NAME LIKE'customer_partial_return_monetary_%' THEN plan_id:=changed->>'plan_id';
  ELSIF TG_TABLE_NAME='operational_fx_sources' THEN
   SELECT fixed.stock_order_id INTO stock_id FROM reconforge.stock_sales_monetary_origins fixed WHERE fixed.tenant_id=tenant AND fixed.fx_source_id=changed->>'id';
  ELSIF TG_TABLE_NAME IN('operational_fx_plans','operational_fx_reviews','operational_fx_links','operational_fx_commands') THEN
   SELECT fixed.stock_order_id INTO stock_id FROM reconforge.stock_sales_monetary_origins fixed
    JOIN reconforge.operational_fx_plans fx_plan ON(fx_plan.tenant_id,fx_plan.source_id)=(fixed.tenant_id,fixed.fx_source_id)
    WHERE fixed.tenant_id=tenant AND fx_plan.id=(CASE WHEN TG_TABLE_NAME='operational_fx_plans' THEN changed->>'id' ELSE changed->>'plan_id' END);
  ELSIF TG_TABLE_NAME='finance_entries' THEN entry_id:=changed->>'id';
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN entry_id:=changed->>'entry_id';
  ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN
   SELECT entry_line.entry_id INTO entry_id FROM reconforge.finance_entry_lines entry_line WHERE entry_line.tenant_id=tenant AND entry_line.id=changed->>'entry_line_id';
  ELSIF TG_TABLE_NAME='inventory_movements' THEN movement_id:=changed->>'id';
  ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN movement_id:=changed->>'movement_id';
  ELSIF TG_TABLE_NAME='inventory_valuation_documents' THEN movement_id:=changed->>'movement_id';
  ELSIF TG_TABLE_NAME='inventory_valuation_lines' THEN
   SELECT document.movement_id INTO movement_id FROM reconforge.inventory_valuation_documents document WHERE document.tenant_id=tenant AND document.id=changed->>'valuation_document_id';
  ELSIF TG_TABLE_NAME='inventory_layer_consumptions' THEN
   SELECT document.movement_id INTO movement_id FROM reconforge.inventory_valuation_lines detail JOIN reconforge.inventory_valuation_documents document
    ON(document.tenant_id,document.id)=(detail.tenant_id,detail.valuation_document_id) WHERE detail.tenant_id=tenant AND detail.id=changed->>'valuation_line_id';
  ELSIF TG_TABLE_NAME='ar_invoices' THEN invoice_id:=changed->>'id';
  ELSIF TG_TABLE_NAME IN('ar_invoice_lines','ar_receipt_allocations') THEN invoice_id:=changed->>'invoice_id';
  ELSIF TG_TABLE_NAME='ar_receipts' THEN
   SELECT fixed.stock_order_id INTO stock_id FROM reconforge.stock_sales_monetary_origins fixed
    JOIN reconforge.operational_fx_plans fx_plan ON(fx_plan.tenant_id,fx_plan.source_id)=(fixed.tenant_id,fixed.fx_source_id)
    JOIN reconforge.operational_fx_links fx_link ON(fx_link.tenant_id,fx_link.plan_id)=(fx_plan.tenant_id,fx_plan.id)
    WHERE fixed.tenant_id=tenant AND fx_link.receipt_id=changed->>'id';
  ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN
   FOR candidate IN SELECT fixed.stock_order_id FROM reconforge.stock_sales_monetary_origins fixed
    JOIN reconforge.customer_partial_return_monetary_plans partial_plan ON(partial_plan.tenant_id,partial_plan.origin_id)=(fixed.tenant_id,fixed.id)
    JOIN reconforge.customer_partial_return_monetary_events event_owner ON(event_owner.tenant_id,event_owner.plan_id)=(partial_plan.tenant_id,partial_plan.id)
    WHERE fixed.tenant_id=tenant AND(event_owner.audit_event_id=changed->>'id' OR event_owner.outbox_event_id=changed->>'event_id')
    UNION SELECT fixed.stock_order_id FROM reconforge.stock_sales_monetary_origins fixed
    JOIN reconforge.operational_fx_plans fx_plan ON(fx_plan.tenant_id,fx_plan.source_id)=(fixed.tenant_id,fixed.fx_source_id)
    LEFT JOIN reconforge.operational_fx_reviews fx_review ON(fx_review.tenant_id,fx_review.plan_id)=(fx_plan.tenant_id,fx_plan.id)
    LEFT JOIN reconforge.operational_fx_links fx_link ON(fx_link.tenant_id,fx_link.plan_id)=(fx_plan.tenant_id,fx_plan.id)
    WHERE fixed.tenant_id=tenant AND(changed->>'id' IN(fx_plan.audit_event_id,fx_review.audit_event_id,fx_link.audit_event_id)
     OR changed->>'event_id' IN(fx_plan.outbox_event_id,fx_review.outbox_event_id,fx_link.outbox_event_id)) LOOP
    affected:=affected||jsonb_build_array(jsonb_build_array(tenant,candidate.stock_order_id));
   END LOOP;
  END IF;
  IF plan_id IS NOT NULL THEN SELECT owned.origin_id INTO origin_id FROM reconforge.customer_partial_return_monetary_plans owned WHERE owned.tenant_id=tenant AND owned.id=plan_id;END IF;
  IF origin_id IS NOT NULL THEN SELECT owned.stock_order_id INTO stock_id FROM reconforge.stock_sales_monetary_origins owned WHERE owned.tenant_id=tenant AND owned.id=origin_id;END IF;
  IF invoice_id IS NOT NULL THEN SELECT owned.stock_order_id INTO stock_id FROM reconforge.stock_sales_monetary_origins owned
   WHERE owned.tenant_id=tenant AND owned.invoice_id=monetary_return_native_close.invoice_id;END IF;
  IF entry_id IS NOT NULL THEN
   FOR candidate IN SELECT fixed.stock_order_id FROM reconforge.stock_sales_monetary_origins fixed
    JOIN reconforge.customer_partial_return_monetary_plans partial_plan ON(partial_plan.tenant_id,partial_plan.origin_id)=(fixed.tenant_id,fixed.id)
    JOIN reconforge.customer_partial_return_monetary_entries journal ON(journal.tenant_id,journal.plan_id)=(partial_plan.tenant_id,partial_plan.id)
    WHERE fixed.tenant_id=tenant AND journal.entry_id=monetary_return_native_close.entry_id
    UNION SELECT fixed.stock_order_id FROM reconforge.stock_sales_monetary_origins fixed
    JOIN reconforge.operational_fx_plans fx_plan ON(fx_plan.tenant_id,fx_plan.source_id)=(fixed.tenant_id,fixed.fx_source_id)
    WHERE fixed.tenant_id=tenant AND fx_plan.entry_id=monetary_return_native_close.entry_id
    UNION SELECT fixed.id FROM reconforge.stock_sales_orders fixed WHERE fixed.tenant_id=tenant AND fixed.cogs_entry_id=monetary_return_native_close.entry_id
     AND fixed.source->>'schema_version'='stock-sales-monetary-order-v2' LOOP
    affected:=affected||jsonb_build_array(jsonb_build_array(tenant,candidate.stock_order_id));
   END LOOP;
   SELECT entry.external_reference INTO reference FROM reconforge.finance_entries entry WHERE entry.tenant_id=tenant AND entry.id=monetary_return_native_close.entry_id;
   IF reference~'^(CR3|CRF3|CR3R|CRF3R)-[0-9a-f]{32}$' THEN
    PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_entries journal
     WHERE journal.tenant_id=tenant AND journal.plan_id=reference AND journal.entry_id=monetary_return_native_close.entry_id),
     'A correction reference cannot be borrowed by an unreserved extra native entry');
   END IF;
   IF TG_TABLE_NAME='finance_entries' AND upper(changed->>'entry_number')~'^(CR3|CRF3|CR3R|CRF3R)-[A-F0-9]{32}-[RCF]$' THEN
    PERFORM reconforge.monetary_return_assert(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_entries journal
     WHERE journal.tenant_id=tenant AND journal.entry_id=monetary_return_native_close.entry_id),'Reserved correction entry numbers require exact native financial membership');
   END IF;
  END IF;
  IF movement_id IS NOT NULL THEN
   SELECT physical.source_reference INTO reference FROM reconforge.inventory_movements physical WHERE physical.tenant_id=tenant AND physical.id=monetary_return_native_close.movement_id;
   IF reference~'^(CR3|CR3R)-[0-9a-f]{32}$' THEN
    SELECT * INTO member FROM reconforge.customer_partial_return_monetary_plans owned WHERE owned.tenant_id=tenant AND owned.id=reference;
    PERFORM reconforge.monetary_return_assert(member.id IS NOT NULL AND member.payload->>'movement_id'=monetary_return_native_close.movement_id,
     'A correction source cannot be borrowed by an extra or renamed physical movement');
    SELECT fixed.stock_order_id INTO stock_id FROM reconforge.stock_sales_monetary_origins fixed WHERE fixed.tenant_id=tenant AND fixed.id=member.origin_id;
   ELSE
    SELECT fixed.id INTO stock_id FROM reconforge.stock_sales_orders fixed WHERE fixed.tenant_id=tenant AND fixed.id=reference
     AND fixed.source->>'schema_version'='stock-sales-monetary-order-v2';
   END IF;
  END IF;
  IF stock_id IS NOT NULL THEN affected:=affected||jsonb_build_array(jsonb_build_array(tenant,stock_id));END IF;
 END LOOP;
 FOR candidate IN SELECT DISTINCT (affected_item.value->>0) COLLATE "C" AS tenant_id,(affected_item.value->>1) COLLATE "C" AS stock_order_id
  FROM jsonb_array_elements(affected) affected_item(value) ORDER BY 1,2 LOOP
  PERFORM reconforge.monetary_stock_close(candidate.tenant_id,candidate.stock_order_id);
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
END $mr149$;
"""

EFFECT_SQL = r"""
CREATE FUNCTION reconforge.monetary_posted_close(t TEXT,i TEXT,f TEXT,o TEXT,e TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE entry_owner RECORD;effect_owner RECORD;snapshot JSONB;
BEGIN
 SELECT * INTO entry_owner FROM reconforge.finance_entries WHERE tenant_id=t AND id=i;
 SELECT * INTO effect_owner FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=f;
 snapshot:=reconforge.fr_snapshot(t,i,o,e);
 PERFORM reconforge.monetary_return_assert(entry_owner.id IS NOT NULL AND effect_owner.id IS NOT NULL
  AND entry_owner.status='Validated' AND entry_owner.validation_contract_version='finance-entry-review-v1'
  AND effect_owner.entry_id=i AND effect_owner.source_id=COALESCE(entry_owner.reverses_posting_id,i) AND effect_owner.purpose='operational_posting'
  AND effect_owner.source_kind=(CASE WHEN entry_owner.reverses_posting_id IS NULL THEN'Manual' ELSE'Reversal' END)
  AND effect_owner.reverses_effect_id IS NOT DISTINCT FROM entry_owner.reverses_posting_id
  AND effect_owner.validation_contract_version='finance-entry-review-v1' AND effect_owner.snapshot_json=snapshot
  AND effect_owner.validation_digest=reconforge.irp_digest(snapshot) AND effect_owner.validation_digest=entry_owner.validation_digest
  AND(effect_owner.workspace_id,effect_owner.organization_id,effect_owner.legal_entity_id)=(entry_owner.workspace_id,o,e)
  AND(effect_owner.currency_code,effect_owner.currency_precision,effect_owner.currency_rounding_policy,effect_owner.currency_registry_version,effect_owner.currency_registry_digest)=
   (entry_owner.currency_code,entry_owner.currency_precision,entry_owner.currency_rounding_policy,entry_owner.currency_registry_version,entry_owner.currency_registry_digest)
  AND entry_owner.validator_actor_id<>entry_owner.preparer_actor_id AND effect_owner.posted_actor_id<>entry_owner.validator_actor_id
  AND effect_owner.posted_actor_id<>entry_owner.preparer_actor_id
  AND EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit_owner JOIN reconforge.outbox_events outbox_owner ON outbox_owner.tenant_id=audit_owner.tenant_id
   WHERE audit_owner.tenant_id=t AND audit_owner.id=effect_owner.audit_event_id AND outbox_owner.event_id=effect_owner.outbox_event_id
   AND audit_owner.actor_user_id=effect_owner.posted_actor_id AND audit_owner.object_type='finance_posting' AND audit_owner.object_id=f
   AND audit_owner.action='finance_entry_posted' AND audit_owner.metadata_json=jsonb_build_object('entry_id',i,'content_digest',effect_owner.validation_digest)
   AND outbox_owner.event_type='finance_entry_posted' AND outbox_owner.aggregate_type='finance_posting' AND outbox_owner.aggregate_id=f
   AND outbox_owner.payload=audit_owner.metadata_json||jsonb_build_object('audit_event_id',audit_owner.id)
   AND(outbox_owner.workspace_id,outbox_owner.organization_id,outbox_owner.legal_entity_id)=(entry_owner.workspace_id,o,e)),
  'Actual FinancePosting ownership requires the complete native reviewed seal, captured policy, all three humans and original audit/outbox');
 RETURN snapshot;
END $mr149$;
"""

MARKER_SQL = r"""
CREATE FUNCTION reconforge.monetary_stock_version() RETURNS INTEGER
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $cr149$ SELECT 149 $cr149$;
"""

NATIVE_FUNCTION_SQL = "\n".join((HISTORY_SQL, EFFECT_SQL, ORIGINAL_EQUATION_SQL, STOCK_ADMISSION_SQL, STOCK_PHYSICAL_SQL,
    ORIGIN_SQL, BALANCE_SQL, POSTING_SQL, FX_SQL, PARTIAL_SQL, PUBLIC_SQL, GUARD_SQL, NAMESPACE_SQL,
    PHYSICAL_FUNCTION_SQL, TRANSFER_FUNCTION_SQL, MARKER_SQL))

_NATIVE_TABLES = (
    "operational_fx_sources", "operational_fx_plans", "operational_fx_reviews", "operational_fx_links", "operational_fx_commands",
    "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects",
    "inventory_movements", "inventory_movement_lines", "inventory_valuation_documents", "inventory_valuation_lines", "inventory_layer_consumptions",
    "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations", "domain_audit_events", "outbox_events",
)
_NAMESPACE_TABLES = ("finance_entries", "operational_fx_sources", "operational_fx_plans", "operational_fx_links",
    "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations")

NATIVE_TRIGGER_CONTRACTS = tuple(
    [(table, "monetary_immutable", "monetary_return_protect()", 31, False, False, "O") for table in TABLES]
    + [(table, "monetary_owner_complete", "monetary_return_native_close()", 29, True, True, "O") for table in (*TABLES, *_NATIVE_TABLES)]
    + [(table, "monetary_namespace", "monetary_namespace()", 31 if table in ("ar_invoice_lines", "ar_receipt_allocations") else 23,
        False, False, "O") for table in _NAMESPACE_TABLES]
)


def _trigger_sql() -> str:
    statements = []
    for table, name, function, trigger_type, deferred, _, _ in NATIVE_TRIGGER_CONTRACTS:
        if deferred:
            statements.append(f"CREATE CONSTRAINT TRIGGER {name} AFTER INSERT OR UPDATE OR DELETE ON reconforge.{table} "
                f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.{function};")
        else:
            events = "INSERT OR UPDATE OR DELETE" if trigger_type == 31 else "INSERT OR UPDATE"
            statements.append(f"CREATE TRIGGER {name} BEFORE {events} ON reconforge.{table} FOR EACH ROW EXECUTE FUNCTION reconforge.{function};")
    return "\n".join(statements)


NULLABLE_SQL = r"""
ALTER TABLE reconforge.operational_fx_plans ALTER COLUMN entry_id DROP NOT NULL;
ALTER TABLE reconforge.operational_fx_links ALTER COLUMN posting_effect_id DROP NOT NULL;
ALTER TABLE reconforge.operational_fx_plans ADD CONSTRAINT monetary_fx_journal_presence CHECK(
 entry_id IS NOT NULL OR(
  payload->>'schema_version' IS NOT DISTINCT FROM'operational-fx-stock-plan-v2' AND kind='settle'
  AND payload->'amount_minor' IS NOT DISTINCT FROM'0'::jsonb AND payload->'entry_id' IS NOT DISTINCT FROM'null'::jsonb
  AND payload->'snapshot' IS NOT DISTINCT FROM'null'::jsonb AND payload->'validation_digest' IS NOT DISTINCT FROM'null'::jsonb
  AND payload#>'{equation,lines}' IS NOT DISTINCT FROM'[]'::jsonb));
"""

# Exact PostgreSQL 17.11 deparse captured on the owned 149 catalog fixture.
# actual149-catalog-3fff6c16.json: b4f7bc8de48504375dd79ea41171f1e708580b82670b666ccb36e26b927e8412.
FX_JOURNAL_CONSTRAINT_EXPRESSION = (
    "((entry_id IS NOT NULL) OR ((NOT ((payload ->> 'schema_version'::text) IS DISTINCT FROM 'operational-fx-stock-plan-v2'::text)) "
    "AND (kind = 'settle'::text) AND (NOT ((payload -> 'amount_minor'::text) IS DISTINCT FROM '0'::jsonb)) "
    "AND (NOT ((payload -> 'entry_id'::text) IS DISTINCT FROM 'null'::jsonb)) "
    "AND (NOT ((payload -> 'snapshot'::text) IS DISTINCT FROM 'null'::jsonb)) "
    "AND (NOT ((payload -> 'validation_digest'::text) IS DISTINCT FROM 'null'::jsonb)) "
    "AND (NOT ((payload #> '{equation,lines}'::text[]) IS DISTINCT FROM '[]'::jsonb))))"
)


def _native_catalog_sql() -> str:
    tables = ",".join("'" + table + "'" for table in TABLES)
    prefix = r"""
DO $mr149_catalog$
DECLARE relation_name TEXT;relation_oid OID;expected_scope TEXT;plans_oid OID;
BEGIN
 expected_scope:=CASE WHEN pg_catalog.pg_function_is_visible('reconforge.irp_scope(text,text,text,text)'::pg_catalog.regprocedure)
  THEN 'irp_scope(tenant_id, workspace_id, organization_id, legal_entity_id)'
  ELSE 'reconforge.irp_scope(tenant_id, workspace_id, organization_id, legal_entity_id)' END;
 FOREACH relation_name IN ARRAY ARRAY["""
    suffix = r"""] LOOP
  relation_oid:=pg_catalog.to_regclass('reconforge.'||relation_name);
  PERFORM reconforge.monetary_return_assert(relation_oid IS NOT NULL
   AND (SELECT count(*) FROM pg_catalog.pg_policy policy_owner WHERE policy_owner.polrelid=relation_oid)=1
   AND EXISTS(SELECT 1 FROM pg_catalog.pg_policy policy_owner WHERE policy_owner.polrelid=relation_oid
    AND policy_owner.polname='scope' AND policy_owner.polcmd='*' AND policy_owner.polpermissive
    AND policy_owner.polroles=ARRAY[0::oid]
    AND pg_catalog.pg_get_expr(policy_owner.polqual,policy_owner.polrelid,false)=expected_scope
    AND pg_catalog.pg_get_expr(policy_owner.polwithcheck,policy_owner.polrelid,false)=expected_scope),
   'Every monetary relation requires its one exact public scope policy and identical full-scope USING and WITH CHECK');
 END LOOP;
 PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM pg_catalog.pg_attribute attribute_owner
  WHERE (attribute_owner.attrelid,attribute_owner.attname) IN(
   (pg_catalog.to_regclass('reconforge.operational_fx_plans'),'entry_id'),
   (pg_catalog.to_regclass('reconforge.operational_fx_links'),'posting_effect_id'))
  AND attribute_owner.attnum>0 AND NOT attribute_owner.attisdropped AND NOT attribute_owner.attnotnull
  AND attribute_owner.atttypid='pg_catalog.text'::pg_catalog.regtype)=2,
  'Only the exact native FX entry and effect text columns may admit an absent zero-turnover journal');
 plans_oid:=pg_catalog.to_regclass('reconforge.operational_fx_plans');
 PERFORM reconforge.monetary_return_assert((SELECT count(*) FROM pg_catalog.pg_constraint constraint_owner
   WHERE constraint_owner.conrelid=plans_oid AND constraint_owner.conname='monetary_fx_journal_presence')=1
  AND EXISTS(SELECT 1 FROM pg_catalog.pg_constraint constraint_owner
   WHERE constraint_owner.conrelid=plans_oid AND constraint_owner.conname='monetary_fx_journal_presence'
   AND constraint_owner.contype='c' AND constraint_owner.convalidated AND NOT constraint_owner.connoinherit
   AND constraint_owner.conkey=ARRAY[
    (SELECT attnum FROM pg_catalog.pg_attribute WHERE attrelid=plans_oid AND attname='entry_id' AND NOT attisdropped),
    (SELECT attnum FROM pg_catalog.pg_attribute WHERE attrelid=plans_oid AND attname='payload' AND NOT attisdropped),
    (SELECT attnum FROM pg_catalog.pg_attribute WHERE attrelid=plans_oid AND attname='kind' AND NOT attisdropped)]::smallint[]
   AND pg_catalog.pg_get_expr(constraint_owner.conbin,constraint_owner.conrelid,false)=$mr149_expression$"""
    expression_tail = r"""$mr149_expression$
   AND pg_catalog.pg_get_constraintdef(constraint_owner.oid,false)=$mr149_definition$CHECK ("""
    definition_tail = r""")$mr149_definition$),
  'The native FX nullable-journal constraint must retain its exact validated zero-settlement expression and column affinity');
END $mr149_catalog$;
"""
    return "".join((prefix, tables, suffix, FX_JOURNAL_CONSTRAINT_EXPRESSION,
                    expression_tail, FX_JOURNAL_CONSTRAINT_EXPRESSION, definition_tail))


NATIVE_CATALOG_SQL = _native_catalog_sql()


UPGRADE_SQL = NATIVE_FUNCTION_SQL + NULLABLE_SQL + _trigger_sql()


def _drop_native() -> str:
    statements = [f"DROP TRIGGER {name} ON reconforge.{table};" for table, name, *_ in reversed(NATIVE_TRIGGER_CONTRACTS)]
    definitions = re.findall(r"CREATE FUNCTION reconforge\.([a-z_]+)\(([^)]*)\)\s+RETURNS", NATIVE_FUNCTION_SQL)
    if not definitions or len({name for name, _ in definitions}) != len(definitions):
        raise ValueError("The complete native monetary function inventory must be unique.")
    for name, arguments in reversed(definitions):
        types = ",".join(argument.strip().split()[-1] for argument in arguments.split(",") if argument.strip())
        statements.append(f"DROP FUNCTION reconforge.{name}({types});")
    return "\n".join(statements)


DOWNGRADE_SQL = DOWNGRADE_PREFLIGHT_SQL + _drop_native() + r"""
ALTER TABLE reconforge.operational_fx_plans DROP CONSTRAINT monetary_fx_journal_presence;
ALTER TABLE reconforge.operational_fx_plans ALTER COLUMN entry_id SET NOT NULL;
ALTER TABLE reconforge.operational_fx_links ALTER COLUMN posting_effect_id SET NOT NULL;
"""
