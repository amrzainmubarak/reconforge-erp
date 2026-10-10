-- Frozen landed_cost_close from commit 69951414 (0123 installed owner).
-- Only CREATE OR REPLACE replaces the existing historical function.
CREATE OR REPLACE FUNCTION reconforge.landed_cost_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
DECLARE p RECORD;o RECORD;e RECORD;r RECORD;l RECORD;f RECORD;a RECORD;d RECORD;n RECORD;c RECORD;header JSONB;lines JSONB;allocations JSONB;
 cash TEXT;clearing TEXT;maker TEXT;total NUMERIC;expected_freight NUMERIC;expected_duty NUMERIC;expected_actor TEXT;expected_request JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.landed_cost_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='LC1 source owner is required'; END IF;
 SELECT * INTO o FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=p.order_id;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 SELECT * INTO r FROM reconforge.landed_cost_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.landed_cost_links WHERE tenant_id=t AND plan_id=i;
 maker:=p.payload->>'preparer_actor_id';
 IF o IS NULL OR NOT o.multiline OR o.stage<>2 OR e IS NULL OR NOT reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR (p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM (o.workspace_id,o.organization_id,o.legal_entity_id)
 OR p.payload->>'schema_version' IS DISTINCT FROM 'landed-cost-v1' OR p.payload->>'id' IS DISTINCT FROM i
 OR p.payload->>'entry_id' IS DISTINCT FROM p.entry_id OR p.payload#>>'{request,order_id}' IS DISTINCT FROM o.id
 OR reconforge.irp_digest(p.payload) IS DISTINCT FROM p.plan_digest
 OR p.amount_minor::numeric IS DISTINCT FROM (p.payload#>>'{request,freight_minor}')::numeric+(p.payload#>>'{request,duty_minor}')::numeric
 OR (p.payload#>>'{request,freight_minor}')::numeric<0 OR (p.payload#>>'{request,duty_minor}')::numeric<0
 OR (p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id') IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR e.entry_number<>upper(i) OR e.external_reference<>'LANDED-COST:'||i OR e.source_type<>'Manual'
 OR e.preparer_actor_id IS DISTINCT FROM maker OR e.total_debit_minor<>p.amount_minor OR e.total_credit_minor<>p.amount_minor
 OR e.currency_code<>o.request_json->>'currency_code' OR e.organization_code<>o.request_json->>'organization_code'
 OR e.entity_code<>o.request_json->>'entity_code' OR e.workspace_id<>o.workspace_id OR e.reverses_posting_id IS NOT NULL
 OR e.description<>p.payload#>>'{request,reason}' OR e.posting_date::text<>p.payload#>>'{request,posting_date}' OR e.period_id<>p.payload#>>'{request,period_id}'
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_journals j WHERE j.tenant_id=t AND j.id=e.journal_id AND j.journal_code=o.request_json->>'journal_code') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost exact source, scope, amount or immutable digest differs'; END IF;
 SELECT jsonb_object_agg(key,value) INTO header FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY[
 'id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
 'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 header:=header||jsonb_build_object('organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,
 'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(z.dimension_id,z.dimension_value_id)
 FROM reconforge.finance_entry_line_dimensions z WHERE z.tenant_id=t AND z.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 INTO lines FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id;
 SELECT fa.id INTO cash FROM reconforge.finance_accounts fa JOIN reconforge.finance_journals j ON j.tenant_id=fa.tenant_id AND j.chart_id=fa.chart_id
 WHERE fa.tenant_id=t AND j.id=e.journal_id AND fa.account_code=o.request_json->>'cash_account_code' AND fa.account_type='Asset';
 IF p.payload->'snapshot' IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',header,'lines',lines)
 OR reconforge.irp_digest(p.payload->'snapshot') IS DISTINCT FROM p.payload->>'validation_digest'
 OR jsonb_array_length(lines)<>2 OR cash IS NULL OR lines->1->>'account_id' IS DISTINCT FROM cash
 OR (lines->0->>'debit_minor')::numeric<>p.amount_minor OR (lines->0->>'credit_minor')::numeric<>0
 OR (lines->1->>'credit_minor')::numeric<>p.amount_minor OR (lines->1->>'debit_minor')::numeric<>0 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Paid charges require their exact retained native GL snapshot'; END IF;
 SELECT sum(base_minor) INTO total FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i;
 SELECT jsonb_agg(to_jsonb(x)-ARRAY['tenant_id','plan_id','order_id'] ORDER BY sequence) INTO allocations
 FROM reconforge.landed_cost_allocations x WHERE tenant_id=t AND plan_id=i;
 IF allocations IS DISTINCT FROM p.payload->'allocations' OR jsonb_array_length(allocations) NOT BETWEEN 1 AND 128
 OR jsonb_array_length(p.payload#>'{request,lines}')<>jsonb_array_length(allocations)
 OR (SELECT sum(freight_minor) FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i)<>(p.payload#>>'{request,freight_minor}')::numeric
 OR (SELECT sum(duty_minor) FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i)<>(p.payload#>>'{request,duty_minor}')::numeric THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Allocations must conserve all paid charges and source members'; END IF;
 FOR a IN SELECT * FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i ORDER BY sequence LOOP
 SELECT * INTO d FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND id=a.receipt_id;
 SELECT * INTO n FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=o.id AND id=a.order_line_id;
 SELECT q.receipt_clearing_account_id INTO clearing FROM reconforge.inventory_receipt_plans q WHERE q.tenant_id=t AND q.id=d.receipt_plan_id;
 SELECT floor((p.payload#>>'{request,freight_minor}')::numeric*a.base_minor/total)+CASE WHEN rank<=residual THEN 1 ELSE 0 END INTO expected_freight
 FROM (SELECT order_line_id,row_number() OVER(ORDER BY mod((p.payload#>>'{request,freight_minor}')::numeric*base_minor,total) DESC,order_line_id COLLATE "C") rank,
 (p.payload#>>'{request,freight_minor}')::numeric-sum(floor((p.payload#>>'{request,freight_minor}')::numeric*base_minor/total)) OVER() residual
 FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i) weights WHERE order_line_id=a.order_line_id;
 SELECT floor((p.payload#>>'{request,duty_minor}')::numeric*a.base_minor/total)+CASE WHEN rank<=residual THEN 1 ELSE 0 END INTO expected_duty
 FROM (SELECT order_line_id,row_number() OVER(ORDER BY mod((p.payload#>>'{request,duty_minor}')::numeric*base_minor,total) DESC,order_line_id COLLATE "C") rank,
 (p.payload#>>'{request,duty_minor}')::numeric-sum(floor((p.payload#>>'{request,duty_minor}')::numeric*base_minor/total)) OVER() residual
 FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i) weights WHERE order_line_id=a.order_line_id;
 IF d IS NULL OR n IS NULL OR d.order_id<>o.id OR d.order_line_id<>n.id OR a.quantity_text::numeric<>d.quantity
 OR a.base_minor<>d.total_minor OR a.base_minor::numeric<>d.quantity*n.unit_price_minor
 OR a.freight_minor<>expected_freight OR a.duty_minor<>expected_duty OR clearing IS DISTINCT FROM lines->0->>'account_id'
 OR d.stage<>p.phase OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload#>'{request,lines}') z
 WHERE z->>'line_id'=n.id AND (z->>'quantity')::numeric=d.quantity)
 OR reconforge.pp_command(t,o.id,d.created_version,'prepare-receipt-line')<>maker
 OR (p.phase>=1 AND reconforge.pp_command(t,o.id,d.reviewed_version,'review-receipt',d.id)<>r.reviewer_actor_id)
 OR (p.phase=2 AND reconforge.pp_command(t,o.id,d.posted_version,'receive',d.id)<>l.posted_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Charged receipts require the whole conserved bundle and its three human stages'; END IF;
 END LOOP;
 IF NOT reconforge.landed_cost_event(t,i,p.audit_event_id,p.outbox_event_id,maker,'landed_cost_prepared',p.plan_digest)
 OR (p.phase=0 AND (e.status<>'Draft' OR r IS NOT NULL OR l IS NOT NULL))
 OR (p.phase>=1 AND (r IS NULL OR r.reviewer_actor_id=maker OR e.validator_actor_id<>r.reviewer_actor_id
 OR e.validation_digest<>p.payload->>'validation_digest' OR NOT reconforge.landed_cost_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'landed_cost_reviewed',p.plan_digest)))
 OR (p.phase=1 AND (e.status<>'Validated' OR l IS NOT NULL)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost requires retained independent review and evidence'; END IF;
 IF p.phase=2 THEN
 SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=l.posting_effect_id;
 IF l IS NULL OR f IS NULL OR f.entry_id<>e.id OR f.source_kind<>'Manual' OR f.source_id<>e.id OR f.snapshot_json<>p.payload->'snapshot'
 OR e.status<>'Validated' OR f.validation_digest<>p.payload->>'validation_digest' OR f.posted_actor_id<>l.posted_actor_id
 OR l.posted_actor_id IN(maker,r.reviewer_actor_id) OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id)
 OR NOT reconforge.landed_cost_event(t,i,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'landed_cost_posted',p.plan_digest) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Receipt publication and exact cash posting must commit together'; END IF;
 ELSIF EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.entry_id=e.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Cash cannot publish without its received allocation bundle'; END IF;
 FOR c IN SELECT * FROM reconforge.landed_cost_commands WHERE tenant_id=t AND plan_id=i LOOP
 expected_actor:=CASE c.operation WHEN 'prepare' THEN maker WHEN 'review' THEN r.reviewer_actor_id ELSE l.posted_actor_id END;
 expected_request:=CASE c.operation WHEN 'prepare' THEN p.payload->'request' ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',p.plan_digest,
 'reason',CASE c.operation WHEN 'review' THEN r.reason ELSE l.reason END) END;
 IF c.workspace_id<>p.workspace_id OR c.actor_id IS DISTINCT FROM expected_actor
 OR c.request_json IS DISTINCT FROM jsonb_build_object('operation',c.operation,'actor_id',c.actor_id,'request',expected_request)
 OR reconforge.irp_digest(c.request_json) IS DISTINCT FROM c.request_digest
 OR c.response_json->>'id' IS DISTINCT FROM i OR c.response_json->>'plan_digest' IS DISTINCT FROM p.plan_digest
 OR c.response_json IS DISTINCT FROM reconforge.landed_cost_ack(t,i,CASE c.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END)
 OR (c.response_json->>'phase')::integer<>(CASE c.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END)
 OR c.response_json->>'status'<>(CASE c.operation WHEN 'prepare' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' ELSE 'Posted' END) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Retry acknowledgement requires its exact source, actor and phase'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM reconforge.landed_cost_commands WHERE tenant_id=t AND plan_id=i)<>p.phase+1 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Every paid landed cost stage requires an immutable command'; END IF;
END $lc$;
