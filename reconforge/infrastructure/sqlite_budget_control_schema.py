"""SQLite migration 52: bounded operational budgets and immutable commitments."""

BUDGET_RESTORE_ADMISSION_TRIGGERS = (
    "budget_envelope_insert_guard",
    "budget_event_insert_guard",
    "budget_event_apply",
)

SQLITE_BUDGET_CONTROL_SCHEMA_SQL = r"""
CREATE TABLE budget_envelopes (
 id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),organization_id TEXT NOT NULL REFERENCES organizations(id),
 legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id),period_id TEXT NOT NULL REFERENCES periods(id),
 budget_code TEXT NOT NULL,name TEXT NOT NULL,currency_code TEXT NOT NULL REFERENCES currencies(code),
 limit_minor INTEGER NOT NULL CHECK(typeof(limit_minor)='integer' AND limit_minor BETWEEN 1 AND 9000000000000000000),
 reserved_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(reserved_minor)='integer' AND reserved_minor>=0),
 consumed_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(consumed_minor)='integer' AND consumed_minor>=0),
 currency_precision INTEGER NOT NULL,currency_rounding_policy TEXT NOT NULL,currency_registry_version TEXT NOT NULL,
 currency_registry_digest TEXT NOT NULL REFERENCES currency_registry_snapshots(registry_digest),
 status TEXT NOT NULL CHECK(status IN('Draft','Submitted','Approved')),created_by TEXT NOT NULL REFERENCES users(id),
 submitted_by TEXT REFERENCES users(id),approved_by TEXT REFERENCES users(id),reason TEXT NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,row_version INTEGER NOT NULL CHECK(row_version>0),
 UNIQUE(workspace_id,organization_id,legal_entity_id,budget_code),CHECK(reserved_minor<=limit_minor-consumed_minor)
);
CREATE TABLE budget_commitment_events (
 id TEXT PRIMARY KEY,budget_id TEXT NOT NULL REFERENCES budget_envelopes(id),commitment_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('Reserve','Release','Consume')),amount_minor INTEGER NOT NULL
 CHECK(typeof(amount_minor)='integer' AND amount_minor BETWEEN 1 AND 9000000000000000000),
 remaining_minor INTEGER NOT NULL CHECK(typeof(remaining_minor)='integer' AND remaining_minor>=0),
 operation_date TEXT NOT NULL,source_reference TEXT NOT NULL,reason TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,budget_version INTEGER NOT NULL,
 audit_event_id TEXT NOT NULL REFERENCES audit_events(id),outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id),
 request_digest TEXT NOT NULL,UNIQUE(budget_id,budget_version)
);
CREATE UNIQUE INDEX budget_reservation_identity ON budget_commitment_events(budget_id,commitment_id) WHERE operation='Reserve';
CREATE UNIQUE INDEX budget_reservation_source ON budget_commitment_events(budget_id,source_reference) WHERE operation='Reserve';
CREATE INDEX budget_events_commitment ON budget_commitment_events(budget_id,commitment_id,budget_version DESC);
CREATE INDEX budget_envelopes_scope ON budget_envelopes(workspace_id,organization_id,legal_entity_id,created_at,id);
CREATE TABLE budget_commands (
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL,request_digest TEXT NOT NULL,budget_id TEXT NOT NULL REFERENCES budget_envelopes(id),
 actor_id TEXT NOT NULL REFERENCES users(id),request_json TEXT NOT NULL CHECK(json_valid(request_json)),
 result_json TEXT NOT NULL CHECK(json_valid(result_json)),result_digest TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(workspace_id,command_id)
);
CREATE TRIGGER budget_envelope_insert_guard BEFORE INSERT ON budget_envelopes BEGIN
 SELECT CASE WHEN NEW.status<>'Draft' OR NEW.row_version<>1 OR NEW.reserved_minor<>0 OR NEW.consumed_minor<>0
 OR NEW.submitted_by IS NOT NULL OR NEW.approved_by IS NOT NULL THEN RAISE(ABORT,'Budget must begin as an empty Draft.') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations o JOIN legal_entities e ON e.organization_id=o.id
  WHERE o.id=NEW.organization_id AND o.workspace_id=NEW.workspace_id AND e.id=NEW.legal_entity_id AND o.active=1 AND e.active=1)
 OR NOT EXISTS(SELECT 1 FROM periods p WHERE p.id=NEW.period_id AND p.workspace_id=NEW.workspace_id AND p.status='Open')
 THEN RAISE(ABORT,'Budget canonical scope or open period is invalid.') END;
END;
CREATE TRIGGER budget_envelope_update_guard BEFORE UPDATE ON budget_envelopes BEGIN
 SELECT CASE WHEN (NEW.id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.budget_code,NEW.name,
  NEW.currency_code,NEW.limit_minor,NEW.currency_precision,NEW.currency_rounding_policy,NEW.currency_registry_version,
  NEW.currency_registry_digest,NEW.created_by,NEW.created_at) IS NOT
 (OLD.id,OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.budget_code,OLD.name,
  OLD.currency_code,OLD.limit_minor,OLD.currency_precision,OLD.currency_rounding_policy,OLD.currency_registry_version,
  OLD.currency_registry_digest,OLD.created_by,OLD.created_at) OR NEW.row_version<>OLD.row_version+1
 THEN RAISE(ABORT,'Budget definition and exact policy are immutable.') END;
 SELECT CASE WHEN NOT (
  (OLD.status='Draft' AND NEW.status='Submitted' AND NEW.submitted_by IS NOT NULL AND NEW.approved_by IS NULL
   AND NEW.reserved_minor=OLD.reserved_minor AND NEW.consumed_minor=OLD.consumed_minor AND length(NEW.reason)>0)
  OR (OLD.status='Submitted' AND NEW.status='Approved' AND NEW.submitted_by=OLD.submitted_by AND NEW.approved_by IS NOT NULL
   AND NEW.approved_by<>OLD.created_by AND NEW.approved_by<>OLD.submitted_by
   AND NEW.reserved_minor=OLD.reserved_minor AND NEW.consumed_minor=OLD.consumed_minor AND length(NEW.reason)>0)
  OR (OLD.status='Approved' AND NEW.status=OLD.status AND NEW.submitted_by=OLD.submitted_by AND NEW.approved_by=OLD.approved_by
   AND NEW.reason=OLD.reason AND EXISTS(SELECT 1 FROM budget_commitment_events e WHERE e.budget_id=OLD.id
    AND e.budget_version=NEW.row_version AND NEW.reserved_minor=OLD.reserved_minor+
     CASE WHEN e.operation='Reserve' THEN e.amount_minor ELSE -e.amount_minor END
    AND NEW.consumed_minor=OLD.consumed_minor+CASE WHEN e.operation='Consume' THEN e.amount_minor ELSE 0 END))
 ) THEN RAISE(ABORT,'Budget transition or conserved ledger update is invalid.') END;
END;
CREATE TRIGGER budget_envelope_delete_guard BEFORE DELETE ON budget_envelopes BEGIN SELECT RAISE(ABORT,'Budget evidence is immutable.'); END;
CREATE TRIGGER budget_event_insert_guard BEFORE INSERT ON budget_commitment_events BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM budget_envelopes b JOIN periods p ON p.id=b.period_id
  WHERE b.id=NEW.budget_id AND b.status='Approved' AND b.row_version+1=NEW.budget_version AND p.status='Open'
  AND NEW.operation_date BETWEEN p.start_date AND p.end_date
  AND ((NEW.operation='Reserve' AND NEW.amount_minor<=b.limit_minor-b.reserved_minor-b.consumed_minor
    AND NEW.remaining_minor=NEW.amount_minor AND NOT EXISTS(SELECT 1 FROM budget_commitment_events r
      WHERE r.budget_id=b.id AND r.commitment_id=NEW.commitment_id))
   OR (NEW.operation IN('Release','Consume') AND NEW.amount_minor<=COALESCE((SELECT e.remaining_minor
      FROM budget_commitment_events e WHERE e.budget_id=b.id AND e.commitment_id=NEW.commitment_id ORDER BY e.budget_version DESC LIMIT 1),-1)
    AND NEW.remaining_minor=(SELECT e.remaining_minor-NEW.amount_minor FROM budget_commitment_events e
      WHERE e.budget_id=b.id AND e.commitment_id=NEW.commitment_id ORDER BY e.budget_version DESC LIMIT 1)
    AND NEW.source_reference=(SELECT e.source_reference FROM budget_commitment_events e
      WHERE e.budget_id=b.id AND e.commitment_id=NEW.commitment_id AND e.operation='Reserve'))))
 THEN RAISE(ABORT,'Commitment capacity, sequence, period or balance is invalid.') END;
END;
CREATE TRIGGER budget_event_apply AFTER INSERT ON budget_commitment_events BEGIN
 UPDATE budget_envelopes SET reserved_minor=reserved_minor+CASE WHEN NEW.operation='Reserve' THEN NEW.amount_minor ELSE -NEW.amount_minor END,
 consumed_minor=consumed_minor+CASE WHEN NEW.operation='Consume' THEN NEW.amount_minor ELSE 0 END,
 row_version=NEW.budget_version,updated_at=NEW.created_at WHERE id=NEW.budget_id;
END;
CREATE TRIGGER budget_event_update_guard BEFORE UPDATE ON budget_commitment_events BEGIN SELECT RAISE(ABORT,'Commitment evidence is immutable.'); END;
CREATE TRIGGER budget_event_delete_guard BEFORE DELETE ON budget_commitment_events BEGIN SELECT RAISE(ABORT,'Commitment evidence is immutable.'); END;
CREATE TRIGGER budget_command_update_guard BEFORE UPDATE ON budget_commands BEGIN SELECT RAISE(ABORT,'Budget command evidence is immutable.'); END;
CREATE TRIGGER budget_command_delete_guard BEFORE DELETE ON budget_commands BEGIN SELECT RAISE(ABORT,'Budget command evidence is immutable.'); END;
INSERT OR IGNORE INTO permissions (name, description) VALUES
 ('budget_control.read', 'Read governed local budget envelopes and retained commitment evidence.'),
 ('budget_control.manage', 'Create, submit, reserve, release, or consume governed local budget commitments.'),
 ('budget_control.approve', 'Independently approve submitted governed local budget envelopes.');
INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles CROSS JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('budget_control.read', 'budget_control.manage', 'budget_control.approve');
"""
