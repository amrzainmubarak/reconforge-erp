"""Native149 monetary origin, exact signed history and correction ownership.

All functions execute as the caller. Public report projections share their
outer SELECT snapshot; authoritative mutation/history functions are VOLATILE.
The seven relations and reversible legacy-function installation are separate.
"""

from reconforge.infrastructure.postgres_operational_fx_tax_schema import UPGRADE_SQL as ORIGINAL_FX_SQL


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
