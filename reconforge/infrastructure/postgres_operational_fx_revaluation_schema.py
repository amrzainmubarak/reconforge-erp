"""Additive closing-rate valuation and exact native inverse over FX1 owners.

Reuse the accepted source/tax/native journal closure verbatim, replacing only
the explicit operation equations and reversal predicates in a forward migration.
No additional trigger or query is added to an unrelated native owner.
"""

from reconforge.infrastructure.postgres_operational_fx_tax_schema import UPGRADE_SQL as FX_SQL


def replace_once(sql: str, original: str, replacement: str) -> str:
    if sql.count(original) != 1:
        raise ValueError("The accepted FX closure changed; review the additive valuation migration.")
    return sql.replace(original, replacement, 1)


ORIGINAL_CLOSE = FX_SQL[FX_SQL.index("CREATE FUNCTION reconforge.fx_close("):FX_SQL.index("CREATE FUNCTION reconforge.fx_reverse_close(")]
ORIGINAL_ACTOR = FX_SQL[FX_SQL.index("CREATE FUNCTION reconforge.fx_command_actor("):FX_SQL.index("CREATE TRIGGER operational_fx_current_actor")]

VALUATION_SQL = r"""
ALTER TABLE reconforge.operational_fx_plans DROP CONSTRAINT operational_fx_plans_kind_check;
ALTER TABLE reconforge.operational_fx_plans ADD CONSTRAINT operational_fx_plans_kind_check
 CHECK(kind IN ('recognize','settle','revalue','reverse_revaluation'));
CREATE FUNCTION reconforge.fx_valuation_equation(t TEXT,i TEXT) RETURNS JSONB LANGUAGE plpgsql SET search_path=pg_catalog AS $fx$
DECLARE p RECORD;s RECORD;previous RECORD;original RECORD;link RECORD;jn RECORD;v JSONB;q JSONB;req JSONB;equation JSONB;expected JSONB;item JSONB;
 paid NUMERIC:=0;released NUMERIC:=0;outstanding NUMERIC;carrying NUMERIC;valued NUMERIC;delta NUMERIC;rate NUMERIC;
 active TEXT;fp INTEGER;lp INTEGER;gain TEXT;loss TEXT;code TEXT;kind TEXT;field TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO s FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=p.source_id;
 v:=p.payload;req:=v->'command_request';q:=s.payload->'request';
 fp:=(s.payload->'foreign_policy'->>'currency_precision')::integer;
 lp:=(s.payload->'functional_policy'->>'currency_precision')::integer;
 FOR previous IN SELECT * FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=s.id AND sequence<p.sequence ORDER BY sequence LOOP
  IF previous.kind='settle' THEN
   PERFORM reconforge.fx_assert(active IS NULL,'Historical settlement requires its closing valuation to be explicitly reversed first');
   paid:=paid+(previous.payload->'equation'->>'foreign_minor')::numeric;
   released:=released+(previous.payload->'equation'->>'historical_release_minor')::numeric;
  ELSIF previous.kind='revalue' THEN
   PERFORM reconforge.fx_assert(active IS NULL,'A source can retain only one active closing valuation');active:=previous.id;
  ELSIF previous.kind='reverse_revaluation' THEN
   PERFORM reconforge.fx_assert(active IS NOT NULL AND previous.payload->'equation'->>'original_revaluation_id'=active,
    'An explicit inverse must close its exact active valuation');active:=NULL;
  END IF;
 END LOOP;
 PERFORM reconforge.fx_assert(req->>'kind'=p.kind AND req->>'source_id'=s.id AND req->>'period_id'=v->>'period_id'
  AND req->>'posting_date'=v->>'posting_date' AND req->>'reason'=v->>'reason','Closing valuation request differs from its retained source and date');
 IF p.kind='settle' THEN
  PERFORM reconforge.fx_assert(active IS NULL,'Historical settlement requires its closing valuation to be explicitly reversed first');
  RETURN NULL;
 END IF;
 IF p.kind='revalue' THEN
  PERFORM reconforge.fx_assert(active IS NULL AND reconforge.fx_object(req,ARRAY['kind','source_id','closing_rate',
   'unrealized_gain_account_code','unrealized_loss_account_code','period_id','posting_date','reason']),
   'Closing valuation requires one exact bounded request and no prior active valuation');
  rate:=reconforge.fx_rate(q->'original_rate',q->>'posting_date');
  PERFORM reconforge.fx_assert(released=reconforge.fx_convert(paid,rate,fp,lp),'Closing valuation historical release differs from the original cumulative rate');
  outstanding:=(s.payload->>'foreign_gross_minor')::numeric-paid;
  carrying:=(s.payload->>'functional_gross_minor')::numeric-released;
  valued:=reconforge.fx_convert(outstanding,reconforge.fx_rate(req->'closing_rate',v->>'posting_date'),fp,lp);delta:=valued-carrying;
  PERFORM reconforge.fx_assert(outstanding BETWEEN 1 AND 9000000000000000000 AND carrying BETWEEN 0 AND 9000000000000000000
   AND valued BETWEEN 1 AND 9000000000000000000 AND abs(delta) BETWEEN 1 AND 9000000000000000000,
   'Closing valuation requires exact positive foreign and functional residuals and a nonzero bounded difference');
  gain:=req->>'unrealized_gain_account_code';loss:=req->>'unrealized_loss_account_code';
  PERFORM reconforge.fx_assert(jsonb_typeof(req->'unrealized_gain_account_code')='string'
   AND jsonb_typeof(req->'unrealized_loss_account_code')='string' AND gain<>loss
   AND gain~'^[A-Z0-9][A-Z0-9._-]{0,63}$' AND loss~'^[A-Z0-9][A-Z0-9._-]{0,63}$'
   AND NOT EXISTS(SELECT 1 FROM jsonb_each_text(q) WHERE key LIKE '%\_account_code' ESCAPE '\' AND value IN (gain,loss))
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(q->'taxes') tax WHERE tax->>'account_code' IN (gain,loss)),
   'Unrealized accounting roles must be canonical and distinct from original revenue, cash, tax and realized roles');
  SELECT j.* INTO jn FROM reconforge.finance_journals j JOIN reconforge.finance_entries e ON e.tenant_id=j.tenant_id AND e.journal_id=j.id WHERE e.tenant_id=t AND e.id=p.entry_id;
  FOREACH field IN ARRAY ARRAY['gain','loss'] LOOP
   code:=CASE field WHEN 'gain' THEN gain ELSE loss END;
   SELECT account_type INTO kind FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=s.workspace_id AND chart_id=jn.chart_id AND account_code=code;
   PERFORM reconforge.fx_assert(kind=CASE field WHEN 'gain' THEN 'Income' ELSE 'Expense' END,'Unrealized accounts require exact Income and Expense classifications');
  END LOOP;
  expected:=jsonb_build_array(jsonb_build_object('account_code',q->>'receivable_account_code','debit_minor',greatest(delta,0),'credit_minor',greatest(-delta,0)),
   jsonb_build_object('account_code',CASE WHEN delta>0 THEN gain ELSE loss END,'debit_minor',greatest(-delta,0),'credit_minor',greatest(delta,0)));
  equation:=jsonb_build_object('foreign_before_minor',paid,'historical_before_minor',released,'foreign_outstanding_minor',outstanding,
   'historical_outstanding_minor',carrying,'valued_outstanding_minor',valued,'unrealized_fx_minor',delta,'closing_rate',req->'closing_rate',
   'unrealized_gain_account_code',gain,'unrealized_loss_account_code',loss,'amount_minor',abs(delta),'lines',expected);
 ELSE
  PERFORM reconforge.fx_assert(p.kind='reverse_revaluation' AND active IS NOT NULL AND req->>'original_revaluation_id'=active
   AND reconforge.fx_object(req,ARRAY['kind','source_id','original_revaluation_id','period_id','posting_date','reason']),
   'Explicit inverse requires the exact active posted original closing valuation');
  SELECT * INTO original FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=active;
  SELECT * INTO link FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=active;
  PERFORM reconforge.fx_assert(original.kind='revalue' AND original.phase=2 AND original.source_id=s.id AND link.posting_effect_id IS NOT NULL,
   'Explicit inverse requires an intact native posted valuation of the same source');
  SELECT jsonb_agg(jsonb_build_object('account_code',value->>'account_code','debit_minor',(value->>'credit_minor')::numeric,
   'credit_minor',(value->>'debit_minor')::numeric) ORDER BY ordinal) INTO expected FROM jsonb_array_elements(original.payload->'equation'->'lines') WITH ORDINALITY x(value,ordinal);
  equation:=jsonb_build_object('original_revaluation_id',active,'original_plan_digest',original.payload->>'plan_digest',
   'original_posting_effect_id',link.posting_effect_id,'original_equation_digest',reconforge.irp_digest(original.payload->'equation'),
   'unrealized_fx_minor',-(original.payload->'equation'->>'unrealized_fx_minor')::numeric,
   'amount_minor',(original.payload->>'amount_minor')::numeric,'lines',expected);
 END IF;
 FOR field IN SELECT key FROM jsonb_each(equation) WHERE key LIKE '%\_minor' ESCAPE '\' LOOP
  PERFORM reconforge.fx_assert(jsonb_typeof(v->'equation'->field)='number' AND (v->'equation'->field)::text~'^(0|-?[1-9][0-9]*)$'
   AND abs((v->'equation'->>field)::numeric)<=9000000000000000000,'Closing valuation requires exact integer financial representation');
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(v->'equation'->'lines') LOOP
  PERFORM reconforge.fx_assert(reconforge.fx_object(item,ARRAY['account_code','debit_minor','credit_minor'])
   AND reconforge.fx_minor(item->'debit_minor') AND reconforge.fx_minor(item->'credit_minor'),
   'Closing valuation lines require exact integer minor units without decimal representation');
 END LOOP;
 RETURN equation;
END $fx$;
"""

CLOSE_SQL = replace_once(ORIGINAL_CLOSE, "CREATE FUNCTION reconforge.fx_close", "CREATE OR REPLACE FUNCTION reconforge.fx_close")
CLOSE_SQL = replace_once(CLOSE_SQL, "v->>'schema_version'='operational-fx-plan-v1'", "v->>'schema_version'=CASE WHEN p.kind IN ('revalue','reverse_revaluation') THEN 'operational-fx-plan-v2' ELSE 'operational-fx-plan-v1' END")
CLOSE_SQL = replace_once(CLOSE_SQL, " ELSE\n  req:=v->'command_request';", " ELSIF p.kind='settle' THEN\n  PERFORM reconforge.fx_valuation_equation(t,i);\n  req:=v->'command_request';")
CLOSE_SQL = replace_once(CLOSE_SQL, "'lines',expected);\n END IF;\n SELECT sum", "'lines',expected);\n ELSE\n  req:=v->'command_request';equation:=reconforge.fx_valuation_equation(t,i);expected:=equation->'lines';\n END IF;\n SELECT sum")
CLOSE_SQL = replace_once(CLOSE_SQL, "e.source_type='Manual'", "e.source_type=CASE WHEN p.kind='reverse_revaluation' THEN 'Generated' ELSE 'Manual' END")
CLOSE_SQL = replace_once(CLOSE_SQL, "e.reverses_posting_id IS NULL", "e.reverses_posting_id IS NOT DISTINCT FROM CASE WHEN p.kind='reverse_revaluation' THEN equation->>'original_posting_effect_id' ELSE NULL END")
CLOSE_SQL = replace_once(CLOSE_SQL, "AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id)", "AND f.reverses_effect_id IS NOT DISTINCT FROM CASE WHEN p.kind='reverse_revaluation' THEN equation->>'original_posting_effect_id' ELSE NULL END\n  AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id\n   AND NOT EXISTS(SELECT 1 FROM reconforge.operational_fx_plans inverse JOIN reconforge.operational_fx_links inverse_link\n    ON inverse_link.tenant_id=inverse.tenant_id AND inverse_link.plan_id=inverse.id WHERE inverse.tenant_id=t AND inverse.source_id=s.id\n    AND inverse.kind='reverse_revaluation' AND inverse.phase=2 AND inverse_link.posting_effect_id=z.id\n    AND inverse.payload->'equation'->>'original_revaluation_id'=p.id AND inverse.payload->'equation'->>'original_posting_effect_id'=f.id))")

ACTOR_SQL = replace_once(ORIGINAL_ACTOR, "CREATE FUNCTION reconforge.fx_command_actor", "CREATE OR REPLACE FUNCTION reconforge.fx_command_actor")
ACTOR_SQL = replace_once(ACTOR_SQL, " SELECT * INTO period", " IF p.kind='reverse_revaluation' THEN PERFORM reconforge.fx_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,'finance_core.reverse'),\n  'Explicit valuation inverse requires current persisted human reversal permission'); END IF;\n SELECT * INTO period")

UPGRADE_SQL = VALUATION_SQL + CLOSE_SQL + ACTOR_SQL
DOWNGRADE_BASE = r"""
DO $fx$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.operational_fx_plans WHERE kind IN ('revalue','reverse_revaluation')) THEN
  RAISE EXCEPTION 'Revaluation rollback refuses to discard retained valuation or inverse evidence';END IF;
END $fx$;
ALTER TABLE reconforge.operational_fx_plans DROP CONSTRAINT operational_fx_plans_kind_check;
ALTER TABLE reconforge.operational_fx_plans ADD CONSTRAINT operational_fx_plans_kind_check CHECK(kind IN ('recognize','settle'));
"""
DOWNGRADE_HELPER = "DROP FUNCTION reconforge.fx_valuation_equation(TEXT,TEXT);"
DOWNGRADE_SQL = "".join((DOWNGRADE_BASE, ORIGINAL_CLOSE.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
                         ORIGINAL_ACTOR.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1), DOWNGRADE_HELPER))
