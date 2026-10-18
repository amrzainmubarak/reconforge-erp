"""Explicit immutable operational postings with forward-only human review provenance."""
from alembic import op

revision = "0098_pg_finance_posting"
down_revision = "0097_pg_reconciliation_seal"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
ALTER TABLE reconforge.finance_entries ADD COLUMN IF NOT EXISTS preparer_actor_id TEXT;
ALTER TABLE reconforge.finance_entries ADD COLUMN IF NOT EXISTS validator_actor_id TEXT;
ALTER TABLE reconforge.finance_entries ADD COLUMN IF NOT EXISTS validation_digest TEXT CHECK(validation_digest ~ '^[0-9a-f]{64}$');
ALTER TABLE reconforge.finance_entries ADD COLUMN IF NOT EXISTS validation_contract_version TEXT;
ALTER TABLE reconforge.finance_entries ADD COLUMN IF NOT EXISTS reverses_posting_id TEXT;
CREATE TABLE IF NOT EXISTS reconforge.finance_posting_effects (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 organization_id TEXT NOT NULL, legal_entity_id TEXT NOT NULL, entry_id TEXT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('Manual','Reversal')),
 source_id TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose='operational_posting'),
 reverses_effect_id TEXT, validation_digest TEXT NOT NULL CHECK(validation_digest ~ '^[0-9a-f]{64}$'),
 validation_contract_version TEXT NOT NULL CHECK(validation_contract_version='finance-entry-review-v1'),
 currency_code TEXT NOT NULL, currency_precision INTEGER NOT NULL CHECK(currency_precision BETWEEN 0 AND 8),
 currency_rounding_policy TEXT NOT NULL CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 currency_registry_version TEXT NOT NULL, currency_registry_digest TEXT NOT NULL,
 snapshot_json JSONB NOT NULL CHECK(octet_length(snapshot_json::text)<=2097152),
 posted_actor_id TEXT NOT NULL, posted_at TEXT NOT NULL, reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
 audit_event_id TEXT NOT NULL, outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,entry_id),
 UNIQUE(tenant_id,workspace_id,source_kind,source_id,purpose), UNIQUE(tenant_id,reverses_effect_id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,reverses_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id),
 CHECK((source_kind='Manual' AND reverses_effect_id IS NULL) OR (source_kind='Reversal' AND reverses_effect_id IS NOT NULL))
);
DO $posting$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='finance_entry_reversal_posting_fk' AND conrelid='reconforge.finance_entries'::regclass) THEN
 ALTER TABLE reconforge.finance_entries ADD CONSTRAINT finance_entry_reversal_posting_fk
 FOREIGN KEY(tenant_id,reverses_posting_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
 END IF;
END $posting$;
CREATE TABLE IF NOT EXISTS reconforge.finance_posting_commands (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, organization_id TEXT NOT NULL, legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
 operation TEXT NOT NULL CHECK(operation IN ('post','prepare_reversal')), actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 result_json JSONB NOT NULL CHECK(octet_length(result_json::text)<=2097152), created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id)
);
ALTER TABLE reconforge.finance_posting_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_posting_effects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS posting_scope ON reconforge.finance_posting_effects;
CREATE POLICY posting_scope ON reconforge.finance_posting_effects USING (
 tenant_id=current_setting('app.tenant_id',true) AND EXISTS (
 SELECT 1 FROM reconforge.finance_entries e JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id
 AND o.organization_code=e.organization_code AND o.application_workspace_id=e.workspace_id
 JOIN reconforge.legal_entities le ON le.tenant_id=o.tenant_id AND le.organization_id=o.id AND le.entity_code=e.entity_code
 WHERE e.tenant_id=finance_posting_effects.tenant_id AND e.id=finance_posting_effects.entry_id
 AND e.workspace_id=finance_posting_effects.workspace_id AND o.id=finance_posting_effects.organization_id AND le.id=finance_posting_effects.legal_entity_id));
ALTER TABLE reconforge.finance_posting_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_posting_commands FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS posting_scope ON reconforge.finance_posting_commands;
CREATE POLICY posting_scope ON reconforge.finance_posting_commands USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND NULLIF(current_setting('app.entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.legal_entity_id',true),'')
 AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
 AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true))
 AND EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities le ON le.tenant_id=o.tenant_id AND le.organization_id=o.id
 WHERE o.tenant_id=finance_posting_commands.tenant_id AND o.id=finance_posting_commands.organization_id
 AND o.application_workspace_id=finance_posting_commands.workspace_id AND le.id=finance_posting_commands.legal_entity_id));

CREATE OR REPLACE FUNCTION reconforge.guard_posting_record_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $posting$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational posting records are immutable.'; END $posting$;
DROP TRIGGER IF EXISTS posting_immutable ON reconforge.finance_posting_effects;
CREATE TRIGGER posting_immutable BEFORE UPDATE OR DELETE ON reconforge.finance_posting_effects FOR EACH ROW EXECUTE FUNCTION reconforge.guard_posting_record_immutable();
DROP TRIGGER IF EXISTS posting_immutable ON reconforge.finance_posting_commands;
CREATE TRIGGER posting_immutable BEFORE UPDATE OR DELETE ON reconforge.finance_posting_commands FOR EACH ROW EXECUTE FUNCTION reconforge.guard_posting_record_immutable();

CREATE OR REPLACE FUNCTION reconforge.guard_finance_posted_header() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $posting$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_posting_effects p WHERE p.tenant_id=OLD.tenant_id AND p.entry_id=OLD.id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operationally posted entries are immutable.';
 END IF;
 IF TG_OP='DELETE' THEN
  IF OLD.validation_digest IS NOT NULL OR OLD.reverses_posting_id IS NOT NULL THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reviewed entries and linked reversal drafts retain immutable history.';
  END IF;
  RETURN OLD;
 END IF;
 IF (OLD.preparer_actor_id,OLD.reverses_posting_id) IS DISTINCT FROM (NEW.preparer_actor_id,NEW.reverses_posting_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Preparation identity and reversal linkage are immutable.';
 END IF;
 IF OLD.validation_digest IS NOT NULL AND
  (to_jsonb(OLD)-ARRAY['status','voided_by','voided_at','void_reason','updated_at']) IS DISTINCT FROM
  (to_jsonb(NEW)-ARRAY['status','voided_by','voided_at','void_reason','updated_at']) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Independently reviewed content is immutable.';
 END IF;
 IF OLD.validation_digest IS NULL AND NEW.validation_digest IS NOT NULL AND
  (OLD.status<>'Draft' OR NEW.status<>'Validated' OR NEW.preparer_actor_id IS NULL OR NEW.validator_actor_id IS NULL
   OR NEW.preparer_actor_id=NEW.validator_actor_id OR NEW.validation_contract_version<>'finance-entry-review-v1') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Review seal requires an independent authenticated validation.';
 END IF;
 RETURN NEW;
END $posting$;
DROP TRIGGER IF EXISTS finance_posted_header ON reconforge.finance_entries;
CREATE TRIGGER finance_posted_header BEFORE UPDATE OR DELETE ON reconforge.finance_entries FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_posted_header();

CREATE OR REPLACE FUNCTION reconforge.guard_finance_reviewed_child() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $posting$
DECLARE old_entry TEXT; new_entry TEXT; parent RECORD; selected_tenant TEXT;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Financial child tenant identity is immutable.';
  END IF;
 END IF;
 IF TG_OP<>'INSERT' THEN
  selected_tenant:=OLD.tenant_id;
  IF TG_TABLE_NAME='finance_entry_lines' THEN old_entry:=OLD.entry_id;
  ELSE SELECT entry_id INTO old_entry FROM reconforge.finance_entry_lines WHERE tenant_id=OLD.tenant_id AND id=OLD.entry_line_id; END IF;
 END IF;
 IF TG_OP<>'DELETE' THEN
  selected_tenant:=NEW.tenant_id;
  IF TG_TABLE_NAME='finance_entry_lines' THEN new_entry:=NEW.entry_id;
  ELSE SELECT entry_id INTO new_entry FROM reconforge.finance_entry_lines WHERE tenant_id=NEW.tenant_id AND id=NEW.entry_line_id; END IF;
 END IF;
 FOR parent IN SELECT id,validation_digest FROM reconforge.finance_entries WHERE tenant_id=selected_tenant AND (id=old_entry OR id=new_entry) ORDER BY id FOR UPDATE LOOP
  IF parent.validation_digest IS NOT NULL OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects p WHERE p.tenant_id=selected_tenant AND p.entry_id=parent.id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reviewed and posted financial content is immutable.';
  END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $posting$;
DROP TRIGGER IF EXISTS finance_reviewed_child ON reconforge.finance_entry_lines;
CREATE TRIGGER finance_reviewed_child BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_entry_lines FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_reviewed_child();
DROP TRIGGER IF EXISTS finance_reviewed_child ON reconforge.finance_entry_line_dimensions;
CREATE TRIGGER finance_reviewed_child BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_entry_line_dimensions FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_reviewed_child();

CREATE OR REPLACE FUNCTION reconforge.guard_finance_posting_effect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $posting$
DECLARE entry RECORD; period RECORD; original RECORD; debit NUMERIC; credit NUMERIC; line_count BIGINT; stored_header JSONB; stored_lines JSONB;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Posting requires READ COMMITTED.'; END IF;
 SELECT p.* INTO period FROM reconforge.fiscal_periods p JOIN reconforge.finance_entries e ON e.tenant_id=p.tenant_id AND e.period_id=p.id
 WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.entry_id FOR SHARE OF p;
 SELECT * INTO entry FROM reconforge.finance_entries WHERE tenant_id=NEW.tenant_id AND id=NEW.entry_id FOR UPDATE;
 IF entry IS NULL OR period IS NULL OR period.status<>'Open' OR entry.status<>'Validated'
 OR entry.period_id<>period.id OR entry.workspace_id<>period.application_workspace_id
 OR entry.posting_date::date<period.start_date OR entry.posting_date::date>period.end_date
 OR entry.preparer_actor_id IS NULL OR entry.validator_actor_id IS NULL OR entry.validation_digest IS NULL
 OR entry.preparer_actor_id=entry.validator_actor_id OR NEW.posted_actor_id=entry.preparer_actor_id
 OR NEW.validation_digest IS DISTINCT FROM entry.validation_digest
 OR NEW.validation_contract_version IS DISTINCT FROM entry.validation_contract_version
 OR (NEW.currency_code,NEW.currency_precision,NEW.currency_rounding_policy,NEW.currency_registry_version,NEW.currency_registry_digest)
 IS DISTINCT FROM (entry.currency_code,entry.currency_precision,entry.currency_rounding_policy,entry.currency_registry_version,entry.currency_registry_digest)
 OR NEW.reverses_effect_id IS DISTINCT FROM entry.reverses_posting_id
 OR (NEW.source_kind='Manual' AND (entry.source_type<>'Manual' OR NEW.source_id<>entry.id))
 OR (NEW.source_kind='Reversal' AND (entry.source_type<>'Generated' OR NEW.source_id<>entry.reverses_posting_id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Posting requires independently reviewed provenance and an open period.';
 END IF;
 SELECT count(*),sum(debit_minor),sum(credit_minor) INTO line_count,debit,credit FROM reconforge.finance_entry_lines WHERE tenant_id=NEW.tenant_id AND entry_id=NEW.entry_id;
 IF line_count<2 OR line_count>1000 OR debit IS NULL OR debit<=0 OR debit>9223372036854775807 OR debit<>credit OR debit<>entry.total_debit_minor OR credit<>entry.total_credit_minor THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Posting requires exactly balanced stored minor units.';
 END IF;
 SELECT jsonb_object_agg(key,value) INTO stored_header FROM jsonb_each(to_jsonb(entry))
 WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
 'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 stored_header:=stored_header||jsonb_build_object('organization_id',NEW.organization_id,'legal_entity_id',NEW.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',l.line_number,'account_id',l.account_id,'description',l.description,
  'debit_minor',l.debit_minor,'credit_minor',l.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id)
   FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=l.tenant_id AND d.entry_line_id=l.id),'{}'::jsonb)) ORDER BY l.line_number)
 INTO stored_lines FROM reconforge.finance_entry_lines l WHERE l.tenant_id=NEW.tenant_id AND l.entry_id=NEW.entry_id;
 IF NEW.snapshot_json IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',stored_header,'lines',stored_lines) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Posting evidence must match exact stored financial content.';
 END IF;
 IF NEW.reverses_effect_id IS NOT NULL THEN
  SELECT * INTO original FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=NEW.reverses_effect_id;
  IF original IS NULL OR original.reverses_effect_id IS NOT NULL OR
   (original.workspace_id,original.organization_id,original.legal_entity_id,original.currency_code,original.currency_registry_digest)
   IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.currency_code,NEW.currency_registry_digest) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reversal must reference its original posting scope and policy.';
  END IF;
  IF original.snapshot_json->'entry'->>'journal_id' IS DISTINCT FROM entry.journal_id OR EXISTS(
   (SELECT value->>'account_id',value->'credit_minor',value->'debit_minor',value->'dimensions' FROM jsonb_array_elements(original.snapshot_json->'lines')
    EXCEPT ALL SELECT value->>'account_id',value->'debit_minor',value->'credit_minor',value->'dimensions' FROM jsonb_array_elements(stored_lines))
   UNION ALL
   (SELECT value->>'account_id',value->'debit_minor',value->'credit_minor',value->'dimensions' FROM jsonb_array_elements(stored_lines)
    EXCEPT ALL SELECT value->>'account_id',value->'credit_minor',value->'debit_minor',value->'dimensions' FROM jsonb_array_elements(original.snapshot_json->'lines'))
  ) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reversal must exactly invert original accounts, amounts and dimensions.'; END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id
  WHERE a.tenant_id=NEW.tenant_id AND a.id=NEW.audit_event_id AND o.event_id=NEW.outbox_event_id
  AND a.actor_user_id=NEW.posted_actor_id AND a.object_type='finance_posting' AND a.object_id=NEW.id
  AND a.action='finance_entry_posted'
  AND a.metadata_json=jsonb_build_object('entry_id',NEW.entry_id,'content_digest',NEW.validation_digest)
  AND o.event_type='finance_entry_posted' AND o.aggregate_type='finance_posting' AND o.aggregate_id=NEW.id
  AND o.payload=jsonb_build_object('entry_id',NEW.entry_id,'content_digest',NEW.validation_digest,'audit_event_id',NEW.audit_event_id)
  AND (o.workspace_id,o.organization_id,o.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Posting requires exact audit and outbox evidence binding.';
 END IF;
 RETURN NEW;
END $posting$;
DROP TRIGGER IF EXISTS finance_posting_effect_guard ON reconforge.finance_posting_effects;
CREATE TRIGGER finance_posting_effect_guard BEFORE INSERT ON reconforge.finance_posting_effects FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_posting_effect();

CREATE OR REPLACE FUNCTION reconforge.guard_finance_posting_command() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $posting$
DECLARE effect RECORD; entry RECORD; expected JSONB;
BEGIN
 IF NEW.operation='post' THEN
  SELECT * INTO effect FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=NEW.result_json->>'id';
  IF effect IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Command receipt requires a committed posting effect.'; END IF;
  expected:=(to_jsonb(effect)-ARRAY['tenant_id','snapshot_json'])||jsonb_build_object('snapshot',effect.snapshot_json);
  IF (effect.workspace_id,effect.organization_id,effect.legal_entity_id,effect.posted_actor_id)
   IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.actor_id) OR NEW.result_json IS DISTINCT FROM expected THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Command receipt must retain its exact committed posting effect.';
  END IF;
 ELSE
  SELECT e.*,o.id AS organization_id,le.id AS legal_entity_id INTO entry FROM reconforge.finance_entries e
   JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.organization_code=e.organization_code AND o.application_workspace_id=e.workspace_id
   JOIN reconforge.legal_entities le ON le.tenant_id=o.tenant_id AND le.organization_id=o.id AND le.entity_code=e.entity_code
   WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.result_json->>'entry_id' FOR UPDATE OF e;
  IF entry IS NULL OR entry.status<>'Draft' OR entry.source_type<>'Generated' OR entry.reverses_posting_id IS NULL OR
   (entry.workspace_id,entry.organization_id,entry.legal_entity_id,entry.preparer_actor_id)
   IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.actor_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Command receipt requires its linked reversal draft.';
  END IF;
  expected:=jsonb_build_object('entry_id',entry.id,'entry_number',entry.entry_number,'status','Draft','reverses_posting_id',entry.reverses_posting_id,'preparer_actor_id',entry.preparer_actor_id);
  IF NEW.result_json IS DISTINCT FROM expected THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Command receipt must retain its exact linked reversal draft.'; END IF;
 END IF;
 RETURN NEW;
END $posting$;
DROP TRIGGER IF EXISTS finance_posting_command_guard ON reconforge.finance_posting_commands;
CREATE TRIGGER finance_posting_command_guard BEFORE INSERT ON reconforge.finance_posting_commands FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_posting_command();
"""

DOWNGRADE_SQL = r"""
DO $posting$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_posting_effects) OR EXISTS(SELECT 1 FROM reconforge.finance_posting_commands)
 OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE preparer_actor_id IS NOT NULL OR validator_actor_id IS NOT NULL
  OR validation_digest IS NOT NULL OR validation_contract_version IS NOT NULL OR reverses_posting_id IS NOT NULL) THEN
  RAISE EXCEPTION 'Refusing to discard operational posting effects or authenticated review provenance.';
 END IF;
END $posting$;
DROP TRIGGER IF EXISTS finance_posting_effect_guard ON reconforge.finance_posting_effects;
DROP TRIGGER IF EXISTS finance_reviewed_child ON reconforge.finance_entry_line_dimensions;
DROP TRIGGER IF EXISTS finance_posting_command_guard ON reconforge.finance_posting_commands;
DROP TRIGGER IF EXISTS finance_reviewed_child ON reconforge.finance_entry_lines;
DROP TRIGGER IF EXISTS finance_posted_header ON reconforge.finance_entries;
DROP FUNCTION IF EXISTS reconforge.guard_finance_posting_effect();
DROP FUNCTION IF EXISTS reconforge.guard_finance_posting_command();
DROP FUNCTION IF EXISTS reconforge.guard_finance_reviewed_child();
DROP FUNCTION IF EXISTS reconforge.guard_finance_posted_header();
ALTER TABLE reconforge.finance_entries DROP CONSTRAINT IF EXISTS finance_entry_reversal_posting_fk;
DROP TABLE reconforge.finance_posting_commands;
DROP TABLE reconforge.finance_posting_effects;
DROP FUNCTION IF EXISTS reconforge.guard_posting_record_immutable();
ALTER TABLE reconforge.finance_entries DROP COLUMN reverses_posting_id, DROP COLUMN validation_contract_version,
 DROP COLUMN validation_digest, DROP COLUMN validator_actor_id, DROP COLUMN preparer_actor_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
