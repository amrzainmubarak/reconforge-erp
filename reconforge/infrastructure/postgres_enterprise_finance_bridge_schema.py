"""Frozen0154 source-owned financial bridge schema; no automatic posting."""

UPGRADE_SQL = r"""

ALTER TABLE reconforge.project_milestones ADD COLUMN IF NOT EXISTS organization_id TEXT;
ALTER TABLE reconforge.project_milestones ADD COLUMN IF NOT EXISTS legal_entity_id TEXT;
ALTER TABLE reconforge.project_milestone_invoices ADD COLUMN IF NOT EXISTS organization_id TEXT;
ALTER TABLE reconforge.project_milestone_invoices ADD COLUMN IF NOT EXISTS legal_entity_id TEXT;
ALTER TABLE reconforge.intercompany_profit_in_stock_rules ADD COLUMN IF NOT EXISTS organization_id TEXT;
ALTER TABLE reconforge.intercompany_profit_in_stock_rules ADD COLUMN IF NOT EXISTS legal_entity_id TEXT;
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations ADD COLUMN IF NOT EXISTS organization_id TEXT;
ALTER TABLE reconforge.intercompany_profit_in_stock_eliminations ADD COLUMN IF NOT EXISTS legal_entity_id TEXT;

CREATE TABLE IF NOT EXISTS reconforge.enterprise_finance_bindings (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 organization_id TEXT NOT NULL, legal_entity_id TEXT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('ProjectMilestone','ProfitInStock','Reversal')),
 source_id TEXT NOT NULL, source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=2097152),
 entry_id TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase IN ('Draft','Reviewed','Posted')),
 preparer_id TEXT NOT NULL, reviewer_id TEXT, poster_id TEXT, effect_id TEXT,
 reverses_binding_id TEXT, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,workspace_id,source_kind,source_id), UNIQUE(tenant_id,entry_id),
 UNIQUE(tenant_id,reverses_binding_id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,reverses_binding_id) REFERENCES reconforge.enterprise_finance_bindings(tenant_id,id),
 FOREIGN KEY(tenant_id,preparer_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,poster_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 CHECK((phase='Draft' AND reviewer_id IS NULL AND poster_id IS NULL AND effect_id IS NULL)
    OR (phase='Reviewed' AND reviewer_id IS NOT NULL AND reviewer_id<>preparer_id AND poster_id IS NULL AND effect_id IS NULL)
    OR (phase='Posted' AND reviewer_id IS NOT NULL AND reviewer_id<>preparer_id AND poster_id IS NOT NULL
        AND poster_id NOT IN(preparer_id,reviewer_id) AND effect_id IS NOT NULL)),
 CHECK((source_kind='Reversal')=(reverses_binding_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS reconforge.enterprise_finance_commands (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, organization_id TEXT NOT NULL, legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),
 operation TEXT NOT NULL CHECK(operation IN ('prepare','review','post','reverse')),
 actor_id TEXT NOT NULL, request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 binding_id TEXT NOT NULL, response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=2097152),
 PRIMARY KEY(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,binding_id) REFERENCES reconforge.enterprise_finance_bindings(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
ALTER TABLE reconforge.enterprise_finance_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.enterprise_finance_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.enterprise_finance_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.enterprise_finance_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY enterprise_finance_scope ON reconforge.enterprise_finance_bindings
 USING(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true)
 AND organization_id=current_setting('app.organization_id',true) AND legal_entity_id=current_setting('app.legal_entity_id',true))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true)
 AND organization_id=current_setting('app.organization_id',true) AND legal_entity_id=current_setting('app.legal_entity_id',true));
CREATE POLICY enterprise_finance_scope ON reconforge.enterprise_finance_commands
 USING(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true)
 AND organization_id=current_setting('app.organization_id',true) AND legal_entity_id=current_setting('app.legal_entity_id',true))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true)
 AND organization_id=current_setting('app.organization_id',true) AND legal_entity_id=current_setting('app.legal_entity_id',true));

CREATE FUNCTION reconforge.enterprise_finance_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Financial source history is append-only' USING ERRCODE='23514'; END IF;
 IF (to_jsonb(NEW)-ARRAY['phase','reviewer_id','poster_id','effect_id'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['phase','reviewer_id','poster_id','effect_id']) THEN
  RAISE EXCEPTION 'Financial source binding is immutable' USING ERRCODE='23514';
 END IF;
 IF NOT ((OLD.phase='Draft' AND NEW.phase='Reviewed') OR (OLD.phase='Reviewed' AND NEW.phase='Posted')) THEN
  RAISE EXCEPTION 'Illegal financial source transition' USING ERRCODE='23514';
 END IF;
 IF NEW.phase='Reviewed' AND NOT EXISTS(SELECT 1 FROM reconforge.finance_entries e
    WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.entry_id AND e.status='Validated'
      AND e.preparer_actor_id=NEW.preparer_id AND e.validator_actor_id=NEW.reviewer_id) THEN
  RAISE EXCEPTION 'Independent canonical validation is required' USING ERRCODE='23514';
 END IF;
 IF NEW.phase='Posted' AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects e
    WHERE e.tenant_id=NEW.tenant_id AND e.entry_id=NEW.entry_id AND e.id=NEW.effect_id AND e.posted_actor_id=NEW.poster_id) THEN
  RAISE EXCEPTION 'Canonical posting effect is required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER enterprise_finance_binding_immutable BEFORE UPDATE OR DELETE ON reconforge.enterprise_finance_bindings
 FOR EACH ROW EXECUTE FUNCTION reconforge.enterprise_finance_binding_immutable();
CREATE FUNCTION reconforge.enterprise_finance_command_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Financial command receipts are append-only' USING ERRCODE='23514'; END $$;
CREATE TRIGGER enterprise_finance_command_immutable BEFORE UPDATE OR DELETE ON reconforge.enterprise_finance_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.enterprise_finance_command_immutable();

-- Legacy sources keep their recorded nullable origin. New scoped sources and
-- financial bindings must never become visible in another workspace/entity.
DO $scope$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['project_milestones','project_milestone_invoices',
   'intercompany_profit_in_stock_rules','intercompany_profit_in_stock_eliminations'] LOOP
  EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I',t);
  EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I
   USING(tenant_id=current_setting(''app.tenant_id'',true)
    AND workspace_id=current_setting(''app.workspace_id'',true)
    AND (organization_id IS NULL OR organization_id=current_setting(''app.organization_id'',true))
    AND (legal_entity_id IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true)))
   WITH CHECK(tenant_id=current_setting(''app.tenant_id'',true)
    AND workspace_id=current_setting(''app.workspace_id'',true)
    AND (organization_id IS NULL OR organization_id=current_setting(''app.organization_id'',true))
    AND (legal_entity_id IS NULL OR legal_entity_id=current_setting(''app.legal_entity_id'',true)))',t);
 END LOOP;
END $scope$;

CREATE FUNCTION reconforge.enterprise_finance_source_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound BOOLEAN; v JSONB;
BEGIN
 v:=to_jsonb(OLD);
 SELECT EXISTS(SELECT 1 FROM reconforge.enterprise_finance_bindings b
  WHERE b.tenant_id=v->>'tenant_id' AND b.workspace_id=v->>'workspace_id' AND (
   (TG_TABLE_NAME='project_milestone_invoices' AND b.source_kind='ProjectMilestone' AND b.source_id=v->>'invoice_id') OR
   (TG_TABLE_NAME='project_milestones' AND b.source_kind='ProjectMilestone' AND b.payload#>>'{source_snapshot,milestone,milestone_id}'=v->>'milestone_id') OR
   (TG_TABLE_NAME='intercompany_profit_in_stock_eliminations' AND b.source_kind='ProfitInStock' AND b.source_id=v->>'elimination_id') OR
   (TG_TABLE_NAME='intercompany_profit_in_stock_rules' AND b.source_kind='ProfitInStock' AND b.payload#>>'{source_snapshot,rule,rule_id}'=v->>'rule_id')
  )) INTO bound;
 IF bound AND (TG_OP='DELETE' OR to_jsonb(NEW) IS DISTINCT FROM v) THEN
  RAISE EXCEPTION 'Prepared financial source is immutable; use its reviewed full inverse' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
DO $freeze$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['project_milestones','project_milestone_invoices',
   'intercompany_profit_in_stock_rules','intercompany_profit_in_stock_eliminations'] LOOP
  EXECUTE format('CREATE TRIGGER enterprise_finance_source_frozen BEFORE UPDATE OR DELETE ON reconforge.%I
   FOR EACH ROW EXECUTE FUNCTION reconforge.enterprise_finance_source_frozen()',t);
 END LOOP;
END $freeze$;

CREATE FUNCTION reconforge.enterprise_finance_entry_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE eid TEXT; b TEXT; v JSONB; values_ JSONB[];
BEGIN
 -- Inspect both endpoints: moving an unrelated line/dimension onto a sealed
 -- entry must be refused just like altering a line already owned by it.
 IF TG_OP='INSERT' THEN values_:=ARRAY[to_jsonb(NEW)];
 ELSIF TG_OP='DELETE' THEN values_:=ARRAY[to_jsonb(OLD)];
 ELSE values_:=ARRAY[to_jsonb(OLD),to_jsonb(NEW)]; END IF;
 FOREACH v IN ARRAY values_ LOOP
  IF TG_TABLE_NAME='finance_entries' THEN eid:=v->>'id';
  ELSIF TG_TABLE_NAME='finance_entry_lines' THEN eid:=v->>'entry_id';
  ELSE SELECT entry_id INTO eid FROM reconforge.finance_entry_lines
    WHERE tenant_id=v->>'tenant_id' AND id=v->>'entry_line_id'; END IF;
  SELECT id INTO b FROM reconforge.enterprise_finance_bindings
   WHERE tenant_id=v->>'tenant_id' AND entry_id=eid;
  IF b IS NOT NULL THEN
   IF TG_TABLE_NAME<>'finance_entries' OR TG_OP<>'UPDATE'
      OR current_setting('app.enterprise_finance_binding',true) IS DISTINCT FROM b THEN
    RAISE EXCEPTION 'Prepared source ledger is immutable outside its source command' USING ERRCODE='23514';
   END IF;
   IF (to_jsonb(NEW)-ARRAY['status','validated_by','validated_at','validation_reason','validator_actor_id',
       'validation_digest','validation_contract_version','updated_at'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','validated_by','validated_at','validation_reason','validator_actor_id',
       'validation_digest','validation_contract_version','updated_at']) THEN
    RAISE EXCEPTION 'Original source ledger values and policy are immutable' USING ERRCODE='23514';
   END IF;
  END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER enterprise_finance_entry_frozen BEFORE UPDATE OR DELETE ON reconforge.finance_entries
 FOR EACH ROW EXECUTE FUNCTION reconforge.enterprise_finance_entry_frozen();
CREATE TRIGGER enterprise_finance_entry_frozen BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_entry_lines
 FOR EACH ROW EXECUTE FUNCTION reconforge.enterprise_finance_entry_frozen();
CREATE TRIGGER enterprise_finance_entry_frozen BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_entry_line_dimensions
 FOR EACH ROW EXECUTE FUNCTION reconforge.enterprise_finance_entry_frozen();

"""

DOWNGRADE_SQL = r"""

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.enterprise_finance_bindings) THEN
  RAISE EXCEPTION 'Populated financial source bindings require forward recovery; downgrade refused';
 END IF;
END $$;
DO $unfreeze$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['project_milestones','project_milestone_invoices',
   'intercompany_profit_in_stock_rules','intercompany_profit_in_stock_eliminations'] LOOP
  EXECUTE format('DROP TRIGGER enterprise_finance_source_frozen ON reconforge.%I',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['finance_entries','finance_entry_lines','finance_entry_line_dimensions'] LOOP
  EXECUTE format('DROP TRIGGER enterprise_finance_entry_frozen ON reconforge.%I',t);
 END LOOP;
END $unfreeze$;
DROP FUNCTION reconforge.enterprise_finance_source_frozen();
DROP FUNCTION reconforge.enterprise_finance_entry_frozen();
DROP TABLE reconforge.enterprise_finance_commands;
DROP TABLE reconforge.enterprise_finance_bindings;
DROP FUNCTION reconforge.enterprise_finance_command_immutable();
DROP FUNCTION reconforge.enterprise_finance_binding_immutable();
-- Retain nullable source-origin columns: deleting populated lineage is not a rollback.

"""
