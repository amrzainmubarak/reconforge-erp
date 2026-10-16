"""Native149 monetary origin, exact signed history and correction ownership.

All functions execute as the caller. Public report projections share their
outer SELECT snapshot; authoritative mutation/history functions are VOLATILE.
The seven relations and reversible legacy-function installation are separate.
"""

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


ORIGINAL_EQUATION_SQL = r"""
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
""" + _original_equation() + r"""
 RETURN a-ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','preparer_actor_id','invoice_id','source_digest','stock_order_id','stock_source_digest'];
END $mr149$;
"""


def _stock_body(name: str, following: str) -> str:
    start = ORIGINAL_STOCK_SQL.index("CREATE FUNCTION reconforge." + name + "(")
    end = ORIGINAL_STOCK_SQL.index(following, start)
    definition = ORIGINAL_STOCK_SQL[start:end]
    return definition[definition.index("AS $$") + 5:definition.rindex("$$;")]


def _stock_physical() -> str:
    """Retain the accepted native issue proof, with an explicit L policy."""
    body = _stock_body("stock_sales_close", "CREATE FUNCTION reconforge.stock_sales_close_trigger")
    body = body[:body.index(" IF d.invoice_id IS NOT NULL THEN")]
    begin = body.index(" s:=reconforge.stock_sales_stage(d.status);")
    retained = body.index(" SELECT * INTO r FROM reconforge.stock_sales_reservations")
    body = body[:begin] + """
 s:=CASE WHEN d.movement_id IS NOT NULL THEN 6 WHEN d.issue_reviewer_id IS NOT NULL THEN 5
  WHEN d.issue_plan IS NOT NULL THEN 4 WHEN d.status='Reserved' THEN 3 ELSE reconforge.stock_sales_stage(d.status) END;
 IF d.issue_plan ? 'cost_admission_policy' THEN
  PERFORM reconforge.monetary_stock_zero_plan(t,target);RETURN;
 END IF;
""" + body[retained:]
    body = body.replace("d.source->'monetary_policy'", "d.source->'functional_policy'")
    body = body.replace("d.currency_code", "(d.source#>>'{functional_policy,currency_code}')")
    body = body.replace("r IS NULL", "r.order_id IS NULL").replace("r IS NOT NULL", "r.order_id IS NOT NULL")
    body = body.replace("claim IS NULL", "claim.order_id IS NULL").replace("claim IS NOT NULL", "claim.order_id IS NOT NULL")
    body = body.replace("entry IS NULL", "entry.id IS NULL")
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
  'transaction_outstanding_minor',position->>'transaction_outstanding_minor','functional_outstanding_minor',position->>'functional_outstanding_minor',
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
 snapshot:=reconforge.fr_snapshot(t,member.entry_id,origin_owner.organization_id,origin_owner.legal_entity_id);
 SELECT actor_id INTO reviewer FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT actor_id INTO poster FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 PERFORM reconforge.monetary_return_assert(slot IS NOT NULL AND member.entry_id=native_id AND entry_owner.id=native_id
  AND entry_owner.entry_number=number AND member.snapshot=snapshot AND member.validation_digest=reconforge.irp_digest(snapshot)
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
   AND(actual_lines->(ordinal-1)-ARRAY['line_number','description'])=part,
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
    assembler = assembler[:first] + r"""
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
""" + assembler[last:]
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
 FOR prior IN SELECT * FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=source_owner.id AND sequence<plan_owner.sequence ORDER BY sequence LOOP
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
  AND v->'entry_id' IS NOT DISTINCT FROM to_jsonb(plan_owner.entry_id) AND reconforge.fx_minor(v->'amount_minor')
  AND reconforge.fx_minor(v->'sequence') AND(v->>'sequence')::integer=plan_owner.sequence
  AND v->>'currency_code'=policy->>'currency_code' AND v->'currency_precision'=policy->'currency_precision',
  'The reused FX plan must preserve its exact fixed source, scope, identity and immutable financial seal');
 FOR prior IN SELECT * FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=source_owner.id AND sequence<plan_owner.sequence ORDER BY sequence LOOP
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
  snapshot:=reconforge.fr_snapshot(t,plan_owner.entry_id,origin_owner.organization_id,origin_owner.legal_entity_id);
  inverse_effect:=CASE WHEN plan_owner.kind='reverse_revaluation' THEN equation->>'original_posting_effect_id' ELSE NULL END;
  PERFORM reconforge.monetary_return_assert(entry_owner.id IS NOT NULL AND entry_owner.entry_number=upper(i)
   AND v->>'schema_version'=(CASE WHEN plan_owner.kind IN('revalue','reverse_revaluation') THEN'operational-fx-plan-v2' ELSE'operational-fx-plan-v1' END)
   AND v->'snapshot'=snapshot AND v->>'validation_digest'=reconforge.irp_digest(snapshot)
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
  'transaction_policy',origin_owner.payload#>'{source,transaction_policy}','functional_policy',origin_owner.payload#>'{source,functional_policy}',
  'quantity_precision',origin_owner.payload#>'{source,quantity_precision}','original_quantity_scaled',origin_owner.payload#>>'{source,quantity_scaled}',
  'returned_quantity_scaled',((origin_owner.payload#>>'{source,quantity_scaled}')::numeric-remaining)::text,'remaining_quantity_scaled',remaining::text);
END $mr149$;
CREATE FUNCTION reconforge.monetary_partial_close(t TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mr149$
DECLARE plan_owner RECORD;origin_owner RECORD;original_owner RECORD;event_owner RECORD;command_owner RECORD;entry_member RECORD;
 v JSONB;source JSONB;prefix JSONB;event JSONB;expected_event JSONB;journals JSONB;part JSONB;lines JSONB;original_event JSONB;
 reviewer TEXT;poster TEXT;preparer TEXT;cancelled TEXT;expected_command TEXT;expected_request JSONB;expected_response JSONB;stage INTEGER;
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
  IF plan_owner.operation IN('Return','ReverseReturn') THEN PERFORM reconforge.monetary_return_physical(t,i,FALSE);END IF;
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
