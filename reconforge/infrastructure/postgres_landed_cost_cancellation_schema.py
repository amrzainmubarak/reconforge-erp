"""Retained unreceived bundle cancellation and exact reservation release."""
from collections.abc import Mapping
from typing import Any

from reconforge.infrastructure.postgres_landed_cost_schema import RECEIPT_CHARGE_SQL, REVERSE_CLOSE_SQL

_TABLE_SQL = r"""
DO $lc$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Cancellation migration requires forced-RLS migration authority'; END IF;
END $lc$;
CREATE TABLE reconforge.landed_cost_cancellations (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,workspace_id TEXT NOT NULL,source_phase INTEGER NOT NULL CHECK(source_phase IN(0,1)),
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 request_json JSONB NOT NULL CHECK(octet_length(request_json::text)<=2048),response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=131072),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),UNIQUE(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.landed_cost_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
ALTER TABLE reconforge.landed_cost_cancellations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.landed_cost_cancellations FORCE ROW LEVEL SECURITY;
CREATE POLICY scope ON reconforge.landed_cost_cancellations USING(EXISTS(SELECT 1 FROM reconforge.landed_cost_plans p
 WHERE p.tenant_id=landed_cost_cancellations.tenant_id AND p.id=plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.landed_cost_plans p
 WHERE p.tenant_id=landed_cost_cancellations.tenant_id AND p.id=plan_id));
CREATE TRIGGER retained BEFORE UPDATE OR DELETE ON reconforge.landed_cost_cancellations FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_protect();
CREATE FUNCTION reconforge.landed_cost_cancel_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
DECLARE p RECORD;permission TEXT;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_cancellation',MESSAGE='Cancellation requires READ COMMITTED'; END IF;
 SELECT * INTO p FROM reconforge.landed_cost_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id FOR UPDATE;
 PERFORM 1 FROM reconforge.procurement_partial_orders WHERE tenant_id=p.tenant_id AND id=p.order_id FOR UPDATE;
 IF p IS NULL OR NEW.source_phase IS DISTINCT FROM p.phase OR p.phase NOT IN(0,1)
 OR NEW.workspace_id IS DISTINCT FROM p.workspace_id OR NOT reconforge.irp_scope(p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR NEW.actor_id=p.payload->>'preparer_actor_id' OR EXISTS(SELECT 1 FROM reconforge.landed_cost_reviews r
 WHERE r.tenant_id=p.tenant_id AND r.plan_id=p.id AND r.reviewer_actor_id=NEW.actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_cancellation',MESSAGE='Unreceived cancellation requires an independent scoped human'; END IF;
 FOREACH permission IN ARRAY ARRAY['payables.read','inventory.read','finance_core.read','payables.settle','payables.approve',
 'inventory.post','inventory.valuation.approve','finance_core.validate'] LOOP
 IF NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.actor_id,permission) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_cancellation',MESSAGE='Cancellation requires current persisted reviewer authority'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM reconforge.landed_cost_commands WHERE tenant_id=p.tenant_id AND workspace_id=p.workspace_id AND command_id=NEW.command_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_cancellation',MESSAGE='Cancellation command already belongs to a retained source operation'; END IF;
 RETURN NEW;
END $lc$;
CREATE TRIGGER cancellation_admit BEFORE INSERT ON reconforge.landed_cost_cancellations
 FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_cancel_admit();
CREATE FUNCTION reconforge.landed_cost_command_cancel_collision() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.landed_cost_cancellations WHERE tenant_id=NEW.tenant_id AND workspace_id=NEW.workspace_id AND command_id=NEW.command_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_cancellation',MESSAGE='Command identifier belongs to immutable cancellation evidence'; END IF;
 RETURN NEW;
END $lc$;
CREATE TRIGGER cancellation_command_collision BEFORE INSERT ON reconforge.landed_cost_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_command_cancel_collision();
CREATE FUNCTION reconforge.pp_receipt_cancelled(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $lc$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts d JOIN reconforge.procurement_partial_receipts q
 ON q.tenant_id=d.tenant_id AND q.order_id=d.order_id JOIN reconforge.inventory_receipt_plans r ON r.tenant_id=q.tenant_id AND r.id=q.receipt_plan_id
 WHERE d.tenant_id=t AND d.id=i AND r.total_value_minor<>q.total_minor) THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.landed_cost_allocations a JOIN reconforge.landed_cost_cancellations c
 ON c.tenant_id=a.tenant_id AND c.plan_id=a.plan_id WHERE a.tenant_id=t AND a.receipt_id=i);
END
$lc$;
ALTER FUNCTION reconforge.landed_cost_close(TEXT,TEXT) RENAME TO landed_cost_close_pre_cancel;
CREATE FUNCTION reconforge.landed_cost_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
DECLARE p RECORD;c RECORD;expected JSONB;projection JSONB;members INTEGER;freight NUMERIC;duty NUMERIC;
BEGIN
 PERFORM reconforge.landed_cost_close_pre_cancel(t,i);
 SELECT * INTO p FROM reconforge.landed_cost_plans WHERE tenant_id=t AND id=i;
 SELECT count(*),sum(freight_minor),sum(duty_minor) INTO members,freight,duty
 FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i;
 IF members NOT BETWEEN 1 AND 128
 OR CASE WHEN jsonb_typeof(p.payload#>'{request,lines}')='array' THEN jsonb_array_length(p.payload#>'{request,lines}') ELSE 0 END<>members
 OR freight IS DISTINCT FROM (p.payload#>>'{request,freight_minor}')::numeric
 OR duty IS DISTINCT FROM (p.payload#>>'{request,duty_minor}')::numeric THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Allocations must conserve all paid charges and source members'; END IF;
 -- Refresh installed 0123 owners too: ordinary-source query avoidance must
 -- never permit a charged owner to lose its exact native capitalization.
 IF EXISTS(SELECT 1 FROM reconforge.landed_cost_allocations a JOIN reconforge.procurement_partial_receipts d
 ON d.tenant_id=a.tenant_id AND d.id=a.receipt_id JOIN reconforge.inventory_receipt_plans r
 ON r.tenant_id=d.tenant_id AND r.id=d.receipt_plan_id WHERE a.tenant_id=t AND a.plan_id=i
 AND r.total_value_minor::numeric<>a.base_minor::numeric+a.freight_minor+a.duty_minor) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Charged owner requires its exact capitalized native receipt cost'; END IF;
 SELECT * INTO c FROM reconforge.landed_cost_cancellations WHERE tenant_id=t AND plan_id=i;
 IF c IS NULL THEN RETURN; END IF;
 expected:=jsonb_build_object('operation','cancel','actor_id',c.actor_id,'request',jsonb_build_object(
 'plan_id',i,'expected_plan_digest',p.plan_digest,'reason',c.reason));
 projection:=jsonb_build_object('actor_id',c.actor_id,'reason',c.reason,'command_id',c.command_id,'audit_event_id',c.audit_event_id,'outbox_event_id',c.outbox_event_id);
 IF p.phase<>c.source_phase OR p.phase NOT IN(0,1) OR c.workspace_id<>p.workspace_id
 OR c.actor_id=p.payload->>'preparer_actor_id' OR EXISTS(SELECT 1 FROM reconforge.landed_cost_reviews r WHERE r.tenant_id=t AND r.plan_id=i AND r.reviewer_actor_id=c.actor_id)
 OR c.request_json IS DISTINCT FROM expected OR c.request_digest IS DISTINCT FROM reconforge.irp_digest(expected)
 OR c.response_json IS DISTINCT FROM reconforge.landed_cost_ack(t,i,c.source_phase)||jsonb_build_object('status','Cancelled','cancellation',projection)
 OR NOT reconforge.landed_cost_event(t,i,c.audit_event_id,c.outbox_event_id,c.actor_id,'landed_cost_cancelled',p.plan_digest)
 OR EXISTS(SELECT 1 FROM reconforge.landed_cost_links WHERE tenant_id=t AND plan_id=i)
 OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=p.entry_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_cancellation',MESSAGE='Cancellation must retain exact original unreceived phase, command and evidence'; END IF;
END $lc$;
CREATE CONSTRAINT TRIGGER landed_cost_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.landed_cost_cancellations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_reverse_close();
ALTER FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT) RENAME TO pp_verify_multiline_pre_cancel;
DO $lc$ DECLARE definition TEXT;needle TEXT:='SELECT COALESCE(sum(quantity),0) INTO received FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND order_line_id=ol.id;';BEGIN
 definition:=pg_get_functiondef('reconforge.pp_verify_multiline_pre_cancel(text,text)'::regprocedure);
 IF length(definition)-length(replace(definition,needle,''))<>length(needle) THEN RAISE EXCEPTION 'Unsupported prior multiline capacity closure'; END IF;
 definition:=replace(definition,'reconforge.pp_verify_multiline_pre_cancel','reconforge.pp_verify_multiline');
 definition:=replace(definition,'OR r.total_value_minor::numeric<>d.total_minor::numeric+COALESCE((SELECT freight_minor::numeric+duty_minor FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND receipt_id=d.id),0)',
 'OR r.total_value_minor::numeric<>d.total_minor::numeric+reconforge.landed_cost_receipt_charge(t,d.id,r.total_value_minor,d.total_minor)');
 definition:=replace(definition,needle,'SELECT COALESCE(sum(quantity),0) INTO received FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND order_line_id=ol.id AND NOT reconforge.pp_receipt_cancelled(t,id);');
 EXECUTE definition;
END $lc$;
"""

UPGRADE_SQL = RECEIPT_CHARGE_SQL + REVERSE_CLOSE_SQL + _TABLE_SQL

DOWNGRADE_SQL = r"""
DO $lc$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.landed_cost_cancellations) THEN
 RAISE EXCEPTION 'Retained cancellations require forward correction or verified pre-upgrade restore'; END IF; END $lc$;
DROP FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT);
ALTER FUNCTION reconforge.pp_verify_multiline_pre_cancel(TEXT,TEXT) RENAME TO pp_verify_multiline;
DROP FUNCTION reconforge.landed_cost_close(TEXT,TEXT);
ALTER FUNCTION reconforge.landed_cost_close_pre_cancel(TEXT,TEXT) RENAME TO landed_cost_close;
DROP FUNCTION reconforge.pp_receipt_cancelled(TEXT,TEXT);
DROP TABLE reconforge.landed_cost_cancellations;
DROP FUNCTION reconforge.landed_cost_cancel_admit();
DROP TRIGGER cancellation_command_collision ON reconforge.landed_cost_commands;
DROP FUNCTION reconforge.landed_cost_command_cancel_collision();
"""


def install_postgres_landed_cost_cancellation(connection: Any) -> None:
    row = connection.execute("SELECT to_regclass('reconforge.landed_cost_cancellations') AS installed").fetchone()
    if (row["installed"] if isinstance(row, Mapping) else row[0]) is None:
        with connection.transaction():
            connection.execute(UPGRADE_SQL)
