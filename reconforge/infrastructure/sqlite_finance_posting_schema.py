"""Additive SQLite operational posting records and immutable review provenance."""

SQLITE_FINANCE_POSTING_MIGRATION_SQL = """
ALTER TABLE ledger_entries ADD COLUMN preparer_actor_id TEXT;
ALTER TABLE ledger_entries ADD COLUMN validator_actor_id TEXT;
ALTER TABLE ledger_entries ADD COLUMN validation_digest TEXT
 CHECK(validation_digest IS NULL OR (length(validation_digest)=64 AND validation_digest NOT GLOB '*[^0-9a-f]*'));
ALTER TABLE ledger_entries ADD COLUMN validation_contract_version TEXT;
ALTER TABLE ledger_entries ADD COLUMN reverses_posting_id TEXT
 REFERENCES finance_posting_effects(id) DEFERRABLE INITIALLY DEFERRED;

CREATE UNIQUE INDEX ledger_entry_posting_scope_key
 ON ledger_entries(id,workspace_id,organization_id,legal_entity_id);

CREATE TABLE finance_posting_effects (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 organization_id TEXT NOT NULL REFERENCES organizations(id),
 legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id),
 entry_id TEXT NOT NULL UNIQUE,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('Manual','Reversal')),
 source_id TEXT NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose='operational_posting'),
 reverses_effect_id TEXT UNIQUE REFERENCES finance_posting_effects(id) DEFERRABLE INITIALLY DEFERRED,
 validation_digest TEXT NOT NULL CHECK(length(validation_digest)=64 AND validation_digest NOT GLOB '*[^0-9a-f]*'),
 validation_contract_version TEXT NOT NULL CHECK(validation_contract_version='finance-entry-review-v1'),
 currency_code TEXT NOT NULL,
 currency_precision INTEGER NOT NULL CHECK(currency_precision BETWEEN 0 AND 8),
 currency_rounding_policy TEXT NOT NULL CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 currency_registry_version TEXT NOT NULL,
 currency_registry_digest TEXT NOT NULL REFERENCES currency_registry_snapshots(registry_digest),
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json) AND length(CAST(snapshot_json AS BLOB)) <= 2097152),
 posted_actor_id TEXT NOT NULL,
 posted_at TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
 audit_event_id TEXT NOT NULL REFERENCES audit_events(id) DEFERRABLE INITIALLY DEFERRED,
 outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(workspace_id,source_kind,source_id,purpose),
 FOREIGN KEY(entry_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES ledger_entries(id,workspace_id,organization_id,legal_entity_id),
 CHECK((source_kind='Manual' AND reverses_effect_id IS NULL) OR
       (source_kind='Reversal' AND reverses_effect_id IS NOT NULL))
);
CREATE INDEX finance_posting_effect_scope ON finance_posting_effects(workspace_id,organization_id,legal_entity_id,posted_at,id);

CREATE TABLE finance_posting_commands (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
 operation TEXT NOT NULL CHECK(operation IN ('post','prepare_reversal')),
 actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(length(request_digest)=64 AND request_digest NOT GLOB '*[^0-9a-f]*'),
 result_json TEXT NOT NULL CHECK(json_valid(result_json) AND length(CAST(result_json AS BLOB)) <= 2097152),
 created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,command_id)
);

CREATE TRIGGER finance_posting_effect_update_immutable BEFORE UPDATE ON finance_posting_effects
BEGIN SELECT RAISE(ABORT,'operational posting effects are immutable'); END;
CREATE TRIGGER finance_posting_effect_delete_immutable BEFORE DELETE ON finance_posting_effects
BEGIN SELECT RAISE(ABORT,'operational posting effects are immutable'); END;
CREATE TRIGGER finance_posting_command_update_immutable BEFORE UPDATE ON finance_posting_commands
BEGIN SELECT RAISE(ABORT,'operational posting command receipts are immutable'); END;
CREATE TRIGGER finance_posting_command_delete_immutable BEFORE DELETE ON finance_posting_commands
BEGIN SELECT RAISE(ABORT,'operational posting command receipts are immutable'); END;

CREATE VIEW finance_posting_effect_receipts AS SELECT id,workspace_id,posted_actor_id,
 json_object('id',id,'workspace_id',workspace_id,'organization_id',organization_id,'legal_entity_id',legal_entity_id,
 'entry_id',entry_id,'source_kind',source_kind,'source_id',source_id,'purpose',purpose,'reverses_effect_id',reverses_effect_id,
 'validation_digest',validation_digest,'validation_contract_version',validation_contract_version,
 'currency_code',currency_code,'currency_precision',currency_precision,'currency_rounding_policy',currency_rounding_policy,
 'currency_registry_version',currency_registry_version,'currency_registry_digest',currency_registry_digest,
 'snapshot',json(snapshot_json),'posted_actor_id',posted_actor_id,'posted_at',posted_at,'reason',reason,
 'audit_event_id',audit_event_id,'outbox_event_id',outbox_event_id) AS result_json FROM finance_posting_effects;

CREATE TRIGGER finance_posting_receipt_backing_guard BEFORE INSERT ON finance_posting_commands
WHEN (NEW.operation='post' AND NOT EXISTS(
 SELECT 1 FROM finance_posting_effect_receipts p WHERE p.id=json_extract(NEW.result_json,'$.id')
 AND p.workspace_id=NEW.workspace_id AND p.posted_actor_id=NEW.actor_id
 AND NOT EXISTS(SELECT fullkey,type,atom FROM json_tree(NEW.result_json)
  EXCEPT SELECT fullkey,type,atom FROM json_tree(p.result_json))
 AND NOT EXISTS(SELECT fullkey,type,atom FROM json_tree(p.result_json)
  EXCEPT SELECT fullkey,type,atom FROM json_tree(NEW.result_json))))
 OR (NEW.operation='prepare_reversal' AND NOT EXISTS(
 SELECT 1 FROM ledger_entries e JOIN finance_posting_effects original ON original.id=e.reverses_posting_id
 WHERE e.id=json_extract(NEW.result_json,'$.entry_id') AND e.status='Draft'
 AND e.workspace_id=NEW.workspace_id AND e.preparer_actor_id=NEW.actor_id
 AND original.workspace_id=e.workspace_id AND original.organization_id=e.organization_id AND original.legal_entity_id=e.legal_entity_id
 AND json_extract(NEW.result_json,'$.entry_number') IS e.entry_number
 AND json_extract(NEW.result_json,'$.status') IS 'Draft'
 AND json_extract(NEW.result_json,'$.reverses_posting_id') IS e.reverses_posting_id
 AND json_extract(NEW.result_json,'$.preparer_actor_id') IS e.preparer_actor_id
 AND (SELECT count(*) FROM json_each(NEW.result_json))=5))
BEGIN SELECT RAISE(ABORT,'posting command receipt must match its persisted financial result'); END;

CREATE TRIGGER ledger_posted_header_update_immutable BEFORE UPDATE ON ledger_entries
WHEN EXISTS(SELECT 1 FROM finance_posting_effects WHERE entry_id=OLD.id OR entry_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'operationally posted ledger entries are immutable'); END;
CREATE TRIGGER ledger_posted_header_delete_immutable BEFORE DELETE ON ledger_entries
WHEN OLD.validation_digest IS NOT NULL OR OLD.reverses_posting_id IS NOT NULL
 OR EXISTS(SELECT 1 FROM finance_posting_effects WHERE entry_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'operationally posted ledger entries are immutable'); END;

CREATE TRIGGER finance_posting_effect_entry_guard BEFORE INSERT ON finance_posting_effects
WHEN NOT EXISTS (
 SELECT 1 FROM ledger_entries e WHERE e.id=NEW.entry_id AND e.workspace_id=NEW.workspace_id
 AND e.organization_id=NEW.organization_id AND e.legal_entity_id=NEW.legal_entity_id
 AND e.status='Validated' AND e.preparer_actor_id IS NOT NULL
 AND e.validator_actor_id IS NOT NULL AND e.validator_actor_id<>e.preparer_actor_id
 AND NEW.posted_actor_id<>e.preparer_actor_id AND NEW.validation_digest=e.validation_digest
 AND NEW.validation_contract_version=e.validation_contract_version
 AND NEW.currency_code=e.currency_code AND NEW.currency_precision=e.currency_precision
 AND NEW.currency_rounding_policy=e.currency_rounding_policy
 AND NEW.currency_registry_version=e.currency_registry_version
 AND NEW.currency_registry_digest=e.currency_registry_digest
 AND ((NEW.source_kind='Manual' AND NEW.source_id=e.id AND e.source_type='Manual' AND e.reverses_posting_id IS NULL)
  OR (NEW.source_kind='Reversal' AND NEW.source_id=NEW.reverses_effect_id AND e.source_type='Generated' AND e.reverses_posting_id=NEW.reverses_effect_id))
)
BEGIN SELECT RAISE(ABORT,'operational posting requires independently reviewed entry provenance'); END;

CREATE TRIGGER finance_posting_open_period BEFORE INSERT ON finance_posting_effects
WHEN NOT EXISTS(SELECT 1 FROM ledger_entries e JOIN periods p ON p.id=e.period_id AND p.workspace_id=e.workspace_id
 WHERE e.id=NEW.entry_id AND p.status='Open' AND e.posting_date BETWEEN p.start_date AND p.end_date)
BEGIN SELECT RAISE(ABORT,'operational posting requires an Open fiscal period'); END;

CREATE TRIGGER finance_posting_snapshot_guard BEFORE INSERT ON finance_posting_effects
WHEN json_extract(NEW.snapshot_json,'$.schema_version') IS NOT 'finance-entry-review-v1'
 OR json_type(NEW.snapshot_json) IS NOT 'object'
 OR json_type(NEW.snapshot_json,'$.entry') IS NOT 'object'
 OR json_type(NEW.snapshot_json,'$.lines') IS NOT 'array'
 OR (SELECT count(*) FROM json_each(NEW.snapshot_json)) <> 3
 OR (SELECT count(*) FROM json_each(NEW.snapshot_json,'$.entry')) <> 18
 OR EXISTS(SELECT 1 FROM json_each(NEW.snapshot_json,'$.entry') WHERE key NOT IN
  ('id','workspace_id','organization_id','legal_entity_id','journal_id','period_id','entry_number',
   'posting_date','description','external_reference','source_type','currency_code','currency_precision',
   'currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id'))
 OR NOT EXISTS(SELECT 1 FROM ledger_entries e WHERE e.id=NEW.entry_id
  AND json_extract(NEW.snapshot_json,'$.entry.id') IS e.id
  AND json_extract(NEW.snapshot_json,'$.entry.workspace_id') IS e.workspace_id
  AND json_extract(NEW.snapshot_json,'$.entry.organization_id') IS e.organization_id
  AND json_extract(NEW.snapshot_json,'$.entry.legal_entity_id') IS e.legal_entity_id
  AND json_extract(NEW.snapshot_json,'$.entry.journal_id') IS e.finance_journal_id
  AND json_extract(NEW.snapshot_json,'$.entry.period_id') IS e.period_id
  AND json_extract(NEW.snapshot_json,'$.entry.entry_number') IS e.entry_number
  AND json_extract(NEW.snapshot_json,'$.entry.posting_date') IS e.posting_date
  AND json_extract(NEW.snapshot_json,'$.entry.description') IS e.description
  AND json_extract(NEW.snapshot_json,'$.entry.external_reference') IS e.external_reference
  AND json_extract(NEW.snapshot_json,'$.entry.source_type') IS e.source_type
  AND json_extract(NEW.snapshot_json,'$.entry.currency_code') IS e.currency_code
  AND json_extract(NEW.snapshot_json,'$.entry.currency_precision') IS e.currency_precision
  AND json_extract(NEW.snapshot_json,'$.entry.currency_rounding_policy') IS e.currency_rounding_policy
  AND json_extract(NEW.snapshot_json,'$.entry.currency_registry_version') IS e.currency_registry_version
  AND json_extract(NEW.snapshot_json,'$.entry.currency_registry_digest') IS e.currency_registry_digest
  AND json_extract(NEW.snapshot_json,'$.entry.preparer_actor_id') IS e.preparer_actor_id
  AND json_extract(NEW.snapshot_json,'$.entry.reverses_posting_id') IS e.reverses_posting_id)
 OR json_array_length(NEW.snapshot_json,'$.lines') IS NOT (SELECT count(*) FROM ledger_lines WHERE entry_id=NEW.entry_id)
 OR json_array_length(NEW.snapshot_json,'$.lines') NOT BETWEEN 2 AND 1000
 OR EXISTS(SELECT 1 FROM json_each(NEW.snapshot_json,'$.lines') item
  WHERE (SELECT count(*) FROM json_each(item.value)) <> 6
   OR json_type(item.value,'$.line_number') IS NOT 'integer'
   OR json_type(item.value,'$.debit_minor') IS NOT 'integer'
   OR json_type(item.value,'$.credit_minor') IS NOT 'integer'
   OR json_type(item.value,'$.dimensions') IS NOT 'object'
   OR NOT EXISTS(SELECT 1 FROM ledger_lines l WHERE l.entry_id=NEW.entry_id
    AND l.line_number=json_extract(item.value,'$.line_number')
    AND l.account_id IS json_extract(item.value,'$.account_id')
    AND l.description IS json_extract(item.value,'$.description')
    AND l.debit_minor IS json_extract(item.value,'$.debit_minor')
    AND l.credit_minor IS json_extract(item.value,'$.credit_minor')
    AND (SELECT count(*) FROM ledger_line_dimensions WHERE line_id=l.id)=(SELECT count(*) FROM json_each(item.value,'$.dimensions'))
    AND NOT EXISTS(SELECT 1 FROM json_each(item.value,'$.dimensions') d WHERE NOT EXISTS(
     SELECT 1 FROM ledger_line_dimensions link JOIN accounting_dimension_values v ON v.id=link.dimension_value_id
     WHERE link.line_id=l.id AND v.dimension_id=d.key AND link.dimension_value_id=d.value))))
 OR (SELECT count(DISTINCT json_extract(value,'$.line_number')) FROM json_each(NEW.snapshot_json,'$.lines'))
    <> json_array_length(NEW.snapshot_json,'$.lines')
BEGIN SELECT RAISE(ABORT,'operational posting snapshot does not match retained entry content'); END;

CREATE TRIGGER finance_posting_reversal_affinity BEFORE INSERT ON finance_posting_effects
WHEN NEW.reverses_effect_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM finance_posting_effects original WHERE original.id=NEW.reverses_effect_id
 AND original.reverses_effect_id IS NULL AND original.workspace_id=NEW.workspace_id
 AND original.organization_id=NEW.organization_id AND original.legal_entity_id=NEW.legal_entity_id
 AND original.currency_code=NEW.currency_code AND original.currency_precision=NEW.currency_precision
 AND original.currency_rounding_policy=NEW.currency_rounding_policy
 AND original.currency_registry_version=NEW.currency_registry_version
 AND original.currency_registry_digest=NEW.currency_registry_digest
)
BEGIN SELECT RAISE(ABORT,'full reversal requires original posting scope and monetary policy'); END;

CREATE TRIGGER finance_posting_reversal_exact BEFORE INSERT ON finance_posting_effects
WHEN NEW.reverses_effect_id IS NOT NULL AND (
 (SELECT count(*) FROM ledger_lines WHERE entry_id=NEW.entry_id) <>
 (SELECT count(*) FROM ledger_lines WHERE entry_id=(SELECT entry_id FROM finance_posting_effects WHERE id=NEW.reverses_effect_id))
 OR EXISTS(
  SELECT l.account_id,l.credit_minor,l.debit_minor,
   (SELECT json_group_object(dimension_id,dimension_value_id) FROM
    (SELECT v.dimension_id,d.dimension_value_id FROM ledger_line_dimensions d JOIN accounting_dimension_values v ON v.id=d.dimension_value_id WHERE d.line_id=l.id ORDER BY v.dimension_id)) dimensions,
   count(*) FROM ledger_lines l
   WHERE l.entry_id=(SELECT entry_id FROM finance_posting_effects WHERE id=NEW.reverses_effect_id)
   GROUP BY l.account_id,l.credit_minor,l.debit_minor,dimensions
  EXCEPT
  SELECT l.account_id,l.debit_minor,l.credit_minor,
   (SELECT json_group_object(dimension_id,dimension_value_id) FROM
    (SELECT v.dimension_id,d.dimension_value_id FROM ledger_line_dimensions d JOIN accounting_dimension_values v ON v.id=d.dimension_value_id WHERE d.line_id=l.id ORDER BY v.dimension_id)) dimensions,
   count(*) FROM ledger_lines l WHERE l.entry_id=NEW.entry_id
   GROUP BY l.account_id,l.debit_minor,l.credit_minor,dimensions
 ))
BEGIN SELECT RAISE(ABORT,'full reversal must exactly invert original amounts accounts and dimensions'); END;

CREATE TRIGGER ledger_dimensions_update_draft_only
BEFORE UPDATE ON ledger_line_dimensions
WHEN COALESCE((SELECT entries.status FROM ledger_lines lines
 JOIN ledger_entries entries ON entries.id=lines.entry_id WHERE lines.id=OLD.line_id),'') <> 'Draft'
 OR COALESCE((SELECT entries.status FROM ledger_lines lines
 JOIN ledger_entries entries ON entries.id=lines.entry_id WHERE lines.id=NEW.line_id),'') <> 'Draft'
BEGIN SELECT RAISE(ABORT,'validated ledger dimensions are immutable'); END;

CREATE TRIGGER ledger_lines_update_target_draft_only
BEFORE UPDATE ON ledger_lines
WHEN COALESCE((SELECT status FROM ledger_entries WHERE id=NEW.entry_id),'') <> 'Draft'
BEGIN SELECT RAISE(ABORT,'validated ledger lines are immutable'); END;

CREATE TRIGGER ledger_posting_preparer_immutable BEFORE UPDATE ON ledger_entries
WHEN NEW.preparer_actor_id IS NOT OLD.preparer_actor_id
 OR NEW.reverses_posting_id IS NOT OLD.reverses_posting_id
BEGIN SELECT RAISE(ABORT,'ledger accountable preparer and reversal linkage are immutable'); END;

CREATE TRIGGER ledger_posting_review_immutable BEFORE UPDATE ON ledger_entries
WHEN (NEW.validator_actor_id IS NOT OLD.validator_actor_id
 OR NEW.validation_digest IS NOT OLD.validation_digest
 OR NEW.validation_contract_version IS NOT OLD.validation_contract_version)
 AND NOT (OLD.status='Draft' AND NEW.status='Validated'
  AND OLD.validator_actor_id IS NULL AND OLD.validation_digest IS NULL
  AND OLD.validation_contract_version IS NULL AND NEW.validator_actor_id IS NOT NULL
  AND NEW.validation_digest IS NOT NULL AND NEW.validation_contract_version IS NOT NULL
  AND OLD.preparer_actor_id IS NOT NULL AND NEW.validator_actor_id <> OLD.preparer_actor_id)
BEGIN SELECT RAISE(ABORT,'ledger validation provenance is immutable'); END;

INSERT OR IGNORE INTO permissions(name,description) VALUES
 ('finance_core.post','Post independently reviewed manual Finance Core entries.'),
 ('finance_core.reverse','Prepare and post a linked full operational reversal.');
INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
 SELECT roles.id,permissions.name FROM roles JOIN permissions
 WHERE roles.name='admin' AND permissions.name IN ('finance_core.post','finance_core.reverse');
"""
