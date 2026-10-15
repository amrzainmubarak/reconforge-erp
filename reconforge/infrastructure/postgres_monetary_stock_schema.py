"""Revision149 storage for the fixed monetary Stock/partial-return owner.

Seven additive relations share exact parent scope. Native lifecycle and deferred
financial closure are installed by the companion owner module in the same
migration transaction. This storage definition grants no business privileges.
"""

from reconforge.infrastructure.postgres_monetary_receivables import MONETARY_TABLES

TABLES = MONETARY_TABLES

STORAGE_SQL = r"""
CREATE TABLE reconforge.stock_sales_monetary_origins (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(reconforge.irp_text(id,160)),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 stock_order_id TEXT NOT NULL,invoice_id TEXT NOT NULL,fx_source_id TEXT NOT NULL,recognition_plan_id TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=2097152),
 source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),
 ar_balance JSONB NOT NULL CHECK(jsonb_typeof(ar_balance)='object' AND octet_length(ar_balance::text)<=8192),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,stock_order_id),UNIQUE(tenant_id,invoice_id),
 UNIQUE(tenant_id,fx_source_id),UNIQUE(tenant_id,recognition_plan_id),
 UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,stock_order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,fx_source_id) REFERENCES reconforge.operational_fx_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,recognition_plan_id) REFERENCES reconforge.operational_fx_plans(tenant_id,id)
);
CREATE INDEX monetary_stock_origin_scope ON reconforge.stock_sales_monetary_origins
 (tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE "C");
CREATE TABLE reconforge.customer_partial_return_monetary_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^(CR3|CRF3|CR3R|CRF3R)-[0-9a-f]{32}$'),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,origin_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('Return','Refund','ReverseReturn','ReverseRefund')),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),original_id TEXT,
 expected_history_version INTEGER NOT NULL CHECK(expected_history_version BETWEEN 0 AND 255),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=2097152),
 plan_digest TEXT NOT NULL CHECK(plan_digest~'^[0-9a-f]{64}$'),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,id,origin_id),UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,origin_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES reconforge.stock_sales_monetary_origins(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,original_id,origin_id) REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,origin_id),
 CHECK((operation='Return' AND original_id IS NULL) OR(operation<>'Return' AND original_id IS NOT NULL)),
 CHECK((operation='Return' AND id~'^CR3-') OR(operation='Refund' AND id~'^CRF3-')
  OR(operation='ReverseReturn' AND id~'^CR3R-') OR(operation='ReverseRefund' AND id~'^CRF3R-'))
);
CREATE UNIQUE INDEX monetary_return_pending ON reconforge.customer_partial_return_monetary_plans(tenant_id,origin_id) WHERE phase IN(0,1);
CREATE UNIQUE INDEX monetary_return_single_inverse ON reconforge.customer_partial_return_monetary_plans(tenant_id,original_id)
 WHERE operation IN('ReverseReturn','ReverseRefund') AND phase<>3;
CREATE INDEX monetary_return_plan_scope ON reconforge.customer_partial_return_monetary_plans
 (tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE "C");
CREATE TABLE reconforge.customer_partial_return_monetary_entries (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN('MerchandiseCredit','CostRestoration','Refund','ReverseMerchandiseCredit','ReverseCostRestoration','ReverseRefund')),
 entry_id TEXT NOT NULL,snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=2097152),
 validation_digest TEXT NOT NULL CHECK(validation_digest~'^[0-9a-f]{64}$'),original_effect_id TEXT,posting_effect_id TEXT,
 PRIMARY KEY(tenant_id,plan_id,purpose),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,original_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 CHECK((purpose IN('ReverseMerchandiseCredit','ReverseCostRestoration','ReverseRefund'))=(original_effect_id IS NOT NULL))
);
CREATE TABLE reconforge.customer_partial_return_monetary_events (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('prepare','review','post','cancel')),
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id,operation),UNIQUE(tenant_id,audit_event_id),UNIQUE(tenant_id,outbox_event_id),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.customer_partial_return_monetary_history (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,origin_id TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 256),
 kind TEXT NOT NULL CHECK(kind IN('Return','Collection','Refund','ReverseReturn','ReverseRefund')),
 stock_fx_plan_id TEXT,partial_plan_id TEXT,original_sequence INTEGER,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=2097152),
 previous_digest TEXT NOT NULL CHECK(previous_digest~'^[0-9a-f]{64}$'),event_digest TEXT NOT NULL CHECK(event_digest~'^[0-9a-f]{64}$'),
 PRIMARY KEY(tenant_id,origin_id,sequence),UNIQUE(tenant_id,stock_fx_plan_id),UNIQUE(tenant_id,partial_plan_id),
 FOREIGN KEY(tenant_id,origin_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES reconforge.stock_sales_monetary_origins(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,partial_plan_id,origin_id) REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,origin_id),
 FOREIGN KEY(tenant_id,stock_fx_plan_id) REFERENCES reconforge.operational_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,origin_id,original_sequence) REFERENCES reconforge.customer_partial_return_monetary_history(tenant_id,origin_id,sequence),
 CHECK((kind='Collection' AND stock_fx_plan_id IS NOT NULL AND partial_plan_id IS NULL)
  OR(kind<>'Collection' AND stock_fx_plan_id IS NULL AND partial_plan_id IS NOT NULL)),
 CHECK((kind IN('ReverseReturn','ReverseRefund') AND original_sequence IS NOT NULL AND original_sequence>0 AND original_sequence<sequence)
  OR(kind NOT IN('ReverseReturn','ReverseRefund') AND original_sequence IS NULL))
);
CREATE TABLE reconforge.customer_partial_return_monetary_restorations (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 origin_id TEXT NOT NULL,plan_id TEXT NOT NULL,position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 32),
 original_consumption_id TEXT NOT NULL,original_valuation_line_id TEXT NOT NULL,cost_layer_id TEXT NOT NULL,
 before_quantity_scaled BIGINT NOT NULL CHECK(before_quantity_scaled BETWEEN 1 AND 9000000000000000000),
 before_value_minor BIGINT NOT NULL CHECK(before_value_minor BETWEEN 0 AND 9000000000000000000),
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND before_quantity_scaled),
 value_minor BIGINT NOT NULL CHECK(value_minor BETWEEN 0 AND before_value_minor),
 direction INTEGER NOT NULL CHECK(direction IN(-1,1)),physical_movement_id TEXT NOT NULL,correction_effect_id TEXT,
 original_restoration_plan_id TEXT,consumption_count_at_restore BIGINT NOT NULL CHECK(consumption_count_at_restore>0),
 PRIMARY KEY(tenant_id,plan_id,position),
 FOREIGN KEY(tenant_id,origin_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES reconforge.stock_sales_monetary_origins(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,plan_id,origin_id) REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,origin_id),
 FOREIGN KEY(tenant_id,original_consumption_id) REFERENCES reconforge.inventory_layer_consumptions(tenant_id,id),
 FOREIGN KEY(tenant_id,original_valuation_line_id) REFERENCES reconforge.inventory_valuation_lines(tenant_id,id),
 FOREIGN KEY(tenant_id,cost_layer_id) REFERENCES reconforge.inventory_cost_layers(tenant_id,id),
 FOREIGN KEY(tenant_id,physical_movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id),
 FOREIGN KEY(tenant_id,correction_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,original_restoration_plan_id,position) REFERENCES reconforge.customer_partial_return_monetary_restorations(tenant_id,plan_id,position),
 FOREIGN KEY(tenant_id,original_restoration_plan_id,origin_id) REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,origin_id),
 CHECK((direction=1 AND original_restoration_plan_id IS NULL) OR(direction=-1 AND original_restoration_plan_id IS NOT NULL)),
 CHECK(value_minor=0 OR correction_effect_id IS NOT NULL)
);
CREATE INDEX monetary_return_restored_layer ON reconforge.customer_partial_return_monetary_restorations(tenant_id,cost_layer_id,plan_id,position);
CREATE TABLE reconforge.customer_partial_return_monetary_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('prepare','prepare_refund','prepare_reversal','review','post','cancel')),
 command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=2097152),
 response_json JSONB NOT NULL CHECK(jsonb_typeof(response_json)='object' AND octet_length(response_json::text)<=2097152),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES reconforge.customer_partial_return_monetary_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
DO $cr149storage$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['stock_sales_monetary_origins','customer_partial_return_monetary_plans',
  'customer_partial_return_monetary_entries','customer_partial_return_monetary_events',
  'customer_partial_return_monetary_history','customer_partial_return_monetary_restorations',
  'customer_partial_return_monetary_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  EXECUTE format('REVOKE ALL ON reconforge.%I FROM PUBLIC',n);
 END LOOP;
END $cr149storage$;
"""

DOWNGRADE_PREFLIGHT_SQL = r"""
DO $cr149storage$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders WHERE source->>'schema_version'='stock-sales-monetary-order-v2')
 OR EXISTS(SELECT 1 FROM reconforge.stock_sales_commands WHERE request->>'protocol_version'='2' OR result->>'schema_version'='stock-sales-monetary-v2')
 OR EXISTS(SELECT 1 FROM reconforge.operational_fx_sources WHERE payload->>'schema_version'='operational-fx-stock-source-v2')
 OR EXISTS(SELECT 1 FROM reconforge.operational_fx_plans WHERE payload->>'schema_version'='operational-fx-stock-plan-v2')
 OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number)~'^(CR3|CRF3|CR3R|CRF3R)-' OR upper(id)~'^(CR3|CRF3|CR3R|CRF3R)-')
 OR EXISTS(SELECT 1 FROM reconforge.stock_sales_monetary_origins)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_plans)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_entries)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_events)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_history)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_commands) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',
   MESSAGE='Monetary Stock downgrade refuses retained source, command or immutable evidence; restore the verified backup';
 END IF;
END $cr149storage$;
"""

DROP_STORAGE_SQL = r"""
DROP TABLE reconforge.customer_partial_return_monetary_commands,
 reconforge.customer_partial_return_monetary_restorations,reconforge.customer_partial_return_monetary_history,
 reconforge.customer_partial_return_monetary_events,reconforge.customer_partial_return_monetary_entries,
 reconforge.customer_partial_return_monetary_plans,reconforge.stock_sales_monetary_origins;
"""
