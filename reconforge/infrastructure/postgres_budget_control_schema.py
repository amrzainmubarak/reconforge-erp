"""PostgreSQL exact budget schema used only by the reviewed Alembic revision."""

POSTGRES_BUDGET_CONTROL_SCHEMA_SQL = r"""
CREATE TABLE reconforge.budget_envelopes (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 period_id TEXT NOT NULL,budget_code TEXT NOT NULL,name TEXT NOT NULL,currency_code TEXT NOT NULL,
 limit_minor BIGINT NOT NULL CHECK(limit_minor BETWEEN 1 AND 9000000000000000000),
 reserved_minor BIGINT NOT NULL DEFAULT 0 CHECK(reserved_minor>=0),consumed_minor BIGINT NOT NULL DEFAULT 0 CHECK(consumed_minor>=0),
 currency_precision INTEGER NOT NULL,currency_rounding_policy TEXT NOT NULL,currency_registry_version TEXT NOT NULL,currency_registry_digest TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('Draft','Submitted','Approved')),created_by TEXT NOT NULL,submitted_by TEXT,approved_by TEXT,
 reason TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,row_version BIGINT NOT NULL CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,budget_code),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id),
 FOREIGN KEY(tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code),
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest),
 FOREIGN KEY(tenant_id,created_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,submitted_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,approved_by) REFERENCES reconforge.identity_users(tenant_id,id),CHECK(reserved_minor<=limit_minor-consumed_minor)
);
CREATE TABLE reconforge.budget_commitment_events (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,budget_id TEXT NOT NULL,commitment_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('Reserve','Release','Consume')),amount_minor BIGINT NOT NULL
 CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),remaining_minor BIGINT NOT NULL CHECK(remaining_minor>=0),
 operation_date TEXT NOT NULL,source_reference TEXT NOT NULL,reason TEXT NOT NULL,actor_id TEXT NOT NULL,
 created_at TEXT NOT NULL,budget_version BIGINT NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,request_digest TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,budget_id,budget_version),
 FOREIGN KEY(tenant_id,budget_id) REFERENCES reconforge.budget_envelopes(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE UNIQUE INDEX budget_reservation_identity ON reconforge.budget_commitment_events(tenant_id,budget_id,commitment_id) WHERE operation='Reserve';
CREATE UNIQUE INDEX budget_reservation_source ON reconforge.budget_commitment_events(tenant_id,budget_id,source_reference) WHERE operation='Reserve';
CREATE INDEX budget_events_commitment ON reconforge.budget_commitment_events(tenant_id,budget_id,commitment_id,budget_version DESC);
CREATE INDEX budget_envelopes_scope ON reconforge.budget_envelopes(tenant_id,workspace_id,organization_id,legal_entity_id,created_at,id);
CREATE TABLE reconforge.budget_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL,request_digest TEXT NOT NULL,budget_id TEXT NOT NULL,actor_id TEXT NOT NULL,request_json TEXT NOT NULL,result_json TEXT NOT NULL,result_digest TEXT NOT NULL,
 created_at TEXT NOT NULL,PRIMARY KEY(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,budget_id) REFERENCES reconforge.budget_envelopes(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 CHECK(octet_length(result_json)<=65536 AND jsonb_typeof(result_json::jsonb)='object'),
 CHECK(octet_length(request_json)<=65536 AND jsonb_typeof(request_json::jsonb)='object')
);
CREATE FUNCTION reconforge.budget_envelope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Budget evidence is immutable.'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.status<>'Draft' OR NEW.row_version<>1 OR NEW.reserved_minor<>0 OR NEW.consumed_minor<>0 OR NEW.submitted_by IS NOT NULL OR NEW.approved_by IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
    WHERE o.tenant_id=NEW.tenant_id AND o.id=NEW.organization_id AND o.application_workspace_id=NEW.workspace_id AND e.id=NEW.legal_entity_id AND o.active AND e.active)
   OR NOT EXISTS(SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.period_id AND p.application_workspace_id=NEW.workspace_id AND p.status='Open')
  THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Budget requires an empty Draft and canonical open scope.'; END IF;
  RETURN NEW;
 END IF;
 IF (NEW.tenant_id,NEW.id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.budget_code,NEW.name,
   NEW.currency_code,NEW.limit_minor,NEW.currency_precision,NEW.currency_rounding_policy,NEW.currency_registry_version,
   NEW.currency_registry_digest,NEW.created_by,NEW.created_at) IS DISTINCT FROM
  (OLD.tenant_id,OLD.id,OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.budget_code,OLD.name,
   OLD.currency_code,OLD.limit_minor,OLD.currency_precision,OLD.currency_rounding_policy,OLD.currency_registry_version,
   OLD.currency_registry_digest,OLD.created_by,OLD.created_at) OR NEW.row_version<>OLD.row_version+1
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Budget definition and exact policy are immutable.'; END IF;
 IF NOT (
  (OLD.status='Draft' AND NEW.status='Submitted' AND NEW.submitted_by IS NOT NULL AND NEW.approved_by IS NULL
   AND NEW.reserved_minor=OLD.reserved_minor AND NEW.consumed_minor=OLD.consumed_minor AND length(NEW.reason)>0)
  OR (OLD.status='Submitted' AND NEW.status='Approved' AND NEW.submitted_by=OLD.submitted_by AND NEW.approved_by IS NOT NULL
   AND NEW.approved_by<>OLD.created_by AND NEW.approved_by<>OLD.submitted_by
   AND NEW.reserved_minor=OLD.reserved_minor AND NEW.consumed_minor=OLD.consumed_minor AND length(NEW.reason)>0)
  OR (OLD.status='Approved' AND NEW.status=OLD.status AND NEW.submitted_by=OLD.submitted_by AND NEW.approved_by=OLD.approved_by
   AND NEW.reason=OLD.reason AND EXISTS(SELECT 1 FROM reconforge.budget_commitment_events e WHERE e.tenant_id=OLD.tenant_id AND e.budget_id=OLD.id
    AND e.budget_version=NEW.row_version AND NEW.reserved_minor=OLD.reserved_minor+
     CASE WHEN e.operation='Reserve' THEN e.amount_minor ELSE -e.amount_minor END
    AND NEW.consumed_minor=OLD.consumed_minor+CASE WHEN e.operation='Consume' THEN e.amount_minor ELSE 0 END))
 ) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Budget transition or conserved ledger update is invalid.'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER budget_envelope_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.budget_envelopes FOR EACH ROW EXECUTE FUNCTION reconforge.budget_envelope_guard();
CREATE FUNCTION reconforge.budget_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b reconforge.budget_envelopes; prior reconforge.budget_commitment_events;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Commitment evidence is immutable.'; END IF;
 SELECT * INTO b FROM reconforge.budget_envelopes WHERE tenant_id=NEW.tenant_id AND id=NEW.budget_id FOR UPDATE;
 IF b.id IS NULL OR b.status<>'Approved' OR NEW.budget_version<>b.row_version+1
  OR NOT EXISTS(SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=b.tenant_id AND p.id=b.period_id AND p.status='Open'
   AND NEW.operation_date BETWEEN p.start_date::text AND p.end_date::text)
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Commitment requires approved current budget and open period.'; END IF;
 SELECT * INTO prior FROM reconforge.budget_commitment_events WHERE tenant_id=NEW.tenant_id AND budget_id=NEW.budget_id
  AND commitment_id=NEW.commitment_id ORDER BY budget_version DESC LIMIT 1;
 IF (NEW.operation='Reserve' AND (prior.id IS NOT NULL OR NEW.amount_minor>b.limit_minor-b.reserved_minor-b.consumed_minor OR NEW.remaining_minor<>NEW.amount_minor))
  OR (NEW.operation<>'Reserve' AND (prior.id IS NULL OR NEW.amount_minor>prior.remaining_minor OR NEW.remaining_minor<>prior.remaining_minor-NEW.amount_minor OR NEW.source_reference<>prior.source_reference))
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Commitment remaining capacity or reference is invalid.'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER budget_event_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.budget_commitment_events FOR EACH ROW EXECUTE FUNCTION reconforge.budget_event_guard();
CREATE FUNCTION reconforge.budget_event_apply() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE reconforge.budget_envelopes SET reserved_minor=reserved_minor+CASE WHEN NEW.operation='Reserve' THEN NEW.amount_minor ELSE -NEW.amount_minor END,
  consumed_minor=consumed_minor+CASE WHEN NEW.operation='Consume' THEN NEW.amount_minor ELSE 0 END,row_version=NEW.budget_version,updated_at=NEW.created_at
  WHERE tenant_id=NEW.tenant_id AND id=NEW.budget_id;
 RETURN NEW;
END $$;
CREATE TRIGGER budget_event_apply AFTER INSERT ON reconforge.budget_commitment_events FOR EACH ROW EXECUTE FUNCTION reconforge.budget_event_apply();
CREATE FUNCTION reconforge.budget_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Budget command evidence is immutable.'; END $$;
CREATE TRIGGER budget_command_guard BEFORE UPDATE OR DELETE ON reconforge.budget_commands FOR EACH ROW EXECUTE FUNCTION reconforge.budget_command_guard();
ALTER TABLE reconforge.budget_envelopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.budget_envelopes FORCE ROW LEVEL SECURITY;
CREATE POLICY budget_scope ON reconforge.budget_envelopes USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
 AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));
ALTER TABLE reconforge.budget_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.budget_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY budget_scope ON reconforge.budget_commands USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
 AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));
ALTER TABLE reconforge.budget_commitment_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.budget_commitment_events FORCE ROW LEVEL SECURITY;
CREATE POLICY budget_scope ON reconforge.budget_commitment_events USING (
 tenant_id=current_setting('app.tenant_id',true) AND EXISTS(SELECT 1 FROM reconforge.budget_envelopes b WHERE b.tenant_id=budget_commitment_events.tenant_id AND b.id=budget_commitment_events.budget_id));
"""
