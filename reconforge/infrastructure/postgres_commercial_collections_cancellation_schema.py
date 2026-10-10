"""Governed release of unposted collection claims; original evidence stays sealed."""

from reconforge.infrastructure.postgres_commercial_collections_extension import UPGRADE_SQL as _EXTENSION
from reconforge.infrastructure.postgres_commercial_collections_schema import REVERSE_CLOSE_SQL
from reconforge.infrastructure.postgres_commercial_collections_schema import UPGRADE_SQL as _ORIGINAL


def _function(source: str, name: str, delimiter: str = "$fi$") -> str:
    start = source.index("CREATE FUNCTION reconforge." + name + "(")
    end = source.index("END " + delimiter + ";", start) + len("END " + delimiter + ";")
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Retained commercial collection closure contract differs")
    return source.replace(old, new, 1)


_CLOSE = _function(_ORIGINAL, "collection_close")
_CLOSE = _replace(_CLOSE, "allocated NUMERIC; c RECORD;", "allocated NUMERIC; c RECORD; cancellation RECORD;")
_CLOSE = _replace(_CLOSE,
    "SELECT * INTO l FROM reconforge.commercial_collection_links WHERE tenant_id=t AND plan_id=i;",
    """SELECT * INTO l FROM reconforge.commercial_collection_links WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO cancellation FROM reconforge.commercial_collection_cancellations WHERE tenant_id=t AND plan_id=i;
 IF (p.phase=3) IS DISTINCT FROM (cancellation IS NOT NULL) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='commercial_collection_owner_phase',MESSAGE='Cancellation phase requires its retained independent evidence'; END IF;""")
_CLOSE = _replace(_CLOSE, "IF p.phase>=1 AND", "IF (p.phase IN(1,2) OR (p.phase=3 AND r IS NOT NULL)) AND")
_CLOSE = _replace(_CLOSE,
    "ELSE\n SELECT * INTO f FROM reconforge.finance_posting_effects",
    """ELSIF p.phase=3 THEN
 IF cancellation.cancelled_actor_id=maker OR (r IS NOT NULL AND cancellation.cancelled_actor_id=r.reviewer_actor_id)
 OR l IS NOT NULL OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.entry_id=p.entry_id)
 OR e.status IS DISTINCT FROM (CASE WHEN r IS NULL THEN 'Draft' ELSE 'Validated' END)
 OR NOT reconforge.collection_event(t,i,cancellation.audit_event_id,cancellation.outbox_event_id,
 cancellation.cancelled_actor_id,'commercial_collection_cancelled',jsonb_build_object('plan_digest',seal,'reason',cancellation.reason)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='commercial_collection_owner_phase',MESSAGE='Cancelled installment retains its original unposted draft or reviewed entry and independent release'; END IF;
 ELSE
 SELECT * INTO f FROM reconforge.finance_posting_effects""")
_CLOSE = _replace(_CLOSE,
    "FOR c IN SELECT * FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i LOOP",
    """FOR c IN SELECT * FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i LOOP
 IF c.operation='cancel' THEN
  IF cancellation IS NULL OR (c.workspace_id,c.organization_id,c.legal_entity_id) IS DISTINCT FROM
   (p.workspace_id,p.organization_id,p.legal_entity_id)
  OR c.actor_id IS DISTINCT FROM cancellation.cancelled_actor_id
  OR reconforge.irp_digest(c.request_json) IS DISTINCT FROM c.request_digest
  OR c.request_json IS DISTINCT FROM jsonb_build_object('operation','cancel','actor_id',cancellation.cancelled_actor_id,
   'request',jsonb_build_object('plan_id',i,'expected_plan_digest',seal,'reason',cancellation.reason))
  OR c.response_json IS DISTINCT FROM p.payload||jsonb_build_object('phase',3,'status','Cancelled',
   'reviewer_actor_id',r.reviewer_actor_id,'posting_effect_id',NULL,'receipt_id',NULL,
   'cancelled_actor_id',cancellation.cancelled_actor_id,'cancellation_reason',cancellation.reason) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='commercial_collection_owner_phase',MESSAGE='Cancellation command must retain its exact actor request and terminal acknowledgement'; END IF;
  CONTINUE;
 END IF;""")
_CLOSE = _replace(_CLOSE,
    "OR (p.phase>=1 AND NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i AND operation='review'))",
    "OR ((p.phase IN(1,2) OR (p.phase=3 AND r IS NOT NULL)) AND NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i AND operation='review'))")
_CLOSE = _replace(_CLOSE,
    "OR (p.phase=2 AND NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i AND operation='post')) THEN",
    """OR (p.phase=2 AND NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i AND operation='post'))
 OR (p.phase=3 AND NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_commands WHERE tenant_id=t AND plan_id=i AND operation='cancel')) THEN""")

_PROTECT = _replace(_function(_ORIGINAL, "collection_protect"),
    "IF NEW.phase=OLD.phase+1 AND",
    "IF ((OLD.phase<2 AND NEW.phase=OLD.phase+1) OR (OLD.phase IN(0,1) AND NEW.phase=3)) AND")
_ADMIT = _function(_EXTENSION, "collection_command_admit", "$ca$")
_ADMIT = _replace(_ADMIT, "NEW.operation='review'", "NEW.operation IN('review','cancel')")
_ADMIT = _replace(_ADMIT, "WHEN'review' THEN'finance_core.validate'", "WHEN'review' THEN'finance_core.validate' WHEN'cancel' THEN'finance_core.validate'")

UPGRADE_SQL = r"""
ALTER TABLE reconforge.commercial_collection_plans DROP CONSTRAINT commercial_collection_plans_phase_check;
ALTER TABLE reconforge.commercial_collection_plans ADD CONSTRAINT commercial_collection_plans_phase_check CHECK(phase BETWEEN 0 AND 3);
ALTER TABLE reconforge.commercial_collection_commands DROP CONSTRAINT commercial_collection_commands_operation_check;
ALTER TABLE reconforge.commercial_collection_commands ADD CONSTRAINT commercial_collection_commands_operation_check CHECK(operation IN('prepare','review','post','cancel'));
DROP INDEX reconforge.commercial_collection_receipt_name;
CREATE UNIQUE INDEX commercial_collection_receipt_name ON reconforge.commercial_collection_plans(tenant_id,workspace_id,(payload->>'receipt_number')) WHERE phase<>3;
CREATE TABLE reconforge.commercial_collection_cancellations (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,cancelled_actor_id TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500 AND btrim(reason)<>''),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.commercial_collection_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
ALTER TABLE reconforge.commercial_collection_cancellations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.commercial_collection_cancellations FORCE ROW LEVEL SECURITY;
CREATE POLICY scope ON reconforge.commercial_collection_cancellations USING(EXISTS(
 SELECT 1 FROM reconforge.commercial_collection_plans p WHERE p.tenant_id=commercial_collection_cancellations.tenant_id
 AND p.id=commercial_collection_cancellations.plan_id)) WITH CHECK(EXISTS(
 SELECT 1 FROM reconforge.commercial_collection_plans p WHERE p.tenant_id=commercial_collection_cancellations.tenant_id
 AND p.id=commercial_collection_cancellations.plan_id));
CREATE FUNCTION reconforge.collection_cancel_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ca$
DECLARE p RECORD;reviewer TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.commercial_collection_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id FOR UPDATE;
 SELECT reviewer_actor_id INTO reviewer FROM reconforge.commercial_collection_reviews WHERE tenant_id=NEW.tenant_id AND plan_id=NEW.plan_id;
 IF p IS NULL OR p.phase NOT IN(0,1) OR NEW.cancelled_actor_id=p.payload->>'preparer_actor_id'
 OR NEW.cancelled_actor_id IS NOT DISTINCT FROM reviewer
 OR NOT reconforge.irp_scope(p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.cancelled_actor_id,'sales.approve')
 OR NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.cancelled_actor_id,'finance_core.validate')
 OR NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.cancelled_actor_id,'receivables.manage') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='commercial_collection_owner_phase',MESSAGE='Cancellation requires current independent scoped human authority over an unposted plan'; END IF;
 RETURN NEW;
END $ca$;
CREATE TRIGGER cancellation_admission BEFORE INSERT ON reconforge.commercial_collection_cancellations
 FOR EACH ROW EXECUTE FUNCTION reconforge.collection_cancel_admit();
CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.commercial_collection_cancellations
 FOR EACH ROW EXECUTE FUNCTION reconforge.collection_protect();
CREATE CONSTRAINT TRIGGER collection_owner_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.commercial_collection_cancellations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.collection_reverse_close();
""" + _PROTECT + _CLOSE + _ADMIT + REVERSE_CLOSE_SQL

DOWNGRADE_SQL = r"""
DO $ca$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.commercial_collection_cancellations)
 OR EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans WHERE phase=3) THEN
 RAISE EXCEPTION 'Cancellation downgrade refuses to discard retained release evidence'; END IF; END $ca$;
DROP TABLE reconforge.commercial_collection_cancellations;
DROP FUNCTION reconforge.collection_cancel_admit();
DROP INDEX reconforge.commercial_collection_receipt_name;
CREATE UNIQUE INDEX commercial_collection_receipt_name ON reconforge.commercial_collection_plans(tenant_id,workspace_id,(payload->>'receipt_number'));
ALTER TABLE reconforge.commercial_collection_plans DROP CONSTRAINT commercial_collection_plans_phase_check;
ALTER TABLE reconforge.commercial_collection_plans ADD CONSTRAINT commercial_collection_plans_phase_check CHECK(phase BETWEEN 0 AND 2);
ALTER TABLE reconforge.commercial_collection_commands DROP CONSTRAINT commercial_collection_commands_operation_check;
ALTER TABLE reconforge.commercial_collection_commands ADD CONSTRAINT commercial_collection_commands_operation_check CHECK(operation IN('prepare','review','post'));
""" + _function(_ORIGINAL, "collection_protect") + _function(_ORIGINAL, "collection_close") + _function(_EXTENSION, "collection_command_admit", "$ca$") + REVERSE_CLOSE_SQL
