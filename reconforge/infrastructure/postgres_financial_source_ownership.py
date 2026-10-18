"""Source ownership directory without mutating approved financial history.

ME2 owns cost capacity and source events. Finance Core reads only its scoped,
non-personnel directory when admitting original-effect reversals. A separate
coordination version rejects stale repeatable-read claim/reversal writers.
Install after ME2 cost claim/release tables; it is part of ordered revision138.
"""

UPGRADE_SQL = r"""
CREATE TABLE reconforge.financial_effect_claim_gates (
 tenant_id TEXT NOT NULL,source_effect_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,version BIGINT NOT NULL CHECK(version BETWEEN 1 AND 9000000000000000000),
 PRIMARY KEY(tenant_id,source_effect_id),
 FOREIGN KEY(tenant_id,source_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id)
);
CREATE TABLE reconforge.financial_effect_ownership_guards (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_effect_id TEXT NOT NULL,owner_namespace TEXT NOT NULL CHECK(owner_namespace='ME2'),owner_claim_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,owner_namespace,owner_claim_id),CHECK(id=owner_claim_id),
 FOREIGN KEY(tenant_id,source_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,owner_claim_id) REFERENCES reconforge.manufacturing_execution_v2_cost_claims(tenant_id,id)
 DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX financial_effect_ownership_source ON reconforge.financial_effect_ownership_guards(tenant_id,source_effect_id,id);
CREATE TABLE reconforge.financial_effect_ownership_releases (
 tenant_id TEXT NOT NULL,guard_id TEXT NOT NULL,release_id TEXT NOT NULL,PRIMARY KEY(tenant_id,guard_id),UNIQUE(tenant_id,release_id),
 FOREIGN KEY(tenant_id,guard_id) REFERENCES reconforge.financial_effect_ownership_guards(tenant_id,id),
 FOREIGN KEY(tenant_id,release_id) REFERENCES reconforge.manufacturing_execution_v2_cost_releases(tenant_id,id)
 DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE reconforge.financial_effect_claim_gates ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.financial_effect_claim_gates FORCE ROW LEVEL SECURITY;
CREATE POLICY source_scope ON reconforge.financial_effect_claim_gates
 USING(tenant_id=current_setting('app.tenant_id',true) AND reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id));
ALTER TABLE reconforge.financial_effect_ownership_guards ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.financial_effect_ownership_guards FORCE ROW LEVEL SECURITY;
CREATE POLICY source_scope ON reconforge.financial_effect_ownership_guards
 USING(tenant_id=current_setting('app.tenant_id',true) AND reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id));
ALTER TABLE reconforge.financial_effect_ownership_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.financial_effect_ownership_releases FORCE ROW LEVEL SECURITY;
CREATE POLICY source_scope ON reconforge.financial_effect_ownership_releases
 USING(tenant_id=current_setting('app.tenant_id',true) AND EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_guards g
 WHERE g.tenant_id=financial_effect_ownership_releases.tenant_id AND g.id=financial_effect_ownership_releases.guard_id))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_guards g
 WHERE g.tenant_id=financial_effect_ownership_releases.tenant_id AND g.id=financial_effect_ownership_releases.guard_id));
CREATE FUNCTION reconforge.financial_source_assert(ok BOOLEAN,message TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_source_ownership',MESSAGE=message; END IF; END $ownership$;
CREATE FUNCTION reconforge.financial_source_projection_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE source RECORD;
BEGIN
 IF TG_OP='DELETE' THEN PERFORM reconforge.financial_source_assert(false,'Financial source coordination history cannot be removed'); END IF;
 IF TG_OP='UPDATE' THEN
  PERFORM reconforge.financial_source_assert(NEW.version=OLD.version+1 AND
   to_jsonb(NEW)-'version'=to_jsonb(OLD)-'version','Source coordination changes only its next exact version');
  RETURN NEW;
 END IF;
 SELECT * INTO source FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=NEW.source_effect_id;
 PERFORM reconforge.financial_source_assert(source.id IS NOT NULL AND
  (source.workspace_id,source.organization_id,source.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),
  'Source coordination requires the original visible effect and exact hierarchy');
 RETURN NEW;
END $ownership$;
CREATE TRIGGER source_coordination BEFORE INSERT OR UPDATE OR DELETE ON reconforge.financial_effect_claim_gates
 FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_projection_guard();
CREATE FUNCTION reconforge.touch_financial_effect_claim_gate(t TEXT,effect TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE source RECORD;
BEGIN
 SELECT * INTO source FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=effect;
 PERFORM reconforge.financial_source_assert(source.id IS NOT NULL,'The original financial source is absent or outside scope');
 INSERT INTO reconforge.financial_effect_claim_gates(tenant_id,source_effect_id,workspace_id,organization_id,legal_entity_id,version)
 VALUES(t,effect,source.workspace_id,source.organization_id,source.legal_entity_id,1)
 ON CONFLICT(tenant_id,source_effect_id) DO UPDATE SET version=reconforge.financial_effect_claim_gates.version+1;
END $ownership$;
CREATE FUNCTION reconforge.financial_source_directory_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE source RECORD;claim RECORD;owned_release RECORD;directory RECORD;
BEGIN
 IF TG_OP<>'INSERT' THEN PERFORM reconforge.financial_source_assert(false,'Source ownership and release history are immutable'); END IF;
 IF TG_TABLE_NAME='financial_effect_ownership_guards' THEN
  PERFORM reconforge.touch_financial_effect_claim_gate(NEW.tenant_id,NEW.source_effect_id);
  SELECT * INTO source FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=NEW.source_effect_id;
  SELECT * INTO claim FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=NEW.tenant_id AND id=NEW.owner_claim_id;
  PERFORM reconforge.financial_source_assert(source.id IS NOT NULL AND source.reverses_effect_id IS NULL
   AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects r WHERE r.tenant_id=NEW.tenant_id AND r.reverses_effect_id=source.id)
   AND claim.id IS NOT NULL AND claim.effect_id=source.id AND claim.state IN ('Reserved','Consumed')
   AND (claim.workspace_id,claim.organization_id,claim.legal_entity_id)=(source.workspace_id,source.organization_id,source.legal_entity_id)
   AND (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)=(source.workspace_id,source.organization_id,source.legal_entity_id),
   'Source directory requires its exact original native cost claim and unreversed effect');
 ELSE
  SELECT * INTO directory FROM reconforge.financial_effect_ownership_guards WHERE tenant_id=NEW.tenant_id AND id=NEW.guard_id;
  PERFORM reconforge.financial_source_assert(directory.id IS NOT NULL,'Source release requires its original ownership record');
  PERFORM reconforge.touch_financial_effect_claim_gate(NEW.tenant_id,directory.source_effect_id);
  SELECT * INTO owned_release FROM reconforge.manufacturing_execution_v2_cost_releases WHERE tenant_id=NEW.tenant_id AND id=NEW.release_id;
  PERFORM reconforge.financial_source_assert(owned_release.id IS NOT NULL AND owned_release.claim_id=directory.owner_claim_id
   AND (owned_release.workspace_id,owned_release.organization_id,owned_release.legal_entity_id)=
       (directory.workspace_id,directory.organization_id,directory.legal_entity_id),
   'Source release requires the exact retained operating-owner release');
 END IF;
 RETURN NEW;
END $ownership$;
CREATE TRIGGER source_directory_immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.financial_effect_ownership_guards
 FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_guard();
CREATE TRIGGER source_release_immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.financial_effect_ownership_releases
 FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_guard();
CREATE FUNCTION reconforge.financial_source_claim_close(t TEXT,claim_id TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE claim RECORD;directory RECORD;owned_release RECORD;directory_release RECORD;
BEGIN
 SELECT c.* INTO claim FROM reconforge.manufacturing_execution_v2_cost_claims c WHERE c.tenant_id=t AND c.id=$2;
 SELECT g.* INTO directory FROM reconforge.financial_effect_ownership_guards g WHERE g.tenant_id=t AND g.owner_claim_id=$2 AND g.owner_namespace='ME2';
 PERFORM reconforge.financial_source_assert(claim.id IS NOT NULL AND directory.id IS NOT NULL
  AND directory.source_effect_id=claim.effect_id AND
  (directory.workspace_id,directory.organization_id,directory.legal_entity_id)=(claim.workspace_id,claim.organization_id,claim.legal_entity_id),
  'Every native cost claim retains one exact finance ownership guard');
 SELECT r.* INTO owned_release FROM reconforge.manufacturing_execution_v2_cost_releases r WHERE r.tenant_id=t AND r.claim_id=claim.id;
 SELECT r.* INTO directory_release FROM reconforge.financial_effect_ownership_releases r WHERE r.tenant_id=t AND r.guard_id=directory.id;
 PERFORM reconforge.financial_source_assert(
  (claim.state='Released' AND owned_release.id IS NOT NULL AND owned_release.order_id=claim.order_id AND directory_release.release_id=owned_release.id)
  OR (claim.state IN ('Reserved','Consumed') AND owned_release.id IS NULL AND directory_release.guard_id IS NULL),
  'Finance source release and operating claim state must close together');
END $ownership$;
CREATE FUNCTION reconforge.financial_source_directory_deferred() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE selected_claim TEXT;
BEGIN
 IF TG_TABLE_NAME='financial_effect_ownership_guards' THEN selected_claim:=NEW.owner_claim_id;
 ELSIF TG_TABLE_NAME='financial_effect_ownership_releases' THEN selected_claim:=NEW.guard_id;
 ELSIF TG_TABLE_NAME='manufacturing_execution_v2_cost_claims' THEN selected_claim:=NEW.id;
 ELSE selected_claim:=NEW.claim_id; END IF;
 PERFORM reconforge.financial_source_claim_close(NEW.tenant_id,selected_claim);RETURN NEW;
END $ownership$;
CREATE CONSTRAINT TRIGGER financial_source_close AFTER INSERT ON reconforge.financial_effect_ownership_guards
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_deferred();
CREATE CONSTRAINT TRIGGER financial_source_close AFTER INSERT ON reconforge.financial_effect_ownership_releases
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_deferred();
CREATE CONSTRAINT TRIGGER financial_source_close AFTER INSERT OR UPDATE ON reconforge.manufacturing_execution_v2_cost_claims
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_deferred();
CREATE CONSTRAINT TRIGGER financial_source_close AFTER INSERT ON reconforge.manufacturing_execution_v2_cost_releases
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_directory_deferred();
CREATE FUNCTION reconforge.refuse_claimed_financial_effect(t TEXT,effect TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
BEGIN
 PERFORM reconforge.touch_financial_effect_claim_gate(t,effect);
 PERFORM reconforge.financial_source_assert(NOT EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_guards g
  WHERE g.tenant_id=t AND g.source_effect_id=effect AND NOT EXISTS(
   SELECT 1 FROM reconforge.financial_effect_ownership_releases r WHERE r.tenant_id=g.tenant_id AND r.guard_id=g.id)),
  'Reverse the complete operating source while its original financial effect is claimed');
END $ownership$;
CREATE FUNCTION reconforge.financial_source_reversal_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ownership$
DECLARE original TEXT;
BEGIN
 IF TG_TABLE_NAME='finance_entries' THEN original:=NEW.reverses_posting_id;
 ELSE original:=NEW.reverses_effect_id; END IF;
 IF original IS NOT NULL THEN PERFORM reconforge.refuse_claimed_financial_effect(NEW.tenant_id,original); END IF;
 RETURN NEW;
END $ownership$;
CREATE TRIGGER financial_source_reversal BEFORE INSERT ON reconforge.finance_entries
 FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_reversal_guard();
CREATE TRIGGER financial_source_reversal BEFORE INSERT ON reconforge.finance_posting_effects
 FOR EACH ROW EXECUTE FUNCTION reconforge.financial_source_reversal_guard();
"""

DOWNGRADE_SQL = r"""
DROP TRIGGER financial_source_reversal ON reconforge.finance_posting_effects;
DROP TRIGGER financial_source_reversal ON reconforge.finance_entries;
DROP TRIGGER financial_source_close ON reconforge.manufacturing_execution_v2_cost_releases;
DROP TRIGGER financial_source_close ON reconforge.manufacturing_execution_v2_cost_claims;
DROP TABLE reconforge.financial_effect_ownership_releases;
DROP TABLE reconforge.financial_effect_ownership_guards;
DROP TABLE reconforge.financial_effect_claim_gates;
DROP FUNCTION reconforge.financial_source_reversal_guard();
DROP FUNCTION reconforge.refuse_claimed_financial_effect(TEXT,TEXT);
DROP FUNCTION reconforge.financial_source_directory_deferred();
DROP FUNCTION reconforge.financial_source_claim_close(TEXT,TEXT);
DROP FUNCTION reconforge.financial_source_directory_guard();
DROP FUNCTION reconforge.touch_financial_effect_claim_gate(TEXT,TEXT);
DROP FUNCTION reconforge.financial_source_projection_guard();
DROP FUNCTION reconforge.financial_source_assert(BOOLEAN,TEXT);
"""
