"""SQLite schema for the first enterprise backbone slice."""

from __future__ import annotations

INITIAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    local_first_note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legal_entities (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity_code TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, entity_code)
);

CREATE TABLE IF NOT EXISTS periods (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, name)
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT,
    disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS permissions (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, account_code)
);

CREATE TABLE IF NOT EXISTS reconciliations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    period_id TEXT NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
    account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
    reconciliation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    period_id TEXT REFERENCES periods(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controls (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    control_code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, control_code)
);

CREATE TABLE IF NOT EXISTS evidence_objects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    provenance_type TEXT NOT NULL,
    redaction_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_objects (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (object_type, object_id)
);

CREATE TABLE IF NOT EXISTS workflow_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    required_permission TEXT,
    sod_rule TEXT,
    UNIQUE (object_type, from_status, to_status)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL UNIQUE CHECK (sequence > 0),
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    actor_user_id TEXT,
    actor_label TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_hash TEXT,
    after_hash TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_ledger_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0),
    last_event_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO audit_ledger_state (id, last_sequence, last_event_hash, updated_at)
VALUES (1, 0, '0000000000000000000000000000000000000000000000000000000000000000', '1970-01-01T00:00:00Z');

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE INDEX IF NOT EXISTS idx_periods_workspace ON periods(workspace_id);
CREATE INDEX IF NOT EXISTS idx_reconciliations_workspace_period ON reconciliations(workspace_id, period_id);
CREATE INDEX IF NOT EXISTS idx_evidence_workspace ON evidence_objects(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_object ON audit_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);
"""

AUTH_RBAC_SCHEMA_SQL = """
ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN password_salt TEXT;
ALTER TABLE users ADD COLUMN password_iterations INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN password_algorithm TEXT NOT NULL DEFAULT 'pbkdf2_sha256';
ALTER TABLE users ADD COLUMN password_changed_at TEXT;
ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN locked_until TEXT;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_name TEXT NOT NULL REFERENCES permissions(name) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_name)
);

INSERT OR IGNORE INTO roles (id, name) VALUES
    ('ROLE-admin', 'admin'),
    ('ROLE-controller', 'controller'),
    ('ROLE-preparer', 'preparer'),
    ('ROLE-reviewer', 'reviewer'),
    ('ROLE-auditor-readonly', 'auditor-readonly');

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('users.manage', 'Manage local users.'),
    ('roles.manage', 'Manage local roles and assignments.'),
    ('db.read', 'Read local database metadata.'),
    ('audit.read', 'Read local audit events.'),
    ('audit.verify', 'Verify local audit event checksums.'),
    ('reconciliation.prepare', 'Prepare local reconciliation workflow objects.'),
    ('reconciliation.review', 'Review local reconciliation workflow objects.'),
    ('reconciliation.approve', 'Approve local reconciliation workflow objects.'),
    ('controls.test', 'Run or update local control testing workflow objects.'),
    ('evidence.read', 'Read local evidence references.'),
    ('reports.read', 'Read local report outputs.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'admin';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'db.read' AS permission_name
    UNION ALL SELECT 'audit.read'
    UNION ALL SELECT 'audit.verify'
    UNION ALL SELECT 'reconciliation.prepare'
    UNION ALL SELECT 'reconciliation.review'
    UNION ALL SELECT 'reconciliation.approve'
    UNION ALL SELECT 'controls.test'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'reports.read'
) permissions
WHERE roles.name = 'controller';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'db.read' AS permission_name
    UNION ALL SELECT 'reconciliation.prepare'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'reports.read'
) permissions
WHERE roles.name = 'preparer';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'db.read' AS permission_name
    UNION ALL SELECT 'audit.read'
    UNION ALL SELECT 'reconciliation.review'
    UNION ALL SELECT 'reconciliation.approve'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'reports.read'
) permissions
WHERE roles.name = 'reviewer';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'db.read' AS permission_name
    UNION ALL SELECT 'audit.read'
    UNION ALL SELECT 'audit.verify'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'reports.read'
) permissions
WHERE roles.name = 'auditor-readonly';

CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission ON role_permissions(permission_name);
"""

WORKFLOW_STATE_MACHINE_SCHEMA_SQL = """
ALTER TABLE workflow_objects ADD COLUMN id TEXT;
ALTER TABLE workflow_objects ADD COLUMN created_at TEXT;

UPDATE workflow_objects
SET id = 'WF-' || lower(hex(randomblob(6)))
WHERE id IS NULL;

UPDATE workflow_objects
SET created_at = COALESCE(created_at, updated_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
WHERE created_at IS NULL;

ALTER TABLE workflow_transitions ADD COLUMN reason_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workflow_transitions ADD COLUMN active INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS workflow_transition_events (
    id TEXT PRIMARY KEY,
    workflow_object_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    actor_label TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_objects_id ON workflow_objects(id);
CREATE INDEX IF NOT EXISTS idx_workflow_objects_type_object ON workflow_objects(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_workflow_transition_events_object ON workflow_transition_events(workflow_object_id);
CREATE INDEX IF NOT EXISTS idx_workflow_transition_events_actor ON workflow_transition_events(actor_user_id);

INSERT OR IGNORE INTO workflow_transitions (
    object_type, from_status, to_status, required_permission, sod_rule, reason_required, active
)
VALUES
    ('generic_review', 'Draft', 'Prepared', NULL, 'prepare_review', 0, 1),
    ('generic_review', 'Prepared', 'In Review', NULL, 'submit_approve', 0, 1),
    ('generic_review', 'In Review', 'Reviewed', NULL, 'prepare_review', 0, 1),
    ('generic_review', 'In Review', 'Needs Follow-up', NULL, NULL, 1, 1),
    ('generic_review', 'Reviewed', 'Complete', NULL, 'submit_approve', 0, 1),
    ('generic_review', 'Reviewed', 'Accepted Risk', NULL, NULL, 1, 1),
    ('generic_review', 'Needs Follow-up', 'Reopened', NULL, NULL, 1, 1),
    ('generic_review', 'Reopened', 'Prepared', NULL, 'prepare_review', 0, 1),
    ('generic_review', 'Draft', 'Not Applicable', NULL, NULL, 1, 1),

    ('reconciliation', 'Draft', 'Prepared', 'reconciliation.prepare', 'prepare_review', 0, 1),
    ('reconciliation', 'Prepared', 'In Review', 'reconciliation.prepare', 'submit_approve', 0, 1),
    ('reconciliation', 'In Review', 'Reviewed', 'reconciliation.review', 'prepare_review', 0, 1),
    ('reconciliation', 'In Review', 'Needs Follow-up', 'reconciliation.review', NULL, 1, 1),
    ('reconciliation', 'Reviewed', 'Complete', 'reconciliation.approve', 'submit_approve', 0, 1),
    ('reconciliation', 'Reviewed', 'Accepted Risk', 'reconciliation.approve', NULL, 1, 1),
    ('reconciliation', 'Needs Follow-up', 'Reopened', 'reconciliation.review', NULL, 1, 1),
    ('reconciliation', 'Reopened', 'Prepared', 'reconciliation.prepare', 'prepare_review', 0, 1),
    ('reconciliation', 'Draft', 'Not Applicable', 'reconciliation.prepare', NULL, 1, 1),

    ('close_task', 'Draft', 'Prepared', NULL, 'prepare_review', 0, 1),
    ('close_task', 'Prepared', 'In Review', NULL, 'submit_approve', 0, 1),
    ('close_task', 'In Review', 'Reviewed', NULL, 'prepare_review', 0, 1),
    ('close_task', 'In Review', 'Needs Follow-up', NULL, NULL, 1, 1),
    ('close_task', 'Reviewed', 'Complete', NULL, 'submit_approve', 0, 1),
    ('close_task', 'Needs Follow-up', 'Reopened', NULL, NULL, 1, 1),
    ('close_task', 'Reopened', 'Prepared', NULL, 'prepare_review', 0, 1),
    ('close_task', 'Draft', 'Not Applicable', NULL, NULL, 1, 1),

    ('control_test', 'Draft', 'Prepared', 'controls.test', 'prepare_review', 0, 1),
    ('control_test', 'Prepared', 'In Review', 'controls.test', 'submit_approve', 0, 1),
    ('control_test', 'In Review', 'Reviewed', 'controls.test', 'prepare_review', 0, 1),
    ('control_test', 'In Review', 'Needs Follow-up', 'controls.test', NULL, 1, 1),
    ('control_test', 'Reviewed', 'Complete', 'controls.test', 'submit_approve', 0, 1),
    ('control_test', 'Needs Follow-up', 'Reopened', 'controls.test', NULL, 1, 1),
    ('control_test', 'Reopened', 'Prepared', 'controls.test', 'prepare_review', 0, 1),
    ('control_test', 'Draft', 'Not Applicable', 'controls.test', NULL, 1, 1),

    ('evidence_requirement', 'Draft', 'Prepared', NULL, 'prepare_review', 0, 1),
    ('evidence_requirement', 'Prepared', 'In Review', NULL, 'submit_approve', 0, 1),
    ('evidence_requirement', 'In Review', 'Reviewed', NULL, 'prepare_review', 0, 1),
    ('evidence_requirement', 'In Review', 'Needs Follow-up', NULL, NULL, 1, 1),
    ('evidence_requirement', 'Reviewed', 'Complete', NULL, 'submit_approve', 0, 1),
    ('evidence_requirement', 'Reviewed', 'Accepted Risk', NULL, NULL, 1, 1),
    ('evidence_requirement', 'Needs Follow-up', 'Reopened', NULL, NULL, 1, 1),
    ('evidence_requirement', 'Reopened', 'Prepared', NULL, 'prepare_review', 0, 1),
    ('evidence_requirement', 'Draft', 'Not Applicable', NULL, NULL, 1, 1);
"""

API_SESSIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS api_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_sessions_user ON api_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_api_sessions_expires ON api_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_api_sessions_revoked ON api_sessions(revoked_at);
"""

DB_BRIDGE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS legacy_import_records (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_checksum_sha256 TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (source_type, object_type, object_id)
);

CREATE INDEX IF NOT EXISTS idx_legacy_import_records_source ON legacy_import_records(source_type);
CREATE INDEX IF NOT EXISTS idx_legacy_import_records_object ON legacy_import_records(object_type, object_id);
"""

FINANCE_PLATFORM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS account_reconciliation_templates (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    account_code TEXT NOT NULL,
    name TEXT NOT NULL,
    risk_rating TEXT NOT NULL,
    materiality_threshold REAL NOT NULL DEFAULT 0,
    required_evidence TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, account_code)
);

CREATE TABLE IF NOT EXISTS trial_balance_rows (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    period_name TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL,
    balance REAL NOT NULL,
    currency TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (workspace_id, period_name, entity_code, account_code, source_path, source_row_number)
);

CREATE TABLE IF NOT EXISTS account_reconciliation_records (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    period_name TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL,
    template_id TEXT REFERENCES account_reconciliation_templates(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    balance REAL NOT NULL DEFAULT 0,
    materiality_threshold REAL NOT NULL DEFAULT 0,
    risk_rating TEXT NOT NULL DEFAULT 'medium',
    owner TEXT NOT NULL DEFAULT '',
    preparer TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    prepared_at TEXT,
    submitted_at TEXT,
    reviewed_at TEXT,
    completed_at TEXT,
    aging_days INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, period_name, entity_code, account_code)
);

CREATE TABLE IF NOT EXISTS account_reconciliation_items (
    id TEXT PRIMARY KEY,
    reconciliation_id TEXT NOT NULL REFERENCES account_reconciliation_records(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    evidence_required INTEGER NOT NULL DEFAULT 0 CHECK (evidence_required IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_reconciliation_support (
    id TEXT PRIMARY KEY,
    reconciliation_id TEXT NOT NULL REFERENCES account_reconciliation_records(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (reconciliation_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS close_periods (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    period_name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL,
    readiness_score REAL NOT NULL DEFAULT 0,
    locked_at TEXT,
    reopened_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, period_name)
);

CREATE TABLE IF NOT EXISTS close_tasks_db (
    id TEXT PRIMARY KEY,
    close_period_id TEXT NOT NULL REFERENCES close_periods(id) ON DELETE CASCADE,
    task_code TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    risk_rating TEXT NOT NULL DEFAULT 'medium',
    due_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    blocker_reason TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (close_period_id, task_code)
);

CREATE TABLE IF NOT EXISTS close_task_dependencies (
    id TEXT PRIMARY KEY,
    close_period_id TEXT NOT NULL REFERENCES close_periods(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES close_tasks_db(id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES close_tasks_db(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE (task_id, depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    title TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    assigned_to TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    override_reason TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS certification_records (
    id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    period_name TEXT NOT NULL DEFAULT '',
    entity_code TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    prepared_by TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (object_type, object_id)
);

CREATE TABLE IF NOT EXISTS evidence_registry (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    evidence_code TEXT NOT NULL,
    source_path TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    provenance_type TEXT NOT NULL,
    redaction_status TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    registered_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, evidence_code)
);

CREATE TABLE IF NOT EXISTS evidence_requirements (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    requirement_code TEXT NOT NULL,
    description TEXT NOT NULL,
    required_status TEXT NOT NULL DEFAULT 'Required',
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, object_type, object_id, requirement_code)
);

CREATE TABLE IF NOT EXISTS evidence_links (
    id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL REFERENCES evidence_registry(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (evidence_id, object_type, object_id, link_type)
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    journal_id TEXT NOT NULL,
    period_name TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    account_code TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    approver TEXT NOT NULL DEFAULT '',
    is_manual INTEGER NOT NULL DEFAULT 0 CHECK (is_manual IN (0, 1)),
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (workspace_id, journal_id)
);

CREATE TABLE IF NOT EXISTS journal_exceptions (
    id TEXT PRIMARY KEY,
    journal_entry_id TEXT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    policy_code TEXT NOT NULL,
    risk_rating TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (journal_entry_id, policy_code)
);

CREATE TABLE IF NOT EXISTS intercompany_transactions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    transaction_id TEXT NOT NULL,
    period_name TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    counterparty_code TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (workspace_id, transaction_id)
);

CREATE TABLE IF NOT EXISTS intercompany_cases (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    period_name TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    counterparty_code TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    imbalance_amount REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    dispute_owner TEXT NOT NULL DEFAULT '',
    settlement_status TEXT NOT NULL DEFAULT 'Open',
    aging_days INTEGER NOT NULL DEFAULT 0,
    evidence_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, period_name, entity_code, counterparty_code, reference)
);

CREATE TABLE IF NOT EXISTS control_library (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    control_code TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    risk_rating TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, control_code)
);

CREATE TABLE IF NOT EXISTS control_test_plans (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    control_id TEXT NOT NULL REFERENCES control_library(id) ON DELETE CASCADE,
    period_name TEXT NOT NULL,
    status TEXT NOT NULL,
    planned_by TEXT NOT NULL DEFAULT '',
    sample_size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (control_id, period_name)
);

CREATE TABLE IF NOT EXISTS control_test_samples (
    id TEXT PRIMARY KEY,
    test_plan_id TEXT NOT NULL REFERENCES control_test_plans(id) ON DELETE CASCADE,
    sample_reference TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (test_plan_id, sample_reference)
);

CREATE TABLE IF NOT EXISTS control_test_results (
    id TEXT PRIMARY KEY,
    test_plan_id TEXT NOT NULL REFERENCES control_test_plans(id) ON DELETE CASCADE,
    result_status TEXT NOT NULL,
    effectiveness_status TEXT NOT NULL,
    tested_by TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    evidence_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remediation_plans (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    target_date TEXT NOT NULL DEFAULT '',
    action_plan TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_jobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    left_source TEXT NOT NULL,
    right_source TEXT NOT NULL,
    status TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS match_rules (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES match_jobs(id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_results (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES match_jobs(id) ON DELETE CASCADE,
    left_id TEXT NOT NULL,
    right_id TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    explanation TEXT NOT NULL,
    amount_difference REAL NOT NULL DEFAULT 0,
    date_difference_days INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    lineage_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (job_id, left_id, right_id, match_type)
);

CREATE TABLE IF NOT EXISTS exceptions_queue (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    period_name TEXT NOT NULL DEFAULT '',
    entity_code TEXT NOT NULL DEFAULT '',
    account_code TEXT NOT NULL DEFAULT '',
    control_code TEXT NOT NULL DEFAULT '',
    risk_rating TEXT NOT NULL DEFAULT 'medium',
    owner TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    escalation_level TEXT NOT NULL DEFAULT '',
    sla_target_date TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS metric_definitions (
    id TEXT PRIMARY KEY,
    metric_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    lineage TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    period_name TEXT NOT NULL DEFAULT '',
    value REAL NOT NULL,
    value_text TEXT NOT NULL DEFAULT '',
    lineage TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE (workspace_id, metric_key, period_name)
);

CREATE TABLE IF NOT EXISTS ops_job_history (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS ops_error_records (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    error_code TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_account_reconciliations_queue ON account_reconciliation_records(status, owner, period_name, entity_code, risk_rating);
CREATE INDEX IF NOT EXISTS idx_close_tasks_queue ON close_tasks_db(status, owner, risk_rating);
CREATE INDEX IF NOT EXISTS idx_evidence_links_object ON evidence_links(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_policy ON journal_entries(period_name, entity_code, account_code);
CREATE INDEX IF NOT EXISTS idx_intercompany_transactions_match ON intercompany_transactions(period_name, reference, currency);
CREATE INDEX IF NOT EXISTS idx_exceptions_queue_filters ON exceptions_queue(status, owner, period_name, entity_code, risk_rating);
CREATE INDEX IF NOT EXISTS idx_match_results_job ON match_results(job_id, status, confidence);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_key ON metric_snapshots(metric_key, period_name);

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('accounts.read', 'Read DB-backed account reconciliation records.'),
    ('accounts.prepare', 'Prepare DB-backed account reconciliation records.'),
    ('accounts.review', 'Review DB-backed account reconciliation records.'),
    ('accounts.complete', 'Complete DB-backed account reconciliation records.'),
    ('close.read', 'Read DB-backed close periods and tasks.'),
    ('close.manage', 'Manage DB-backed close periods and tasks.'),
    ('approval.submit', 'Submit local approval requests.'),
    ('approval.approve', 'Approve or reject local approval requests.'),
    ('evidence.manage', 'Register and update DB-backed local evidence records.'),
    ('journals.read', 'Read DB-backed journal control records.'),
    ('journals.manage', 'Import journals and run local journal policies.'),
    ('intercompany.read', 'Read DB-backed intercompany cases.'),
    ('intercompany.manage', 'Import, match, and settle local intercompany cases.'),
    ('controls.manage', 'Manage DB-backed control library and testing records.'),
    ('match.read', 'Read DB-backed match jobs and results.'),
    ('match.run', 'Run deterministic local matching jobs.'),
    ('exceptions.read', 'Read the unified local exception queue.'),
    ('exceptions.manage', 'Assign and update the unified local exception queue.'),
    ('metrics.read', 'Read governed local dashboard metrics.'),
    ('ops.read', 'Read local operational health and job records.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'admin';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'accounts.read' AS permission_name
    UNION ALL SELECT 'accounts.prepare'
    UNION ALL SELECT 'accounts.review'
    UNION ALL SELECT 'accounts.complete'
    UNION ALL SELECT 'close.read'
    UNION ALL SELECT 'close.manage'
    UNION ALL SELECT 'approval.submit'
    UNION ALL SELECT 'approval.approve'
    UNION ALL SELECT 'evidence.manage'
    UNION ALL SELECT 'journals.read'
    UNION ALL SELECT 'journals.manage'
    UNION ALL SELECT 'intercompany.read'
    UNION ALL SELECT 'intercompany.manage'
    UNION ALL SELECT 'controls.manage'
    UNION ALL SELECT 'match.read'
    UNION ALL SELECT 'match.run'
    UNION ALL SELECT 'exceptions.read'
    UNION ALL SELECT 'exceptions.manage'
    UNION ALL SELECT 'metrics.read'
    UNION ALL SELECT 'ops.read'
) permissions
WHERE roles.name = 'controller';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'accounts.read' AS permission_name
    UNION ALL SELECT 'accounts.prepare'
    UNION ALL SELECT 'close.read'
    UNION ALL SELECT 'approval.submit'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'evidence.manage'
    UNION ALL SELECT 'exceptions.read'
    UNION ALL SELECT 'metrics.read'
) permissions
WHERE roles.name = 'preparer';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'accounts.read' AS permission_name
    UNION ALL SELECT 'accounts.review'
    UNION ALL SELECT 'accounts.complete'
    UNION ALL SELECT 'close.read'
    UNION ALL SELECT 'approval.approve'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'exceptions.read'
    UNION ALL SELECT 'exceptions.manage'
    UNION ALL SELECT 'metrics.read'
) permissions
WHERE roles.name = 'reviewer';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permission_name
FROM roles
JOIN (
    SELECT 'accounts.read' AS permission_name
    UNION ALL SELECT 'close.read'
    UNION ALL SELECT 'evidence.read'
    UNION ALL SELECT 'journals.read'
    UNION ALL SELECT 'intercompany.read'
    UNION ALL SELECT 'exceptions.read'
    UNION ALL SELECT 'metrics.read'
) permissions
WHERE roles.name = 'auditor-readonly';

INSERT OR IGNORE INTO workflow_transitions (
    object_type, from_status, to_status, required_permission, sod_rule, reason_required, active
)
VALUES
    ('approval_request', 'Draft', 'Submitted', 'approval.submit', 'prepare_review', 0, 1),
    ('approval_request', 'Submitted', 'Approved', 'approval.approve', 'prepare_review', 0, 1),
    ('approval_request', 'Submitted', 'Rejected', 'approval.approve', NULL, 1, 1),
    ('approval_request', 'Rejected', 'Submitted', 'approval.submit', NULL, 1, 1),
    ('exception_case', 'Open', 'In Review', 'exceptions.manage', NULL, 0, 1),
    ('exception_case', 'In Review', 'Resolved', 'exceptions.manage', 'prepare_review', 0, 1),
    ('exception_case', 'In Review', 'Accepted Risk', 'exceptions.manage', NULL, 1, 1),
    ('exception_case', 'Resolved', 'Closed', 'exceptions.manage', 'submit_approve', 0, 1);

INSERT OR IGNORE INTO metric_definitions (id, metric_key, name, description, lineage, created_at)
VALUES
    ('METDEF-close_completion', 'close_completion', 'Close completion', 'Percentage of DB close tasks marked Complete or Not Applicable.', 'close_tasks_db grouped by close_periods.period_name', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-unresolved_high_risk_exceptions', 'unresolved_high_risk_exceptions', 'Unresolved high-risk exceptions', 'Open high/critical queue records.', 'exceptions_queue filtered by status and risk_rating', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-review_aging', 'review_aging', 'Review aging', 'Average age in days for non-complete account reconciliations.', 'account_reconciliation_records aging_days by status', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-evidence_coverage', 'evidence_coverage', 'Evidence coverage', 'Evidence requirements with at least one linked evidence record.', 'evidence_requirements joined to evidence_links', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-control_effectiveness', 'control_effectiveness', 'Control testing effectiveness', 'Percentage of control test results marked Effective.', 'control_test_results.effectiveness_status', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-match_rate', 'match_rate', 'Match rate', 'Percentage of match results with status Matched.', 'match_results by job/status', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-exception_aging', 'exception_aging', 'Exception aging', 'Average age in days for unresolved exception queue records.', 'exceptions_queue.created_at by status', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('METDEF-period_readiness', 'period_readiness', 'Period readiness', 'Close readiness score stored for the period.', 'close_periods.readiness_score', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
"""

MASTER_DATA_SCHEMA_SQL = """
ALTER TABLE organizations ADD COLUMN organization_code TEXT NOT NULL DEFAULT '';
ALTER TABLE organizations ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1));
ALTER TABLE organizations ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';

UPDATE organizations
SET organization_code = printf('LEGACY-%08X', rowid),
    updated_at = created_at
WHERE organization_code = '';

ALTER TABLE legal_entities ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1));
ALTER TABLE legal_entities ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';

UPDATE legal_entities SET updated_at = created_at WHERE updated_at = '';

ALTER TABLE periods ADD COLUMN fiscal_year INTEGER NOT NULL DEFAULT 0 CHECK (fiscal_year >= 0);
ALTER TABLE periods ADD COLUMN period_number INTEGER NOT NULL DEFAULT 0 CHECK (period_number >= 0);
ALTER TABLE periods ADD COLUMN status_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE periods ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';

UPDATE periods
SET fiscal_year = CASE
        WHEN LENGTH(start_date) >= 4 THEN CAST(SUBSTR(start_date, 1, 4) AS INTEGER)
        ELSE 0
    END,
    period_number = CASE
        WHEN LENGTH(start_date) >= 7 THEN CAST(SUBSTR(start_date, 6, 2) AS INTEGER)
        ELSE 0
    END,
    updated_at = created_at
WHERE updated_at = '';

CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY CHECK (LENGTH(code) = 3 AND code = UPPER(code)),
    name TEXT NOT NULL,
    minor_units INTEGER NOT NULL DEFAULT 2 CHECK (minor_units BETWEEN 0 AND 6),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO currencies (code, name, minor_units, active, created_at, updated_at)
VALUES
    ('USD', 'US Dollar', 2, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('EUR', 'Euro', 2, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('GBP', 'Pound Sterling', 2, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('EGP', 'Egyptian Pound', 2, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('SAR', 'Saudi Riyal', 2, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('AED', 'UAE Dirham', 2, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

INSERT OR IGNORE INTO currencies (code, name, minor_units, active, created_at, updated_at)
SELECT DISTINCT UPPER(TRIM(currency)), UPPER(TRIM(currency)), 2, 1,
       strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
FROM legal_entities
WHERE LENGTH(TRIM(currency)) = 3;

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE SET NULL,
    branch_code TEXT NOT NULL,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, branch_code)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_workspace_code
ON organizations(workspace_id, organization_code);
CREATE INDEX IF NOT EXISTS idx_legal_entities_organization_active
ON legal_entities(organization_id, active, entity_code);
CREATE INDEX IF NOT EXISTS idx_branches_organization_active
ON branches(organization_id, active, branch_code);
CREATE INDEX IF NOT EXISTS idx_periods_workspace_status
ON periods(workspace_id, status, start_date, end_date);

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('master_data.read', 'Read local organization, entity, branch, currency, and period references.'),
    ('master_data.manage', 'Manage local organization, entity, branch, currency, and period references.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('master_data.read', 'master_data.manage');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('preparer', 'reviewer', 'auditor-readonly')
  AND permissions.name = 'master_data.read';
"""

FINANCE_CORE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS charts_of_accounts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    chart_code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, chart_code)
);

INSERT OR IGNORE INTO charts_of_accounts (
    id, workspace_id, organization_id, chart_code, name, description, active, created_at, updated_at
)
SELECT 'COA-' || id, id, NULL, 'DEFAULT', 'Default chart of accounts',
       'Migrated shared chart for existing workspace accounts.', 1, created_at, created_at
FROM workspaces;

ALTER TABLE accounts ADD COLUMN chart_id TEXT NOT NULL DEFAULT '';
ALTER TABLE accounts ADD COLUMN parent_account_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT;
ALTER TABLE accounts ADD COLUMN account_type TEXT NOT NULL DEFAULT 'Asset'
    CHECK (account_type IN ('Asset', 'Liability', 'Equity', 'Income', 'Expense', 'Off Balance'));
ALTER TABLE accounts ADD COLUMN normal_balance TEXT NOT NULL DEFAULT 'Debit'
    CHECK (normal_balance IN ('Debit', 'Credit'));
ALTER TABLE accounts ADD COLUMN allow_posting INTEGER NOT NULL DEFAULT 1 CHECK (allow_posting IN (0, 1));
ALTER TABLE accounts ADD COLUMN allow_manual_posting INTEGER NOT NULL DEFAULT 1 CHECK (allow_manual_posting IN (0, 1));
ALTER TABLE accounts ADD COLUMN reconciliation_required INTEGER NOT NULL DEFAULT 0
    CHECK (reconciliation_required IN (0, 1));
ALTER TABLE accounts ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1));
ALTER TABLE accounts ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE accounts ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';

UPDATE accounts
SET chart_id = 'COA-' || workspace_id,
    updated_at = created_at
WHERE chart_id = '';

CREATE TABLE IF NOT EXISTS accounting_dimensions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    dimension_code TEXT NOT NULL,
    name TEXT NOT NULL,
    dimension_type TEXT NOT NULL DEFAULT 'Custom'
        CHECK (dimension_type IN ('Cost Center', 'Department', 'Project', 'Custom')),
    required_on_entries INTEGER NOT NULL DEFAULT 0 CHECK (required_on_entries IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, dimension_code)
);

CREATE TABLE IF NOT EXISTS accounting_dimension_values (
    id TEXT PRIMARY KEY,
    dimension_id TEXT NOT NULL REFERENCES accounting_dimensions(id) ON DELETE CASCADE,
    value_code TEXT NOT NULL,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (dimension_id, value_code)
);

CREATE TABLE IF NOT EXISTS finance_journals (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    chart_id TEXT NOT NULL REFERENCES charts_of_accounts(id) ON DELETE RESTRICT,
    journal_code TEXT NOT NULL,
    name TEXT NOT NULL,
    journal_type TEXT NOT NULL DEFAULT 'General'
        CHECK (journal_type IN ('General', 'Sales', 'Purchase', 'Bank', 'Cash', 'Adjustment')),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, organization_id, journal_code)
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    chart_id TEXT NOT NULL REFERENCES charts_of_accounts(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    period_id TEXT NOT NULL REFERENCES periods(id) ON DELETE RESTRICT,
    finance_journal_id TEXT NOT NULL REFERENCES finance_journals(id) ON DELETE RESTRICT,
    entry_number TEXT NOT NULL,
    posting_date TEXT NOT NULL,
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    description TEXT NOT NULL,
    external_reference TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'Manual'
        CHECK (source_type IN ('Manual', 'Imported', 'Generated')),
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Validated', 'Voided')),
    created_by TEXT NOT NULL,
    validated_by TEXT NOT NULL DEFAULT '',
    validated_at TEXT,
    validation_reason TEXT NOT NULL DEFAULT '',
    voided_by TEXT NOT NULL DEFAULT '',
    voided_at TEXT,
    void_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, entry_number)
);

CREATE TABLE IF NOT EXISTS ledger_lines (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL REFERENCES ledger_entries(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    description TEXT NOT NULL DEFAULT '',
    debit_minor INTEGER NOT NULL DEFAULT 0 CHECK (debit_minor >= 0),
    credit_minor INTEGER NOT NULL DEFAULT 0 CHECK (credit_minor >= 0),
    created_at TEXT NOT NULL,
    CHECK ((debit_minor > 0 AND credit_minor = 0) OR (credit_minor > 0 AND debit_minor = 0)),
    UNIQUE (entry_id, line_number)
);

CREATE TABLE IF NOT EXISTS ledger_line_dimensions (
    line_id TEXT NOT NULL REFERENCES ledger_lines(id) ON DELETE CASCADE,
    dimension_value_id TEXT NOT NULL REFERENCES accounting_dimension_values(id) ON DELETE RESTRICT,
    PRIMARY KEY (line_id, dimension_value_id)
);

CREATE INDEX IF NOT EXISTS idx_charts_workspace_org
ON charts_of_accounts(workspace_id, organization_id, active, chart_code);
CREATE INDEX IF NOT EXISTS idx_accounts_chart_parent
ON accounts(chart_id, parent_account_id, active, account_code);
CREATE INDEX IF NOT EXISTS idx_dimensions_workspace_org
ON accounting_dimensions(workspace_id, organization_id, active, dimension_code);
CREATE INDEX IF NOT EXISTS idx_finance_journals_workspace_org
ON finance_journals(workspace_id, organization_id, active, journal_code);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_scope
ON ledger_entries(workspace_id, organization_id, legal_entity_id, period_id, status, posting_date);
CREATE INDEX IF NOT EXISTS idx_ledger_lines_account
ON ledger_lines(account_id, entry_id);

CREATE TRIGGER IF NOT EXISTS ledger_lines_insert_draft_only
BEFORE INSERT ON ledger_lines
WHEN COALESCE((SELECT status FROM ledger_entries WHERE id = NEW.entry_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'ledger lines require a draft entry');
END;

CREATE TRIGGER IF NOT EXISTS ledger_lines_update_draft_only
BEFORE UPDATE ON ledger_lines
WHEN COALESCE((SELECT status FROM ledger_entries WHERE id = OLD.entry_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'validated ledger lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ledger_lines_delete_draft_only
BEFORE DELETE ON ledger_lines
WHEN COALESCE((SELECT status FROM ledger_entries WHERE id = OLD.entry_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'validated ledger lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ledger_dimensions_insert_draft_only
BEFORE INSERT ON ledger_line_dimensions
WHEN COALESCE((
    SELECT ledger_entries.status
    FROM ledger_lines
    JOIN ledger_entries ON ledger_entries.id = ledger_lines.entry_id
    WHERE ledger_lines.id = NEW.line_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'ledger dimensions require a draft entry');
END;

CREATE TRIGGER IF NOT EXISTS ledger_dimensions_delete_draft_only
BEFORE DELETE ON ledger_line_dimensions
WHEN COALESCE((
    SELECT ledger_entries.status
    FROM ledger_lines
    JOIN ledger_entries ON ledger_entries.id = ledger_lines.entry_id
    WHERE ledger_lines.id = OLD.line_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'validated ledger dimensions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_status_transition
BEFORE UPDATE OF status ON ledger_entries
WHEN NEW.status <> OLD.status
 AND NOT (
    (OLD.status = 'Draft' AND NEW.status = 'Validated') OR
    (OLD.status = 'Validated' AND NEW.status = 'Voided')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid ledger entry status transition');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_validate_balanced
BEFORE UPDATE OF status ON ledger_entries
WHEN OLD.status = 'Draft' AND NEW.status = 'Validated'
 AND (
    (SELECT COUNT(*) FROM ledger_lines WHERE entry_id = OLD.id) < 2 OR
    COALESCE((SELECT SUM(debit_minor) FROM ledger_lines WHERE entry_id = OLD.id), 0) <= 0 OR
    COALESCE((SELECT SUM(debit_minor) FROM ledger_lines WHERE entry_id = OLD.id), 0)
        <> COALESCE((SELECT SUM(credit_minor) FROM ledger_lines WHERE entry_id = OLD.id), 0) OR
    NEW.validated_by = '' OR NEW.validated_at IS NULL OR NEW.validation_reason = ''
 )
BEGIN
    SELECT RAISE(ABORT, 'ledger entry must contain at least two balanced non-zero lines');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_void_requires_metadata
BEFORE UPDATE OF status ON ledger_entries
WHEN OLD.status = 'Validated' AND NEW.status = 'Voided'
 AND (NEW.voided_by = '' OR NEW.voided_at IS NULL OR NEW.void_reason = '')
BEGIN
    SELECT RAISE(ABORT, 'voiding a ledger entry requires actor, timestamp, and reason');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, chart_id, legal_entity_id, period_id,
                 finance_journal_id, entry_number, posting_date, currency_code, description,
                 external_reference, source_type, created_by, created_at
ON ledger_entries
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'validated ledger entry headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_validation_metadata_immutable
BEFORE UPDATE OF validated_by, validated_at, validation_reason ON ledger_entries
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'ledger validation metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_void_metadata_immutable
BEFORE UPDATE OF voided_by, voided_at, void_reason ON ledger_entries
WHEN OLD.status = 'Voided'
BEGIN
    SELECT RAISE(ABORT, 'ledger void metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS ledger_entry_delete_draft_only
BEFORE DELETE ON ledger_entries
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'validated ledger entries cannot be deleted');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('finance_core.read', 'Read local chart, dimension, journal, and ledger-control records.'),
    ('finance_core.manage', 'Manage local finance masters and draft ledger-control entries.'),
    ('finance_core.validate', 'Validate or void balanced local ledger-control entries.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('finance_core.read', 'finance_core.manage', 'finance_core.validate');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name IN ('finance_core.read', 'finance_core.manage');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name IN ('finance_core.read', 'finance_core.validate');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'auditor-readonly'
  AND permissions.name = 'finance_core.read';
"""

INVENTORY_CORE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS units_of_measure (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    uom_code TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Count'
        CHECK (category IN ('Count', 'Weight', 'Volume', 'Length', 'Time', 'Custom')),
    decimal_places INTEGER NOT NULL DEFAULT 0 CHECK (decimal_places BETWEEN 0 AND 6),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, uom_code)
);

INSERT OR IGNORE INTO units_of_measure (
    id, workspace_id, uom_code, name, category, decimal_places, active, created_at, updated_at
)
SELECT 'UOM-' || id, id, 'EA', 'Each', 'Count', 0, 1, created_at, created_at
FROM workspaces;

CREATE TABLE IF NOT EXISTS inventory_items (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    item_code TEXT NOT NULL,
    name TEXT NOT NULL,
    item_type TEXT NOT NULL DEFAULT 'Stock'
        CHECK (item_type IN ('Stock', 'Consumable', 'Service')),
    tracking_mode TEXT NOT NULL DEFAULT 'None'
        CHECK (tracking_mode IN ('None', 'Lot', 'Serial')),
    uom_id TEXT NOT NULL REFERENCES units_of_measure(id) ON DELETE RESTRICT,
    inventory_account_id TEXT REFERENCES accounts(id) ON DELETE RESTRICT,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, item_code)
);

CREATE TABLE IF NOT EXISTS warehouses (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    warehouse_code TEXT NOT NULL,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, organization_id, warehouse_code)
);

CREATE TABLE IF NOT EXISTS inventory_locations (
    id TEXT PRIMARY KEY,
    warehouse_id TEXT NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    parent_location_id TEXT REFERENCES inventory_locations(id) ON DELETE RESTRICT,
    location_code TEXT NOT NULL,
    name TEXT NOT NULL,
    location_type TEXT NOT NULL DEFAULT 'Internal'
        CHECK (location_type IN ('Internal', 'Transit', 'Supplier', 'Customer', 'Adjustment')),
    allow_negative INTEGER NOT NULL DEFAULT 0 CHECK (allow_negative IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (parent_location_id IS NULL OR parent_location_id <> id),
    UNIQUE (warehouse_id, location_code)
);

CREATE TABLE IF NOT EXISTS inventory_lots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    lot_serial_code TEXT NOT NULL,
    tracking_type TEXT NOT NULL CHECK (tracking_type IN ('Lot', 'Serial')),
    manufactured_on TEXT,
    expires_on TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (manufactured_on IS NULL OR expires_on IS NULL OR manufactured_on <= expires_on),
    UNIQUE (item_id, organization_id, lot_serial_code)
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    period_id TEXT NOT NULL REFERENCES periods(id) ON DELETE RESTRICT,
    movement_number TEXT NOT NULL,
    movement_type TEXT NOT NULL
        CHECK (movement_type IN ('Receipt', 'Delivery', 'Transfer', 'Adjustment')),
    movement_date TEXT NOT NULL,
    source_reference TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'Manual'
        CHECK (source_type IN ('Manual', 'Imported', 'Generated')),
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Posted', 'Voided')),
    created_by TEXT NOT NULL,
    posted_by TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    post_reason TEXT NOT NULL DEFAULT '',
    voided_by TEXT NOT NULL DEFAULT '',
    voided_at TEXT,
    void_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, movement_number)
);

CREATE TABLE IF NOT EXISTS inventory_movement_lines (
    id TEXT PRIMARY KEY,
    movement_id TEXT NOT NULL REFERENCES inventory_movements(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    uom_id TEXT NOT NULL REFERENCES units_of_measure(id) ON DELETE RESTRICT,
    inventory_lot_id TEXT REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    from_location_id TEXT REFERENCES inventory_locations(id) ON DELETE RESTRICT,
    to_location_id TEXT REFERENCES inventory_locations(id) ON DELETE RESTRICT,
    quantity_scaled INTEGER NOT NULL CHECK (quantity_scaled > 0),
    quantity_precision INTEGER NOT NULL CHECK (quantity_precision BETWEEN 0 AND 6),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK (from_location_id IS NOT NULL OR to_location_id IS NOT NULL),
    CHECK (from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id),
    UNIQUE (movement_id, line_number)
);

CREATE INDEX IF NOT EXISTS idx_inventory_items_scope
ON inventory_items(workspace_id, organization_id, active, item_code);
CREATE INDEX IF NOT EXISTS idx_warehouses_scope
ON warehouses(workspace_id, organization_id, legal_entity_id, active, warehouse_code);
CREATE INDEX IF NOT EXISTS idx_inventory_locations_warehouse
ON inventory_locations(warehouse_id, parent_location_id, active, location_code);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_item
ON inventory_lots(item_id, active, lot_serial_code);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_scope
ON inventory_movements(workspace_id, organization_id, legal_entity_id, period_id, status, movement_date);
CREATE INDEX IF NOT EXISTS idx_inventory_movement_lines_item
ON inventory_movement_lines(item_id, inventory_lot_id, from_location_id, to_location_id, movement_id);

CREATE TRIGGER IF NOT EXISTS inventory_movement_lines_insert_draft_only
BEFORE INSERT ON inventory_movement_lines
WHEN COALESCE((SELECT status FROM inventory_movements WHERE id = NEW.movement_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'inventory movement lines require a draft movement');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_lines_update_draft_only
BEFORE UPDATE ON inventory_movement_lines
WHEN COALESCE((SELECT status FROM inventory_movements WHERE id = OLD.movement_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'posted inventory movement lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_lines_delete_draft_only
BEFORE DELETE ON inventory_movement_lines
WHEN COALESCE((SELECT status FROM inventory_movements WHERE id = OLD.movement_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'posted inventory movement lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_status_transition
BEFORE UPDATE OF status ON inventory_movements
WHEN NEW.status <> OLD.status
 AND NOT (
    (OLD.status = 'Draft' AND NEW.status = 'Posted') OR
    (OLD.status = 'Posted' AND NEW.status = 'Voided')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid inventory movement status transition');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_post_integrity
BEFORE UPDATE OF status ON inventory_movements
WHEN OLD.status = 'Draft' AND NEW.status = 'Posted'
 AND (
    (SELECT COUNT(*) FROM inventory_movement_lines WHERE movement_id = OLD.id) < 1 OR
    NEW.posted_by = '' OR NEW.posted_at IS NULL OR NEW.post_reason = '' OR
    EXISTS (
        SELECT 1 FROM inventory_movement_lines lines
        WHERE lines.movement_id = OLD.id
          AND (
            (OLD.movement_type = 'Receipt' AND (lines.from_location_id IS NOT NULL OR lines.to_location_id IS NULL)) OR
            (OLD.movement_type = 'Delivery' AND (lines.from_location_id IS NULL OR lines.to_location_id IS NOT NULL)) OR
            (OLD.movement_type = 'Transfer' AND (lines.from_location_id IS NULL OR lines.to_location_id IS NULL)) OR
            (OLD.movement_type = 'Adjustment' AND ((lines.from_location_id IS NULL) = (lines.to_location_id IS NULL)))
          )
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'inventory movement posting requires valid lines and review metadata');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_void_requires_metadata
BEFORE UPDATE OF status ON inventory_movements
WHEN OLD.status = 'Posted' AND NEW.status = 'Voided'
 AND (NEW.voided_by = '' OR NEW.voided_at IS NULL OR NEW.void_reason = '')
BEGIN
    SELECT RAISE(ABORT, 'voiding an inventory movement requires actor, timestamp, and reason');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, legal_entity_id, period_id, movement_number,
                 movement_type, movement_date, source_reference, description, source_type,
                 created_by, created_at
ON inventory_movements
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'posted inventory movement headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_post_metadata_immutable
BEFORE UPDATE OF posted_by, posted_at, post_reason ON inventory_movements
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'inventory movement posting metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_void_metadata_immutable
BEFORE UPDATE OF voided_by, voided_at, void_reason ON inventory_movements
WHEN OLD.status = 'Voided'
BEGIN
    SELECT RAISE(ABORT, 'inventory movement void metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_delete_draft_only
BEFORE DELETE ON inventory_movements
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'posted inventory movements cannot be deleted');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('inventory.read', 'Read local inventory masters, movements, balances, and control exceptions.'),
    ('inventory.manage', 'Manage local inventory masters and draft movements.'),
    ('inventory.post', 'Post or void locally reviewed inventory movements.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('inventory.read', 'inventory.manage', 'inventory.post');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name IN ('inventory.read', 'inventory.manage');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name IN ('inventory.read', 'inventory.post');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'auditor-readonly'
  AND permissions.name = 'inventory.read';
"""

INVENTORY_PLANNING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inventory_count_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    period_id TEXT NOT NULL REFERENCES periods(id) ON DELETE RESTRICT,
    location_id TEXT NOT NULL REFERENCES inventory_locations(id) ON DELETE RESTRICT,
    count_number TEXT NOT NULL,
    count_date TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Counting', 'Submitted', 'Approved', 'Cancelled')),
    created_by TEXT NOT NULL,
    started_by TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    submitted_by TEXT NOT NULL DEFAULT '',
    submitted_at TEXT,
    submit_reason TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    approval_reason TEXT NOT NULL DEFAULT '',
    cancelled_by TEXT NOT NULL DEFAULT '',
    cancelled_at TEXT,
    cancel_reason TEXT NOT NULL DEFAULT '',
    adjustment_movement_id TEXT UNIQUE REFERENCES inventory_movements(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, count_number)
);

CREATE TABLE IF NOT EXISTS inventory_count_lines (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES inventory_count_sessions(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    uom_id TEXT NOT NULL REFERENCES units_of_measure(id) ON DELETE RESTRICT,
    inventory_lot_id TEXT REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    expected_quantity_scaled INTEGER NOT NULL,
    counted_quantity_scaled INTEGER CHECK (counted_quantity_scaled IS NULL OR counted_quantity_scaled >= 0),
    quantity_precision INTEGER NOT NULL CHECK (quantity_precision BETWEEN 0 AND 6),
    count_note TEXT NOT NULL DEFAULT '',
    counted_by TEXT NOT NULL DEFAULT '',
    counted_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, line_number),
    UNIQUE (session_id, item_id, inventory_lot_id)
);

CREATE TABLE IF NOT EXISTS inventory_reorder_rules (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    location_id TEXT NOT NULL REFERENCES inventory_locations(id) ON DELETE RESTRICT,
    minimum_quantity_scaled INTEGER NOT NULL CHECK (minimum_quantity_scaled >= 0),
    target_quantity_scaled INTEGER NOT NULL CHECK (target_quantity_scaled > minimum_quantity_scaled),
    quantity_precision INTEGER NOT NULL CHECK (quantity_precision BETWEEN 0 AND 6),
    lead_time_days INTEGER NOT NULL DEFAULT 0 CHECK (lead_time_days BETWEEN 0 AND 3650),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, organization_id, legal_entity_id, item_id, location_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_count_sessions_scope
ON inventory_count_sessions(workspace_id, organization_id, legal_entity_id, status, count_date);
CREATE INDEX IF NOT EXISTS idx_inventory_count_lines_session
ON inventory_count_lines(session_id, line_number, item_id, inventory_lot_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_count_lines_item_lot
ON inventory_count_lines(session_id, item_id, COALESCE(inventory_lot_id, ''));
CREATE INDEX IF NOT EXISTS idx_inventory_reorder_rules_scope
ON inventory_reorder_rules(workspace_id, organization_id, legal_entity_id, active, item_id, location_id);

CREATE TRIGGER IF NOT EXISTS inventory_count_insert_draft_only
BEFORE INSERT ON inventory_count_sessions
WHEN NEW.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'inventory counts must be created as Draft');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_status_transition
BEFORE UPDATE OF status ON inventory_count_sessions
WHEN NEW.status <> OLD.status
 AND NOT (
    (OLD.status = 'Draft' AND NEW.status IN ('Counting', 'Cancelled')) OR
    (OLD.status = 'Counting' AND NEW.status IN ('Submitted', 'Cancelled')) OR
    (OLD.status = 'Submitted' AND NEW.status IN ('Approved', 'Cancelled'))
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid inventory count status transition');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_start_integrity
BEFORE UPDATE OF status ON inventory_count_sessions
WHEN OLD.status = 'Draft' AND NEW.status = 'Counting'
 AND (
    NEW.started_by = '' OR NEW.started_at IS NULL OR
    (SELECT COUNT(*) FROM inventory_count_lines WHERE session_id = OLD.id) < 1
 )
BEGIN
    SELECT RAISE(ABORT, 'starting an inventory count requires snapshot lines and actor metadata');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_submit_integrity
BEFORE UPDATE OF status ON inventory_count_sessions
WHEN OLD.status = 'Counting' AND NEW.status = 'Submitted'
 AND (
    NEW.submitted_by = '' OR NEW.submitted_at IS NULL OR NEW.submit_reason = '' OR
    EXISTS (
        SELECT 1 FROM inventory_count_lines
        WHERE session_id = OLD.id AND counted_quantity_scaled IS NULL
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'submitting an inventory count requires completed lines and review metadata');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_approve_integrity
BEFORE UPDATE OF status ON inventory_count_sessions
WHEN OLD.status = 'Submitted' AND NEW.status = 'Approved'
 AND (NEW.approved_by = '' OR NEW.approved_at IS NULL OR NEW.approval_reason = '')
BEGIN
    SELECT RAISE(ABORT, 'approving an inventory count requires actor, timestamp, and reason');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_cancel_integrity
BEFORE UPDATE OF status ON inventory_count_sessions
WHEN NEW.status = 'Cancelled' AND OLD.status <> 'Cancelled'
 AND (NEW.cancelled_by = '' OR NEW.cancelled_at IS NULL OR NEW.cancel_reason = '')
BEGIN
    SELECT RAISE(ABORT, 'cancelling an inventory count requires actor, timestamp, and reason');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, legal_entity_id, period_id, location_id,
                 count_number, count_date, description, created_by, created_at
ON inventory_count_sessions
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'started inventory count headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_started_metadata_immutable
BEFORE UPDATE OF started_by, started_at ON inventory_count_sessions
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'inventory count start metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_submit_metadata_immutable
BEFORE UPDATE OF submitted_by, submitted_at, submit_reason ON inventory_count_sessions
WHEN OLD.status IN ('Submitted', 'Approved', 'Cancelled')
BEGIN
    SELECT RAISE(ABORT, 'inventory count submission metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_approval_metadata_immutable
BEFORE UPDATE OF approved_by, approved_at, approval_reason, adjustment_movement_id
ON inventory_count_sessions
WHEN OLD.status IN ('Approved', 'Cancelled')
BEGIN
    SELECT RAISE(ABORT, 'inventory count approval metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_cancel_metadata_immutable
BEFORE UPDATE OF cancelled_by, cancelled_at, cancel_reason ON inventory_count_sessions
WHEN OLD.status = 'Cancelled'
BEGIN
    SELECT RAISE(ABORT, 'inventory count cancellation metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_delete_draft_only
BEFORE DELETE ON inventory_count_sessions
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'started inventory counts cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_lines_insert_draft_only
BEFORE INSERT ON inventory_count_lines
WHEN COALESCE((SELECT status FROM inventory_count_sessions WHERE id = NEW.session_id), '') <> 'Draft'
 OR NEW.counted_quantity_scaled IS NOT NULL
 OR NEW.count_note <> ''
 OR NEW.counted_by <> ''
 OR NEW.counted_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'inventory count snapshot lines require a Draft session and empty count results');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_line_snapshot_immutable
BEFORE UPDATE OF session_id, line_number, item_id, uom_id, inventory_lot_id,
                 expected_quantity_scaled, quantity_precision, created_at
ON inventory_count_lines
BEGIN
    SELECT RAISE(ABORT, 'inventory count snapshot fields are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_lines_update_counting_only
BEFORE UPDATE OF counted_quantity_scaled, count_note, counted_by, counted_at
ON inventory_count_lines
WHEN COALESCE((SELECT status FROM inventory_count_sessions WHERE id = OLD.session_id), '') <> 'Counting'
BEGIN
    SELECT RAISE(ABORT, 'inventory count results can be updated only while counting');
END;

CREATE TRIGGER IF NOT EXISTS inventory_count_lines_delete_draft_only
BEFORE DELETE ON inventory_count_lines
WHEN COALESCE((SELECT status FROM inventory_count_sessions WHERE id = OLD.session_id), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'started inventory count lines are immutable');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('inventory.count.manage', 'Create, count, submit, or cancel local inventory count sessions.'),
    ('inventory.count.approve', 'Approve submitted local inventory counts and prepare draft adjustments.'),
    ('inventory.reorder.manage', 'Manage local inventory reorder thresholds and lead-time metadata.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('inventory.count.manage', 'inventory.count.approve', 'inventory.reorder.manage');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name IN ('inventory.count.manage', 'inventory.reorder.manage');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name = 'inventory.count.approve';
"""

INVENTORY_VALUATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inventory_valuation_policies (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    policy_code TEXT NOT NULL,
    costing_method TEXT NOT NULL DEFAULT 'FIFO' CHECK (costing_method = 'FIFO'),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    finance_journal_id TEXT NOT NULL REFERENCES finance_journals(id) ON DELETE RESTRICT,
    receipt_clearing_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    cogs_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    adjustment_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, organization_id, legal_entity_id, policy_code)
);

CREATE TABLE IF NOT EXISTS inventory_valuation_documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    period_id TEXT NOT NULL REFERENCES periods(id) ON DELETE RESTRICT,
    movement_id TEXT NOT NULL REFERENCES inventory_movements(id) ON DELETE RESTRICT,
    policy_id TEXT NOT NULL REFERENCES inventory_valuation_policies(id) ON DELETE RESTRICT,
    valuation_number TEXT NOT NULL,
    valuation_date TEXT NOT NULL,
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Approved', 'Cancelled')),
    total_value_minor INTEGER NOT NULL DEFAULT 0 CHECK (total_value_minor >= 0),
    finance_entry_id TEXT UNIQUE REFERENCES ledger_entries(id) ON DELETE RESTRICT,
    created_by TEXT NOT NULL,
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    approval_reason TEXT NOT NULL DEFAULT '',
    cancelled_by TEXT NOT NULL DEFAULT '',
    cancelled_at TEXT,
    cancel_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, valuation_number)
);

CREATE TABLE IF NOT EXISTS inventory_valuation_input_costs (
    id TEXT PRIMARY KEY,
    valuation_document_id TEXT NOT NULL REFERENCES inventory_valuation_documents(id) ON DELETE CASCADE,
    movement_line_id TEXT NOT NULL REFERENCES inventory_movement_lines(id) ON DELETE RESTRICT,
    total_cost_minor INTEGER NOT NULL CHECK (total_cost_minor > 0),
    created_at TEXT NOT NULL,
    UNIQUE (valuation_document_id, movement_line_id)
);

CREATE TABLE IF NOT EXISTS inventory_valuation_lines (
    id TEXT PRIMARY KEY,
    valuation_document_id TEXT NOT NULL REFERENCES inventory_valuation_documents(id) ON DELETE CASCADE,
    movement_line_id TEXT NOT NULL REFERENCES inventory_movement_lines(id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    flow_direction TEXT NOT NULL CHECK (flow_direction IN ('Inbound', 'Outbound')),
    item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    uom_id TEXT NOT NULL REFERENCES units_of_measure(id) ON DELETE RESTRICT,
    inventory_lot_id TEXT REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    quantity_scaled INTEGER NOT NULL CHECK (quantity_scaled > 0),
    quantity_precision INTEGER NOT NULL CHECK (quantity_precision BETWEEN 0 AND 6),
    value_minor INTEGER NOT NULL CHECK (value_minor > 0),
    inventory_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    offset_account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE (valuation_document_id, line_number),
    UNIQUE (valuation_document_id, movement_line_id)
);

CREATE TABLE IF NOT EXISTS inventory_cost_layers (
    id TEXT PRIMARY KEY,
    source_valuation_line_id TEXT NOT NULL UNIQUE REFERENCES inventory_valuation_lines(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
    uom_id TEXT NOT NULL REFERENCES units_of_measure(id) ON DELETE RESTRICT,
    inventory_lot_id TEXT REFERENCES inventory_lots(id) ON DELETE RESTRICT,
    quantity_precision INTEGER NOT NULL CHECK (quantity_precision BETWEEN 0 AND 6),
    original_quantity_scaled INTEGER NOT NULL CHECK (original_quantity_scaled > 0),
    remaining_quantity_scaled INTEGER NOT NULL CHECK (
        remaining_quantity_scaled >= 0 AND remaining_quantity_scaled <= original_quantity_scaled
    ),
    original_value_minor INTEGER NOT NULL CHECK (original_value_minor > 0),
    remaining_value_minor INTEGER NOT NULL CHECK (
        remaining_value_minor >= 0 AND remaining_value_minor <= original_value_minor
    ),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK (
        (remaining_quantity_scaled = 0 AND remaining_value_minor = 0) OR
        (remaining_quantity_scaled > 0 AND remaining_value_minor > 0)
    )
);

CREATE TABLE IF NOT EXISTS inventory_layer_consumptions (
    id TEXT PRIMARY KEY,
    valuation_line_id TEXT NOT NULL REFERENCES inventory_valuation_lines(id) ON DELETE RESTRICT,
    cost_layer_id TEXT NOT NULL REFERENCES inventory_cost_layers(id) ON DELETE RESTRICT,
    quantity_scaled INTEGER NOT NULL CHECK (quantity_scaled > 0),
    value_minor INTEGER NOT NULL CHECK (value_minor > 0),
    created_at TEXT NOT NULL,
    UNIQUE (valuation_line_id, cost_layer_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_valuation_policies_scope
ON inventory_valuation_policies(workspace_id, organization_id, legal_entity_id, active, policy_code);
CREATE INDEX IF NOT EXISTS idx_inventory_valuation_documents_scope
ON inventory_valuation_documents(workspace_id, organization_id, legal_entity_id, status, valuation_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_valuation_active_movement
ON inventory_valuation_documents(movement_id) WHERE status <> 'Cancelled';
CREATE INDEX IF NOT EXISTS idx_inventory_cost_layers_fifo
ON inventory_cost_layers(legal_entity_id, item_id, inventory_lot_id, created_at, id)
WHERE remaining_quantity_scaled > 0;
CREATE INDEX IF NOT EXISTS idx_inventory_layer_consumptions_layer
ON inventory_layer_consumptions(cost_layer_id, valuation_line_id);

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_insert_draft_only
BEFORE INSERT ON inventory_valuation_documents
WHEN NEW.status <> 'Draft' OR NEW.total_value_minor <> 0 OR NEW.finance_entry_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'inventory valuations must be created as empty Draft documents');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_status_transition
BEFORE UPDATE OF status ON inventory_valuation_documents
WHEN NEW.status <> OLD.status
 AND NOT (
    (OLD.status = 'Draft' AND NEW.status = 'Approved') OR
    (OLD.status = 'Draft' AND NEW.status = 'Cancelled')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid inventory valuation status transition');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_approve_integrity
BEFORE UPDATE OF status ON inventory_valuation_documents
WHEN OLD.status = 'Draft' AND NEW.status = 'Approved'
 AND (
    NEW.approved_by = '' OR NEW.approved_at IS NULL OR NEW.approval_reason = '' OR
    NEW.total_value_minor <= 0 OR NEW.finance_entry_id IS NULL OR
    COALESCE((SELECT status FROM inventory_movements WHERE id = OLD.movement_id), '') <> 'Posted' OR
    (SELECT COUNT(*) FROM inventory_valuation_lines WHERE valuation_document_id = OLD.id) < 1 OR
    NEW.total_value_minor <> COALESCE((
        SELECT SUM(value_minor) FROM inventory_valuation_lines WHERE valuation_document_id = OLD.id
    ), 0) OR
    NOT EXISTS (
        SELECT 1 FROM ledger_entries
        WHERE id = NEW.finance_entry_id
          AND status IN ('Draft', 'Validated')
          AND currency_code = NEW.currency_code
    ) OR
    NEW.total_value_minor <> COALESCE((
        SELECT SUM(debit_minor) FROM ledger_lines WHERE entry_id = NEW.finance_entry_id
    ), 0) OR
    NEW.total_value_minor <> COALESCE((
        SELECT SUM(credit_minor) FROM ledger_lines WHERE entry_id = NEW.finance_entry_id
    ), 0) OR
    EXISTS (
        SELECT 1
        FROM inventory_valuation_lines lines
        WHERE lines.valuation_document_id = OLD.id
          AND (
            (lines.flow_direction = 'Inbound' AND NOT EXISTS (
                SELECT 1 FROM inventory_cost_layers layers
                WHERE layers.source_valuation_line_id = lines.id
                  AND layers.original_quantity_scaled = lines.quantity_scaled
                  AND layers.original_value_minor = lines.value_minor
            )) OR
            (lines.flow_direction = 'Outbound' AND (
                lines.quantity_scaled <> COALESCE((
                    SELECT SUM(consumptions.quantity_scaled)
                    FROM inventory_layer_consumptions consumptions
                    WHERE consumptions.valuation_line_id = lines.id
                ), 0) OR
                lines.value_minor <> COALESCE((
                    SELECT SUM(consumptions.value_minor)
                    FROM inventory_layer_consumptions consumptions
                    WHERE consumptions.valuation_line_id = lines.id
                ), 0)
            ))
          )
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'inventory valuation approval requires complete layers and a balanced finance draft');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_cancel_integrity
BEFORE UPDATE OF status ON inventory_valuation_documents
WHEN OLD.status = 'Draft' AND NEW.status = 'Cancelled'
 AND (NEW.cancelled_by = '' OR NEW.cancelled_at IS NULL OR NEW.cancel_reason = '')
BEGIN
    SELECT RAISE(ABORT, 'cancelling an inventory valuation requires actor, timestamp, and reason');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, legal_entity_id, period_id, movement_id,
                 policy_id, valuation_number, valuation_date, currency_code, created_by, created_at
ON inventory_valuation_documents
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_approval_metadata_immutable
BEFORE UPDATE OF approved_by, approved_at, approval_reason, total_value_minor, finance_entry_id
ON inventory_valuation_documents
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'inventory valuation approval metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_document_delete_draft_only
BEFORE DELETE ON inventory_valuation_documents
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuations cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_input_costs_draft_only
BEFORE INSERT ON inventory_valuation_input_costs
WHEN COALESCE((
    SELECT status FROM inventory_valuation_documents WHERE id = NEW.valuation_document_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'valuation input costs require a Draft document');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_input_costs_update_draft_only
BEFORE UPDATE ON inventory_valuation_input_costs
WHEN COALESCE((
    SELECT status FROM inventory_valuation_documents WHERE id = OLD.valuation_document_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved valuation input costs are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_input_costs_delete_draft_only
BEFORE DELETE ON inventory_valuation_input_costs
WHEN COALESCE((
    SELECT status FROM inventory_valuation_documents WHERE id = OLD.valuation_document_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved valuation input costs are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_lines_insert_draft_only
BEFORE INSERT ON inventory_valuation_lines
WHEN COALESCE((
    SELECT status FROM inventory_valuation_documents WHERE id = NEW.valuation_document_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'valuation lines require a Draft document');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_lines_immutable
BEFORE UPDATE ON inventory_valuation_lines
BEGIN
    SELECT RAISE(ABORT, 'inventory valuation lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_lines_delete_draft_only
BEFORE DELETE ON inventory_valuation_lines
WHEN COALESCE((
    SELECT status FROM inventory_valuation_documents WHERE id = OLD.valuation_document_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved valuation lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_cost_layers_identity_immutable
BEFORE UPDATE OF source_valuation_line_id, legal_entity_id, item_id, uom_id, inventory_lot_id,
                 quantity_precision, original_quantity_scaled, original_value_minor, currency_code, created_at
ON inventory_cost_layers
BEGIN
    SELECT RAISE(ABORT, 'inventory cost-layer identity and origin are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_cost_layers_remaining_control
BEFORE UPDATE OF remaining_quantity_scaled, remaining_value_minor ON inventory_cost_layers
WHEN NEW.remaining_quantity_scaled > OLD.remaining_quantity_scaled
 OR NEW.remaining_value_minor > OLD.remaining_value_minor
 OR NEW.remaining_quantity_scaled <> OLD.original_quantity_scaled - COALESCE((
        SELECT SUM(quantity_scaled) FROM inventory_layer_consumptions WHERE cost_layer_id = OLD.id
    ), 0)
 OR NEW.remaining_value_minor <> OLD.original_value_minor - COALESCE((
        SELECT SUM(value_minor) FROM inventory_layer_consumptions WHERE cost_layer_id = OLD.id
    ), 0)
BEGIN
    SELECT RAISE(ABORT, 'cost-layer balances must match immutable consumption records');
END;

CREATE TRIGGER IF NOT EXISTS inventory_cost_layers_delete_blocked
BEFORE DELETE ON inventory_cost_layers
BEGIN
    SELECT RAISE(ABORT, 'inventory cost layers cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS inventory_layer_consumptions_insert_draft_only
BEFORE INSERT ON inventory_layer_consumptions
WHEN COALESCE((
    SELECT documents.status
    FROM inventory_valuation_lines lines
    JOIN inventory_valuation_documents documents ON documents.id = lines.valuation_document_id
    WHERE lines.id = NEW.valuation_line_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'layer consumptions require a Draft valuation document');
END;

CREATE TRIGGER IF NOT EXISTS inventory_layer_consumptions_immutable
BEFORE UPDATE ON inventory_layer_consumptions
BEGIN
    SELECT RAISE(ABORT, 'inventory layer consumptions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_layer_consumptions_delete_blocked
BEFORE DELETE ON inventory_layer_consumptions
BEGIN
    SELECT RAISE(ABORT, 'inventory layer consumptions cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS inventory_movement_void_blocked_after_valuation
BEFORE UPDATE OF status ON inventory_movements
WHEN OLD.status = 'Posted' AND NEW.status = 'Voided'
 AND EXISTS (
    SELECT 1 FROM inventory_valuation_documents
    WHERE movement_id = OLD.id AND status = 'Approved'
 )
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation must be reversed before voiding its movement');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_lines_insert_blocked
BEFORE INSERT ON ledger_lines
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_documents
    WHERE finance_entry_id = NEW.entry_id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_lines_update_blocked
BEFORE UPDATE ON ledger_lines
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_documents
    WHERE finance_entry_id = OLD.entry_id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_lines_delete_blocked
BEFORE DELETE ON ledger_lines
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_documents
    WHERE finance_entry_id = OLD.entry_id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, chart_id, legal_entity_id, period_id,
                 finance_journal_id, entry_number, posting_date, currency_code, description,
                 external_reference, source_type, created_by, created_at
ON ledger_entries
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_documents
    WHERE finance_entry_id = OLD.id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_void_blocked
BEFORE UPDATE OF status ON ledger_entries
WHEN OLD.status = 'Validated' AND NEW.status = 'Voided'
 AND EXISTS (
    SELECT 1 FROM inventory_valuation_documents
    WHERE finance_entry_id = OLD.id AND status = 'Approved'
 )
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation must be reversed before voiding its finance entry');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('inventory.valuation.manage', 'Configure FIFO policies and prepare local inventory valuation drafts.'),
    ('inventory.valuation.approve', 'Approve FIFO valuations and generate balanced Finance Core drafts.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('inventory.valuation.manage', 'inventory.valuation.approve');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name = 'inventory.valuation.manage';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name = 'inventory.valuation.approve';
"""

INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inventory_valuation_reversals (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id) ON DELETE RESTRICT,
    period_id TEXT NOT NULL REFERENCES periods(id) ON DELETE RESTRICT,
    original_valuation_document_id TEXT NOT NULL
        REFERENCES inventory_valuation_documents(id) ON DELETE RESTRICT,
    reversal_movement_id TEXT NOT NULL REFERENCES inventory_movements(id) ON DELETE RESTRICT,
    reversal_number TEXT NOT NULL,
    reversal_date TEXT NOT NULL,
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Approved', 'Cancelled')),
    total_value_minor INTEGER NOT NULL DEFAULT 0 CHECK (total_value_minor >= 0),
    finance_entry_id TEXT UNIQUE REFERENCES ledger_entries(id) ON DELETE RESTRICT,
    created_by TEXT NOT NULL,
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    approval_reason TEXT NOT NULL DEFAULT '',
    cancelled_by TEXT NOT NULL DEFAULT '',
    cancelled_at TEXT,
    cancel_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, reversal_number)
);

CREATE TABLE IF NOT EXISTS inventory_valuation_reversal_effects (
    id TEXT PRIMARY KEY,
    reversal_id TEXT NOT NULL REFERENCES inventory_valuation_reversals(id) ON DELETE CASCADE,
    original_valuation_line_id TEXT NOT NULL
        REFERENCES inventory_valuation_lines(id) ON DELETE RESTRICT,
    original_consumption_id TEXT REFERENCES inventory_layer_consumptions(id) ON DELETE RESTRICT,
    cost_layer_id TEXT NOT NULL REFERENCES inventory_cost_layers(id) ON DELETE RESTRICT,
    effect_type TEXT NOT NULL CHECK (effect_type IN ('Restore', 'Remove')),
    quantity_scaled INTEGER NOT NULL CHECK (quantity_scaled > 0),
    value_minor INTEGER NOT NULL CHECK (value_minor > 0),
    created_at TEXT NOT NULL,
    CHECK (
        (effect_type = 'Remove' AND original_consumption_id IS NULL) OR
        (effect_type = 'Restore' AND original_consumption_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_valuation_reversal_active_document
ON inventory_valuation_reversals(original_valuation_document_id) WHERE status <> 'Cancelled';
CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_valuation_reversal_active_movement
ON inventory_valuation_reversals(reversal_movement_id) WHERE status <> 'Cancelled';
CREATE INDEX IF NOT EXISTS idx_inventory_valuation_reversals_scope
ON inventory_valuation_reversals(workspace_id, organization_id, legal_entity_id, status, reversal_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_valuation_reversal_remove_line
ON inventory_valuation_reversal_effects(reversal_id, original_valuation_line_id)
WHERE effect_type = 'Remove';
CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_valuation_reversal_restore_consumption
ON inventory_valuation_reversal_effects(reversal_id, original_consumption_id)
WHERE effect_type = 'Restore';
CREATE INDEX IF NOT EXISTS idx_inventory_valuation_reversal_effects_layer
ON inventory_valuation_reversal_effects(cost_layer_id, reversal_id);

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_insert_draft_only
BEFORE INSERT ON inventory_valuation_reversals
WHEN NEW.status <> 'Draft' OR NEW.total_value_minor <> 0 OR NEW.finance_entry_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'inventory valuation reversals must be created as empty Draft records');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_status_transition
BEFORE UPDATE OF status ON inventory_valuation_reversals
WHEN NEW.status <> OLD.status
 AND NOT (
    (OLD.status = 'Draft' AND NEW.status = 'Approved') OR
    (OLD.status = 'Draft' AND NEW.status = 'Cancelled')
 )
BEGIN
    SELECT RAISE(ABORT, 'invalid inventory valuation reversal status transition');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_approve_integrity
BEFORE UPDATE OF status ON inventory_valuation_reversals
WHEN OLD.status = 'Draft' AND NEW.status = 'Approved'
 AND (
    NEW.approved_by = '' OR NEW.approved_at IS NULL OR NEW.approval_reason = '' OR
    NEW.total_value_minor <= 0 OR NEW.finance_entry_id IS NULL OR
    COALESCE((
        SELECT status FROM inventory_valuation_documents
        WHERE id = OLD.original_valuation_document_id
    ), '') <> 'Approved' OR
    EXISTS (
        SELECT 1 FROM inventory_valuation_documents documents
        WHERE documents.id = OLD.original_valuation_document_id
          AND (
            documents.workspace_id <> OLD.workspace_id OR
            documents.organization_id <> OLD.organization_id OR
            documents.legal_entity_id <> OLD.legal_entity_id OR
            documents.currency_code <> OLD.currency_code
          )
    ) OR
    COALESCE((
        SELECT status FROM inventory_movements WHERE id = OLD.reversal_movement_id
    ), '') <> 'Posted' OR
    NOT EXISTS (
        SELECT 1
        FROM inventory_movements reversal_movements
        JOIN inventory_valuation_documents original_documents
          ON original_documents.id = OLD.original_valuation_document_id
        JOIN inventory_movements original_movements
          ON original_movements.id = original_documents.movement_id
        WHERE reversal_movements.id = OLD.reversal_movement_id
          AND (
            (original_movements.movement_type = 'Receipt'
             AND reversal_movements.movement_type = 'Delivery') OR
            (original_movements.movement_type = 'Delivery'
             AND reversal_movements.movement_type = 'Receipt') OR
            (original_movements.movement_type = 'Adjustment'
             AND reversal_movements.movement_type = 'Adjustment')
          )
    ) OR
    EXISTS (
        SELECT 1 FROM inventory_movements movements
        WHERE movements.id = OLD.reversal_movement_id
          AND (
            movements.workspace_id <> OLD.workspace_id OR
            movements.organization_id <> OLD.organization_id OR
            movements.legal_entity_id <> OLD.legal_entity_id OR
            movements.period_id <> OLD.period_id OR
            movements.movement_date <> OLD.reversal_date
          )
    ) OR
    NEW.total_value_minor <> COALESCE((
        SELECT total_value_minor FROM inventory_valuation_documents
        WHERE id = OLD.original_valuation_document_id
    ), 0) OR
    (SELECT COUNT(*) FROM inventory_valuation_reversal_effects WHERE reversal_id = OLD.id) < 1 OR
    NEW.total_value_minor <> COALESCE((
        SELECT SUM(value_minor) FROM inventory_valuation_reversal_effects
        WHERE reversal_id = OLD.id
    ), 0) OR
    NOT EXISTS (
        SELECT 1 FROM ledger_entries entries
        WHERE entries.id = NEW.finance_entry_id
          AND entries.status = 'Draft'
          AND entries.workspace_id = OLD.workspace_id
          AND entries.organization_id = OLD.organization_id
          AND entries.legal_entity_id = OLD.legal_entity_id
          AND entries.period_id = OLD.period_id
          AND entries.posting_date = OLD.reversal_date
          AND entries.currency_code = OLD.currency_code
          AND entries.source_type = 'Generated'
          AND entries.chart_id = (
              SELECT chart_id FROM ledger_entries
              WHERE id = (
                  SELECT finance_entry_id FROM inventory_valuation_documents
                  WHERE id = OLD.original_valuation_document_id
              )
          )
          AND entries.finance_journal_id = (
              SELECT finance_journal_id FROM ledger_entries
              WHERE id = (
                  SELECT finance_entry_id FROM inventory_valuation_documents
                  WHERE id = OLD.original_valuation_document_id
              )
          )
    ) OR
    NEW.total_value_minor <> COALESCE((
        SELECT SUM(debit_minor) FROM ledger_lines WHERE entry_id = NEW.finance_entry_id
    ), 0) OR
    NEW.total_value_minor <> COALESCE((
        SELECT SUM(credit_minor) FROM ledger_lines WHERE entry_id = NEW.finance_entry_id
    ), 0) OR
    (SELECT COUNT(*) FROM ledger_lines WHERE entry_id = NEW.finance_entry_id)
      <> (SELECT COUNT(*) FROM ledger_lines
          WHERE entry_id = (
              SELECT finance_entry_id FROM inventory_valuation_documents
              WHERE id = OLD.original_valuation_document_id
          )) OR
    EXISTS (
        SELECT 1
        FROM ledger_lines original_finance_lines
        WHERE original_finance_lines.entry_id = (
            SELECT finance_entry_id FROM inventory_valuation_documents
            WHERE id = OLD.original_valuation_document_id
        )
          AND (
            NOT EXISTS (
                SELECT 1 FROM ledger_lines reversal_finance_lines
                WHERE reversal_finance_lines.entry_id = NEW.finance_entry_id
                  AND reversal_finance_lines.line_number = original_finance_lines.line_number
                  AND reversal_finance_lines.account_id = original_finance_lines.account_id
                  AND reversal_finance_lines.debit_minor = original_finance_lines.credit_minor
                  AND reversal_finance_lines.credit_minor = original_finance_lines.debit_minor
            ) OR
            EXISTS (
                SELECT dimension_value_id FROM ledger_line_dimensions
                WHERE line_id = original_finance_lines.id
                EXCEPT
                SELECT reversal_dimensions.dimension_value_id
                FROM ledger_line_dimensions reversal_dimensions
                JOIN ledger_lines reversal_dimension_lines
                  ON reversal_dimension_lines.id = reversal_dimensions.line_id
                WHERE reversal_dimension_lines.entry_id = NEW.finance_entry_id
                  AND reversal_dimension_lines.line_number = original_finance_lines.line_number
            ) OR
            EXISTS (
                SELECT reversal_dimensions.dimension_value_id
                FROM ledger_line_dimensions reversal_dimensions
                JOIN ledger_lines reversal_dimension_lines
                  ON reversal_dimension_lines.id = reversal_dimensions.line_id
                WHERE reversal_dimension_lines.entry_id = NEW.finance_entry_id
                  AND reversal_dimension_lines.line_number = original_finance_lines.line_number
                EXCEPT
                SELECT dimension_value_id FROM ledger_line_dimensions
                WHERE line_id = original_finance_lines.id
            )
          )
    ) OR
    EXISTS (
        SELECT original_lines.line_number
        FROM inventory_valuation_lines original_lines
        JOIN inventory_valuation_documents original_documents
          ON original_documents.id = original_lines.valuation_document_id
        JOIN inventory_movement_lines original_movement_lines
          ON original_movement_lines.id = original_lines.movement_line_id
        LEFT JOIN inventory_movement_lines reversal_lines
          ON reversal_lines.movement_id = OLD.reversal_movement_id
         AND reversal_lines.line_number = original_lines.line_number
         AND reversal_lines.item_id = original_movement_lines.item_id
         AND reversal_lines.uom_id = original_movement_lines.uom_id
         AND COALESCE(reversal_lines.inventory_lot_id, '')
             = COALESCE(original_movement_lines.inventory_lot_id, '')
         AND COALESCE(reversal_lines.from_location_id, '')
             = COALESCE(original_movement_lines.to_location_id, '')
         AND COALESCE(reversal_lines.to_location_id, '')
             = COALESCE(original_movement_lines.from_location_id, '')
         AND reversal_lines.quantity_scaled = original_movement_lines.quantity_scaled
         AND reversal_lines.quantity_precision = original_movement_lines.quantity_precision
        WHERE original_documents.id = OLD.original_valuation_document_id
          AND reversal_lines.id IS NULL
    ) OR
    (SELECT COUNT(*) FROM inventory_movement_lines WHERE movement_id = OLD.reversal_movement_id)
      <> (SELECT COUNT(*) FROM inventory_valuation_lines
          WHERE valuation_document_id = OLD.original_valuation_document_id) OR
    EXISTS (
        SELECT 1
        FROM inventory_valuation_reversal_effects effects
        JOIN inventory_valuation_lines lines ON lines.id = effects.original_valuation_line_id
        LEFT JOIN inventory_layer_consumptions consumptions
          ON consumptions.id = effects.original_consumption_id
        LEFT JOIN inventory_cost_layers layers ON layers.id = effects.cost_layer_id
        WHERE effects.reversal_id = OLD.id
          AND (
            lines.valuation_document_id <> OLD.original_valuation_document_id OR
            (effects.effect_type = 'Remove' AND (
                lines.flow_direction <> 'Inbound' OR
                layers.source_valuation_line_id <> lines.id OR
                effects.quantity_scaled <> lines.quantity_scaled OR
                effects.value_minor <> lines.value_minor
            )) OR
            (effects.effect_type = 'Restore' AND (
                lines.flow_direction <> 'Outbound' OR
                consumptions.valuation_line_id <> lines.id OR
                consumptions.cost_layer_id <> effects.cost_layer_id OR
                effects.quantity_scaled <> consumptions.quantity_scaled OR
                effects.value_minor <> consumptions.value_minor
            ))
          )
    ) OR
    EXISTS (
        SELECT 1
        FROM inventory_cost_layers layers
        WHERE layers.id IN (
            SELECT effects.cost_layer_id
            FROM inventory_valuation_reversal_effects effects
            WHERE effects.reversal_id = OLD.id
        )
          AND (
            layers.remaining_quantity_scaled <> layers.original_quantity_scaled - COALESCE((
                SELECT SUM(consumptions.quantity_scaled)
                FROM inventory_layer_consumptions consumptions
                WHERE consumptions.cost_layer_id = layers.id
            ), 0) + COALESCE((
                SELECT SUM(CASE effects.effect_type
                    WHEN 'Restore' THEN effects.quantity_scaled ELSE -effects.quantity_scaled END)
                FROM inventory_valuation_reversal_effects effects
                WHERE effects.cost_layer_id = layers.id
            ), 0) OR
            layers.remaining_value_minor <> layers.original_value_minor - COALESCE((
                SELECT SUM(consumptions.value_minor)
                FROM inventory_layer_consumptions consumptions
                WHERE consumptions.cost_layer_id = layers.id
            ), 0) + COALESCE((
                SELECT SUM(CASE effects.effect_type
                    WHEN 'Restore' THEN effects.value_minor ELSE -effects.value_minor END)
                FROM inventory_valuation_reversal_effects effects
                WHERE effects.cost_layer_id = layers.id
            ), 0)
          )
    ) OR
    EXISTS (
        SELECT 1 FROM inventory_valuation_lines lines
        WHERE lines.valuation_document_id = OLD.original_valuation_document_id
          AND lines.flow_direction = 'Inbound'
          AND NOT EXISTS (
            SELECT 1 FROM inventory_valuation_reversal_effects effects
            WHERE effects.reversal_id = OLD.id
              AND effects.original_valuation_line_id = lines.id
              AND effects.effect_type = 'Remove'
          )
    ) OR
    EXISTS (
        SELECT 1
        FROM inventory_layer_consumptions consumptions
        JOIN inventory_valuation_lines lines ON lines.id = consumptions.valuation_line_id
        WHERE lines.valuation_document_id = OLD.original_valuation_document_id
          AND NOT EXISTS (
            SELECT 1 FROM inventory_valuation_reversal_effects effects
            WHERE effects.reversal_id = OLD.id
              AND effects.original_consumption_id = consumptions.id
              AND effects.effect_type = 'Restore'
          )
    ) OR
    EXISTS (
        SELECT account_id, SUM(debit_minor), SUM(credit_minor)
        FROM ledger_lines
        WHERE entry_id = (
            SELECT finance_entry_id FROM inventory_valuation_documents
            WHERE id = OLD.original_valuation_document_id
        )
        GROUP BY account_id
        EXCEPT
        SELECT account_id, SUM(credit_minor), SUM(debit_minor)
        FROM ledger_lines WHERE entry_id = NEW.finance_entry_id
        GROUP BY account_id
    ) OR
    EXISTS (
        SELECT account_id, SUM(credit_minor), SUM(debit_minor)
        FROM ledger_lines WHERE entry_id = NEW.finance_entry_id
        GROUP BY account_id
        EXCEPT
        SELECT account_id, SUM(debit_minor), SUM(credit_minor)
        FROM ledger_lines
        WHERE entry_id = (
            SELECT finance_entry_id FROM inventory_valuation_documents
            WHERE id = OLD.original_valuation_document_id
        )
        GROUP BY account_id
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'valuation reversal approval requires exact mirror movement, layer effects, and finance draft');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_cancel_integrity
BEFORE UPDATE OF status ON inventory_valuation_reversals
WHEN OLD.status = 'Draft' AND NEW.status = 'Cancelled'
 AND (NEW.cancelled_by = '' OR NEW.cancelled_at IS NULL OR NEW.cancel_reason = '')
BEGIN
    SELECT RAISE(ABORT, 'cancelling a valuation reversal requires actor, timestamp, and reason');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, legal_entity_id, period_id,
                 original_valuation_document_id, reversal_movement_id, reversal_number,
                 reversal_date, currency_code, created_by, created_at
ON inventory_valuation_reversals
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_approval_immutable
BEFORE UPDATE OF approved_by, approved_at, approval_reason, total_value_minor, finance_entry_id
ON inventory_valuation_reversals
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'valuation reversal approval metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_delete_draft_only
BEFORE DELETE ON inventory_valuation_reversals
WHEN OLD.status <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversals cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_effect_insert_draft_only
BEFORE INSERT ON inventory_valuation_reversal_effects
WHEN COALESCE((
    SELECT status FROM inventory_valuation_reversals WHERE id = NEW.reversal_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'layer reversal effects require a Draft valuation reversal');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_effect_immutable
BEFORE UPDATE ON inventory_valuation_reversal_effects
BEGIN
    SELECT RAISE(ABORT, 'valuation reversal layer effects are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_reversal_effect_delete_draft_only
BEFORE DELETE ON inventory_valuation_reversal_effects
WHEN COALESCE((
    SELECT status FROM inventory_valuation_reversals WHERE id = OLD.reversal_id
), '') <> 'Draft'
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal layer effects are immutable');
END;

DROP TRIGGER IF EXISTS inventory_cost_layers_remaining_control;
CREATE TRIGGER inventory_cost_layers_remaining_control
BEFORE UPDATE OF remaining_quantity_scaled, remaining_value_minor ON inventory_cost_layers
WHEN NEW.remaining_quantity_scaled <> OLD.original_quantity_scaled - COALESCE((
        SELECT SUM(quantity_scaled) FROM inventory_layer_consumptions WHERE cost_layer_id = OLD.id
    ), 0) + COALESCE((
        SELECT SUM(CASE effect_type WHEN 'Restore' THEN quantity_scaled ELSE -quantity_scaled END)
        FROM inventory_valuation_reversal_effects WHERE cost_layer_id = OLD.id
    ), 0)
 OR NEW.remaining_value_minor <> OLD.original_value_minor - COALESCE((
        SELECT SUM(value_minor) FROM inventory_layer_consumptions WHERE cost_layer_id = OLD.id
    ), 0) + COALESCE((
        SELECT SUM(CASE effect_type WHEN 'Restore' THEN value_minor ELSE -value_minor END)
        FROM inventory_valuation_reversal_effects WHERE cost_layer_id = OLD.id
    ), 0)
BEGIN
    SELECT RAISE(ABORT, 'cost-layer balances must match immutable consumption and reversal records');
END;

CREATE TRIGGER IF NOT EXISTS inventory_reversal_movement_void_blocked
BEFORE UPDATE OF status ON inventory_movements
WHEN OLD.status = 'Posted' AND NEW.status = 'Voided'
 AND EXISTS (
    SELECT 1 FROM inventory_valuation_reversals
    WHERE reversal_movement_id = OLD.id AND status = 'Approved'
 )
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal movement cannot be voided');
END;

CREATE TRIGGER IF NOT EXISTS inventory_reversal_finance_lines_insert_blocked
BEFORE INSERT ON ledger_lines
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_reversals
    WHERE finance_entry_id = NEW.entry_id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal finance lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_reversal_finance_lines_update_blocked
BEFORE UPDATE ON ledger_lines
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_reversals
    WHERE finance_entry_id = OLD.entry_id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal finance lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_reversal_finance_lines_delete_blocked
BEFORE DELETE ON ledger_lines
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_reversals
    WHERE finance_entry_id = OLD.entry_id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal finance lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_dimensions_insert_blocked
BEFORE INSERT ON ledger_line_dimensions
WHEN EXISTS (
    SELECT 1
    FROM ledger_lines lines
    WHERE lines.id = NEW.line_id
      AND (
        EXISTS (
            SELECT 1 FROM inventory_valuation_documents
            WHERE finance_entry_id = lines.entry_id AND status = 'Approved'
        ) OR
        EXISTS (
            SELECT 1 FROM inventory_valuation_reversals
            WHERE finance_entry_id = lines.entry_id AND status = 'Approved'
        )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance dimensions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_dimensions_update_blocked
BEFORE UPDATE ON ledger_line_dimensions
WHEN EXISTS (
    SELECT 1
    FROM ledger_lines lines
    WHERE lines.id IN (OLD.line_id, NEW.line_id)
      AND (
        EXISTS (
            SELECT 1 FROM inventory_valuation_documents
            WHERE finance_entry_id = lines.entry_id AND status = 'Approved'
        ) OR
        EXISTS (
            SELECT 1 FROM inventory_valuation_reversals
            WHERE finance_entry_id = lines.entry_id AND status = 'Approved'
        )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance dimensions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_valuation_finance_dimensions_delete_blocked
BEFORE DELETE ON ledger_line_dimensions
WHEN EXISTS (
    SELECT 1
    FROM ledger_lines lines
    WHERE lines.id = OLD.line_id
      AND (
        EXISTS (
            SELECT 1 FROM inventory_valuation_documents
            WHERE finance_entry_id = lines.entry_id AND status = 'Approved'
        ) OR
        EXISTS (
            SELECT 1 FROM inventory_valuation_reversals
            WHERE finance_entry_id = lines.entry_id AND status = 'Approved'
        )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'approved inventory valuation finance dimensions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_reversal_finance_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, chart_id, legal_entity_id, period_id,
                 finance_journal_id, entry_number, posting_date, currency_code, description,
                 external_reference, source_type, created_by, created_at
ON ledger_entries
WHEN EXISTS (
    SELECT 1 FROM inventory_valuation_reversals
    WHERE finance_entry_id = OLD.id AND status = 'Approved'
)
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal finance headers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS inventory_reversal_finance_void_blocked
BEFORE UPDATE OF status ON ledger_entries
WHEN OLD.status = 'Validated' AND NEW.status = 'Voided'
 AND EXISTS (
    SELECT 1 FROM inventory_valuation_reversals
    WHERE finance_entry_id = OLD.id AND status = 'Approved'
 )
BEGIN
    SELECT RAISE(ABORT, 'approved valuation reversal finance entry cannot be voided');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('inventory.valuation.reverse.manage', 'Prepare or cancel Draft FIFO valuation reversals.'),
    ('inventory.valuation.reverse.approve', 'Approve FIFO valuation reversals and generate mirror Finance Core drafts.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('inventory.valuation.reverse.manage', 'inventory.valuation.reverse.approve');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name = 'inventory.valuation.reverse.manage';

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name = 'inventory.valuation.reverse.approve';
"""


OUTBOX_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outbox_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
ON outbox_events(published_at, created_at, id);
"""


OUTBOX_DELIVERY_MIGRATION_SQL = """
ALTER TABLE outbox_events ADD COLUMN available_at TEXT;
ALTER TABLE outbox_events ADD COLUMN locked_at TEXT;
ALTER TABLE outbox_events ADD COLUMN locked_by TEXT;
ALTER TABLE outbox_events ADD COLUMN dead_lettered_at TEXT;

UPDATE outbox_events
SET available_at = created_at
WHERE available_at IS NULL;

DROP INDEX IF EXISTS idx_outbox_events_pending;
CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
ON outbox_events(published_at, dead_lettered_at, available_at, locked_at, created_at, id);
"""


PAYABLES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ap_suppliers (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    supplier_code TEXT NOT NULL,
    name TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    tax_identifier TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Active'
        CHECK (status IN ('Draft', 'Active', 'Suspended', 'Closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (workspace_id, supplier_code)
);

CREATE TABLE IF NOT EXISTS ap_purchase_orders (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    branch_id TEXT REFERENCES branches(id) ON DELETE RESTRICT,
    supplier_id TEXT NOT NULL REFERENCES ap_suppliers(id) ON DELETE RESTRICT,
    po_number TEXT NOT NULL,
    order_date TEXT NOT NULL,
    expected_date TEXT NOT NULL DEFAULT '',
    currency_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Submitted', 'Approved', 'Closed', 'Cancelled')),
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (workspace_id, po_number)
);

CREATE TABLE IF NOT EXISTS ap_purchase_order_lines (
    id TEXT PRIMARY KEY,
    purchase_order_id TEXT NOT NULL REFERENCES ap_purchase_orders(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    item_code TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    ordered_quantity TEXT NOT NULL,
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    created_at TEXT NOT NULL,
    UNIQUE (purchase_order_id, line_number)
);

CREATE TABLE IF NOT EXISTS ap_goods_receipts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    purchase_order_id TEXT NOT NULL REFERENCES ap_purchase_orders(id) ON DELETE RESTRICT,
    receipt_number TEXT NOT NULL,
    receipt_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Posted', 'Cancelled')),
    created_by TEXT NOT NULL DEFAULT '',
    posted_by TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, receipt_number)
);

CREATE TABLE IF NOT EXISTS ap_goods_receipt_lines (
    id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES ap_goods_receipts(id) ON DELETE CASCADE,
    purchase_order_line_id TEXT NOT NULL REFERENCES ap_purchase_order_lines(id) ON DELETE RESTRICT,
    received_quantity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (receipt_id, purchase_order_line_id)
);

CREATE TABLE IF NOT EXISTS ap_supplier_invoices (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    supplier_id TEXT NOT NULL REFERENCES ap_suppliers(id) ON DELETE RESTRICT,
    purchase_order_id TEXT REFERENCES ap_purchase_orders(id) ON DELETE RESTRICT,
    invoice_number TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL DEFAULT '',
    currency_code TEXT NOT NULL,
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    total_minor INTEGER NOT NULL CHECK (total_minor >= 0),
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Submitted', 'Matched', 'Exception', 'Approved', 'Paid', 'Rejected')),
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (workspace_id, supplier_id, invoice_number)
);

CREATE TABLE IF NOT EXISTS ap_supplier_invoice_lines (
    id TEXT PRIMARY KEY,
    supplier_invoice_id TEXT NOT NULL REFERENCES ap_supplier_invoices(id) ON DELETE CASCADE,
    purchase_order_line_id TEXT REFERENCES ap_purchase_order_lines(id) ON DELETE RESTRICT,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    description TEXT NOT NULL DEFAULT '',
    invoiced_quantity TEXT NOT NULL,
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    line_total_minor INTEGER NOT NULL CHECK (line_total_minor >= 0),
    created_at TEXT NOT NULL,
    UNIQUE (supplier_invoice_id, line_number)
);

CREATE TABLE IF NOT EXISTS ap_three_way_matches (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    supplier_invoice_id TEXT NOT NULL REFERENCES ap_supplier_invoices(id) ON DELETE CASCADE,
    purchase_order_id TEXT REFERENCES ap_purchase_orders(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('Passed', 'Exception')),
    quantity_variance TEXT NOT NULL DEFAULT '0',
    price_variance_minor INTEGER NOT NULL DEFAULT 0,
    total_variance_minor INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (supplier_invoice_id)
);

CREATE TABLE IF NOT EXISTS ap_idempotency_keys (
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_ap_purchase_orders_supplier
ON ap_purchase_orders(workspace_id, supplier_id, status, order_date, id);
CREATE INDEX IF NOT EXISTS idx_ap_supplier_invoices_supplier
ON ap_supplier_invoices(workspace_id, supplier_id, status, invoice_date, id);
CREATE INDEX IF NOT EXISTS idx_ap_receipt_lines_po_line
ON ap_goods_receipt_lines(purchase_order_line_id, receipt_id);
CREATE INDEX IF NOT EXISTS idx_ap_invoice_lines_po_line
ON ap_supplier_invoice_lines(purchase_order_line_id, supplier_invoice_id);

CREATE TRIGGER IF NOT EXISTS ap_supplier_invoice_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, legal_entity_id, supplier_id,
                 purchase_order_id, invoice_number, invoice_date, due_date,
                 currency_code, tax_minor, total_minor, created_by, created_at
ON ap_supplier_invoices
WHEN OLD.status IN ('Approved', 'Paid')
BEGIN
    SELECT RAISE(ABORT, 'approved supplier invoices are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ap_supplier_invoice_delete_blocked
BEFORE DELETE ON ap_supplier_invoices
WHEN OLD.status IN ('Approved', 'Paid')
BEGIN
    SELECT RAISE(ABORT, 'approved supplier invoices cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS ap_supplier_invoice_line_update_blocked
BEFORE UPDATE ON ap_supplier_invoice_lines
WHEN COALESCE((SELECT status FROM ap_supplier_invoices WHERE id = OLD.supplier_invoice_id), '') IN ('Approved', 'Paid')
BEGIN
    SELECT RAISE(ABORT, 'approved supplier invoice lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ap_supplier_invoice_line_delete_blocked
BEFORE DELETE ON ap_supplier_invoice_lines
WHEN COALESCE((SELECT status FROM ap_supplier_invoices WHERE id = OLD.supplier_invoice_id), '') IN ('Approved', 'Paid')
BEGIN
    SELECT RAISE(ABORT, 'approved supplier invoice lines cannot be deleted');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('payables.read', 'Read local supplier, purchase order, receipt, and supplier invoice records.'),
    ('payables.manage', 'Manage local supplier, purchase order, receipt, and supplier invoice drafts.'),
    ('payables.approve', 'Approve matched local supplier invoices.'),
    ('payables.match', 'Run deterministic three-way supplier invoice matching.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('payables.read', 'payables.manage', 'payables.approve', 'payables.match');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name IN ('payables.read', 'payables.manage', 'payables.match');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name IN ('payables.read', 'payables.approve', 'payables.match');
"""


RECEIVABLES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ar_customers (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    customer_code TEXT NOT NULL,
    name TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    tax_identifier TEXT NOT NULL DEFAULT '',
    payment_terms_days INTEGER NOT NULL DEFAULT 0 CHECK (payment_terms_days >= 0),
    credit_limit_minor INTEGER NOT NULL DEFAULT 0 CHECK (credit_limit_minor >= 0),
    credit_hold INTEGER NOT NULL DEFAULT 0 CHECK (credit_hold IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'Active'
        CHECK (status IN ('Draft', 'Active', 'Suspended', 'Closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (workspace_id, customer_code)
);

CREATE TABLE IF NOT EXISTS ar_invoices (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    customer_id TEXT NOT NULL REFERENCES ar_customers(id) ON DELETE RESTRICT,
    invoice_number TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    subtotal_minor INTEGER NOT NULL CHECK (subtotal_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    total_minor INTEGER NOT NULL CHECK (total_minor >= 0),
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Submitted', 'Approved', 'PartiallyPaid', 'Paid', 'Cancelled')),
    created_by TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    credit_override_reason TEXT NOT NULL DEFAULT '',
    cancelled_by TEXT NOT NULL DEFAULT '',
    cancelled_at TEXT,
    cancel_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (workspace_id, customer_id, invoice_number),
    CHECK (total_minor = subtotal_minor + tax_minor)
);

CREATE TABLE IF NOT EXISTS ar_invoice_lines (
    id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES ar_invoices(id) ON DELETE CASCADE,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    description TEXT NOT NULL DEFAULT '',
    quantity TEXT NOT NULL,
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    line_total_minor INTEGER NOT NULL CHECK (line_total_minor >= 0),
    created_at TEXT NOT NULL,
    UNIQUE (invoice_id, line_number)
);

CREATE TABLE IF NOT EXISTS ar_receipts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE RESTRICT,
    legal_entity_id TEXT REFERENCES legal_entities(id) ON DELETE RESTRICT,
    customer_id TEXT NOT NULL REFERENCES ar_customers(id) ON DELETE RESTRICT,
    receipt_number TEXT NOT NULL,
    receipt_date TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    status TEXT NOT NULL DEFAULT 'Posted'
        CHECK (status IN ('Posted', 'Cancelled')),
    created_by TEXT NOT NULL DEFAULT '',
    posted_by TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (workspace_id, receipt_number)
);

CREATE TABLE IF NOT EXISTS ar_receipt_allocations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    receipt_id TEXT NOT NULL REFERENCES ar_receipts(id) ON DELETE RESTRICT,
    invoice_id TEXT NOT NULL REFERENCES ar_invoices(id) ON DELETE RESTRICT,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    created_at TEXT NOT NULL,
    UNIQUE (receipt_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS ar_idempotency_keys (
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_ar_invoices_customer_status
ON ar_invoices(workspace_id, customer_id, status, due_date, invoice_date, id);
CREATE INDEX IF NOT EXISTS idx_ar_receipts_customer_date
ON ar_receipts(workspace_id, customer_id, receipt_date, id);
CREATE INDEX IF NOT EXISTS idx_ar_allocations_invoice
ON ar_receipt_allocations(workspace_id, invoice_id, created_at, id);

CREATE TRIGGER IF NOT EXISTS ar_invoice_header_immutable
BEFORE UPDATE OF workspace_id, organization_id, legal_entity_id, customer_id,
                 invoice_number, invoice_date, due_date, currency_code,
                 subtotal_minor, tax_minor, total_minor, created_by, credit_override_reason, created_at
ON ar_invoices
WHEN OLD.status IN ('Approved', 'PartiallyPaid', 'Paid', 'Cancelled')
BEGIN
    SELECT RAISE(ABORT, 'approved receivable invoices are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ar_invoice_delete_blocked
BEFORE DELETE ON ar_invoices
WHEN OLD.status IN ('Approved', 'PartiallyPaid', 'Paid', 'Cancelled')
BEGIN
    SELECT RAISE(ABORT, 'approved receivable invoices cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS ar_invoice_line_update_blocked
BEFORE UPDATE ON ar_invoice_lines
WHEN COALESCE((SELECT status FROM ar_invoices WHERE id = OLD.invoice_id), '') IN
    ('Approved', 'PartiallyPaid', 'Paid', 'Cancelled')
BEGIN
    SELECT RAISE(ABORT, 'approved receivable invoice lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS ar_invoice_line_delete_blocked
BEFORE DELETE ON ar_invoice_lines
WHEN COALESCE((SELECT status FROM ar_invoices WHERE id = OLD.invoice_id), '') IN
    ('Approved', 'PartiallyPaid', 'Paid', 'Cancelled')
BEGIN
    SELECT RAISE(ABORT, 'approved receivable invoice lines cannot be deleted');
END;

INSERT OR IGNORE INTO permissions (name, description) VALUES
    ('receivables.read', 'Read local customer, invoice, receipt, allocation, credit, and aging records.'),
    ('receivables.manage', 'Manage local customer, invoice, receipt, and allocation drafts.'),
    ('receivables.approve', 'Approve local receivable invoices after credit-control checks.'),
    ('receivables.credit_override', 'Override a customer credit hold or credit-limit breach with a reason.');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name IN ('admin', 'controller')
  AND permissions.name IN ('receivables.read', 'receivables.manage', 'receivables.approve', 'receivables.credit_override');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'preparer'
  AND permissions.name IN ('receivables.read', 'receivables.manage');

INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles
JOIN permissions
WHERE roles.name = 'reviewer'
  AND permissions.name IN ('receivables.read', 'receivables.approve');
"""

DURABLE_JOBS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS durable_jobs (
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    version INTEGER NOT NULL CHECK (version >= 1),
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'paused', 'retrying', 'failed', 'completed', 'cancelled')
    ),
    idempotency_scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    config_digest TEXT NOT NULL CHECK (length(config_digest) = 64),
    worker_version TEXT NOT NULL,
    completed_units INTEGER NOT NULL CHECK (completed_units >= 0),
    total_units INTEGER NOT NULL CHECK (total_units >= 0 AND completed_units <= total_units),
    checkpoint_digest TEXT NOT NULL DEFAULT '' CHECK (
        checkpoint_digest = '' OR length(checkpoint_digest) = 64
    ),
    retry_count INTEGER NOT NULL CHECK (retry_count >= 0),
    retry_ceiling INTEGER NOT NULL CHECK (retry_ceiling >= 0 AND retry_count <= retry_ceiling),
    safe_error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    output_manifest_schema_version INTEGER,
    output_manifest_digest TEXT NOT NULL DEFAULT '',
    output_manifest_reference TEXT NOT NULL DEFAULT '',
    UNIQUE (tenant_id, idempotency_scope, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_durable_jobs_scope_status
ON durable_jobs (tenant_id, workspace_id, status, created_at, id);

CREATE TABLE IF NOT EXISTS durable_job_transitions (
    job_id TEXT NOT NULL REFERENCES durable_jobs(id) ON DELETE RESTRICT,
    job_version INTEGER NOT NULL CHECK (job_version >= 1),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL CHECK (
        to_status IN ('queued', 'running', 'paused', 'retrying', 'failed', 'completed', 'cancelled')
    ),
    actor_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    PRIMARY KEY (job_id, job_version)
);

CREATE TRIGGER IF NOT EXISTS durable_job_transitions_immutable_update
BEFORE UPDATE ON durable_job_transitions
BEGIN
    SELECT RAISE(ABORT, 'durable job transitions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS durable_job_transitions_immutable_delete
BEFORE DELETE ON durable_job_transitions
BEGIN
    SELECT RAISE(ABORT, 'durable job transitions are immutable');
END;
"""

DURABLE_JOB_LEASES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS durable_job_leases (
    job_id TEXT PRIMARY KEY REFERENCES durable_jobs(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_durable_job_leases_expiry
ON durable_job_leases (tenant_id, expires_at, job_id);

CREATE TABLE IF NOT EXISTS durable_job_lease_events (
    job_id TEXT NOT NULL REFERENCES durable_jobs(id) ON DELETE RESTRICT,
    event_sequence INTEGER NOT NULL CHECK (event_sequence >= 1),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    action TEXT NOT NULL CHECK (action IN ('claimed', 'taken_over', 'renewed', 'released')),
    owner_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (job_id, event_sequence)
);

CREATE TRIGGER IF NOT EXISTS durable_job_lease_events_immutable_update
BEFORE UPDATE ON durable_job_lease_events
BEGIN
    SELECT RAISE(ABORT, 'durable job lease events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS durable_job_lease_events_immutable_delete
BEFORE DELETE ON durable_job_lease_events
BEGIN
    SELECT RAISE(ABORT, 'durable job lease events are immutable');
END;
"""

DURABLE_JOB_EFFECTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS durable_job_partition_effects (
    job_id TEXT NOT NULL REFERENCES durable_jobs(id) ON DELETE RESTRICT,
    partition_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    completed_units INTEGER NOT NULL CHECK (completed_units >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    output_digest TEXT NOT NULL CHECK (length(output_digest) = 64),
    effect_reference TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    job_version INTEGER NOT NULL CHECK (job_version >= 2),
    PRIMARY KEY (job_id, partition_key),
    UNIQUE (job_id, ordinal),
    UNIQUE (job_id, job_version)
);

CREATE TRIGGER IF NOT EXISTS durable_job_partition_effects_immutable_update
BEFORE UPDATE ON durable_job_partition_effects
BEGIN
    SELECT RAISE(ABORT, 'durable job partition effects are immutable');
END;

CREATE TRIGGER IF NOT EXISTS durable_job_partition_effects_immutable_delete
BEFORE DELETE ON durable_job_partition_effects
BEGIN
    SELECT RAISE(ABORT, 'durable job partition effects are immutable');
END;
"""

IDEMPOTENCY_RECORDS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS idempotency_records (
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    tenant_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (length(scope) BETWEEN 1 AND 160),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    owner_token_digest TEXT NOT NULL CHECK (length(owner_token_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('pending','completed')),
    response_body TEXT NOT NULL DEFAULT '',
    response_digest TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL CHECK (expires_at > created_at),
    completed_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, scope, idempotency_key),
    CHECK (
      (status='pending' AND length(response_body)=0 AND response_digest='' AND completed_at='') OR
      (status='completed' AND length(response_digest)=64 AND completed_at<>'')
    )
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expiry
ON idempotency_records (expires_at, tenant_id);
"""


CONSOLIDATION_CLOSE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS consolidation_close_periods (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    group_code TEXT NOT NULL,
    period_name TEXT NOT NULL,
    reporting_currency TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    period_start_date TEXT NOT NULL,
    period_end_date TEXT NOT NULL,
    reporting_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Locked','Reopened')),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    locked_by TEXT NOT NULL DEFAULT '',
    locked_at TEXT NOT NULL DEFAULT '',
    lock_reason TEXT NOT NULL DEFAULT '',
    reopened_by TEXT NOT NULL DEFAULT '',
    reopened_at TEXT NOT NULL DEFAULT '',
    reopen_reason TEXT NOT NULL DEFAULT '',
    UNIQUE (workspace_id, group_code, period_name),
    CHECK (period_start_date <= reporting_date AND reporting_date <= period_end_date),
    CHECK (
      (status='Open' AND locked_by='' AND locked_at='' AND lock_reason=''
                     AND reopened_by='' AND reopened_at='' AND reopen_reason='') OR
      (status='Locked' AND locked_by<>'' AND locked_at<>'' AND lock_reason<>'') OR
      (status='Reopened' AND locked_by<>'' AND locked_at<>'' AND lock_reason<>''
                         AND reopened_by<>'' AND reopened_at<>'' AND reopen_reason<>'')
    )
);

CREATE TABLE IF NOT EXISTS consolidation_runs (
    id TEXT PRIMARY KEY,
    period_id TEXT NOT NULL REFERENCES consolidation_close_periods(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    run_number TEXT NOT NULL,
    worksheet_id TEXT NOT NULL,
    worksheet_request_digest TEXT NOT NULL CHECK (length(worksheet_request_digest)=64),
    worksheet_result_digest TEXT NOT NULL CHECK (length(worksheet_result_digest)=64),
    translation_result_digest TEXT NOT NULL CHECK (length(translation_result_digest)=64),
    worksheet_payload TEXT NOT NULL,
    worksheet_payload_digest TEXT NOT NULL CHECK (length(worksheet_payload_digest)=64),
    reporting_currency TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    journal_line_count INTEGER NOT NULL CHECK (journal_line_count BETWEEN 2 AND 10000),
    journal_digest TEXT NOT NULL CHECK (length(journal_digest)=64),
    status TEXT NOT NULL DEFAULT 'Prepared'
        CHECK (status IN ('Prepared','Approved','Posted','ReversalPrepared','Reversed')),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    prepared_by TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT NOT NULL DEFAULT '',
    approval_reason TEXT NOT NULL DEFAULT '',
    posted_by TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    posting_reason TEXT NOT NULL DEFAULT '',
    reversal_requested_by TEXT NOT NULL DEFAULT '',
    reversal_requested_at TEXT NOT NULL DEFAULT '',
    reversal_request_reason TEXT NOT NULL DEFAULT '',
    reversed_by TEXT NOT NULL DEFAULT '',
    reversed_at TEXT NOT NULL DEFAULT '',
    reversal_reason TEXT NOT NULL DEFAULT '',
    UNIQUE (period_id, run_number),
    UNIQUE (workspace_id, worksheet_result_digest),
    CHECK (prepared_by<>'' AND prepared_at<>''),
    CHECK (
      (status='Prepared' AND approved_by='' AND approved_at='' AND approval_reason=''
                         AND posted_by='' AND posted_at='' AND posting_reason=''
                         AND reversal_requested_by='' AND reversal_requested_at=''
                         AND reversal_request_reason='' AND reversed_by='' AND reversed_at=''
                         AND reversal_reason='') OR
      (status='Approved' AND approved_by<>'' AND approved_at<>'' AND approval_reason<>''
                         AND posted_by='' AND posted_at='' AND posting_reason=''
                         AND reversal_requested_by='' AND reversal_requested_at=''
                         AND reversal_request_reason='' AND reversed_by='' AND reversed_at=''
                         AND reversal_reason='') OR
      (status='Posted' AND approved_by<>'' AND approved_at<>'' AND approval_reason<>''
                       AND posted_by<>'' AND posted_at<>'' AND posting_reason<>''
                       AND reversal_requested_by='' AND reversal_requested_at=''
                       AND reversal_request_reason='' AND reversed_by='' AND reversed_at=''
                       AND reversal_reason='') OR
      (status='ReversalPrepared' AND approved_by<>'' AND approved_at<>'' AND approval_reason<>''
                                 AND posted_by<>'' AND posted_at<>'' AND posting_reason<>''
                                 AND reversal_requested_by<>'' AND reversal_requested_at<>''
                                 AND reversal_request_reason<>'' AND reversed_by='' AND reversed_at=''
                                 AND reversal_reason='') OR
      (status='Reversed' AND approved_by<>'' AND approved_at<>'' AND approval_reason<>''
                         AND posted_by<>'' AND posted_at<>'' AND posting_reason<>''
                         AND reversal_requested_by<>'' AND reversal_requested_at<>''
                         AND reversal_request_reason<>'' AND reversed_by<>'' AND reversed_at<>''
                         AND reversal_reason<>'')
    )
);

CREATE TABLE IF NOT EXISTS consolidation_period_events (
    id TEXT PRIMARY KEY,
    period_id TEXT NOT NULL REFERENCES consolidation_close_periods(id) ON DELETE RESTRICT,
    event_sequence INTEGER NOT NULL CHECK (event_sequence >= 2),
    from_status TEXT NOT NULL CHECK (from_status IN ('Open','Locked','Reopened')),
    to_status TEXT NOT NULL CHECK (to_status IN ('Locked','Reopened')),
    actor_label TEXT NOT NULL CHECK (actor_label <> ''),
    occurred_at TEXT NOT NULL CHECK (occurred_at <> ''),
    reason TEXT NOT NULL CHECK (reason <> ''),
    UNIQUE (period_id, event_sequence),
    CHECK ((from_status IN ('Open','Reopened') AND to_status='Locked') OR
           (from_status='Locked' AND to_status='Reopened'))
);

CREATE TABLE IF NOT EXISTS consolidation_run_lines (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES consolidation_runs(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    elimination_id TEXT NOT NULL,
    source_line_id TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    group_account_code TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('Asset','Liability','Equity','Income','Expense')),
    amount_decimal TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor <> 0),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    source_reference TEXT NOT NULL,
    source_digest TEXT NOT NULL CHECK (length(source_digest)=64),
    UNIQUE (run_id, ordinal),
    UNIQUE (run_id, source_line_id)
);

CREATE TABLE IF NOT EXISTS consolidation_effects (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES consolidation_runs(id) ON DELETE RESTRICT,
    effect_type TEXT NOT NULL CHECK (effect_type IN ('Posting','Reversal')),
    source_effect_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Building' CHECK (status IN ('Building','Committed')),
    line_count INTEGER NOT NULL CHECK (line_count BETWEEN 2 AND 10000),
    effect_digest TEXT NOT NULL CHECK (length(effect_digest)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, effect_type),
    CHECK ((effect_type='Posting' AND source_effect_id='') OR
           (effect_type='Reversal' AND source_effect_id<>''))
);

CREATE TABLE IF NOT EXISTS consolidation_effect_lines (
    id TEXT PRIMARY KEY,
    effect_id TEXT NOT NULL REFERENCES consolidation_effects(id) ON DELETE RESTRICT,
    run_line_id TEXT NOT NULL REFERENCES consolidation_run_lines(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    amount_decimal TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor <> 0),
    currency_code TEXT NOT NULL REFERENCES currencies(code) ON DELETE RESTRICT,
    UNIQUE (effect_id, ordinal),
    UNIQUE (effect_id, run_line_id)
);

CREATE INDEX IF NOT EXISTS idx_consolidation_periods_scope
ON consolidation_close_periods(workspace_id, group_code, period_name, status);
CREATE INDEX IF NOT EXISTS idx_consolidation_runs_scope
ON consolidation_runs(workspace_id, period_id, status, run_number);
CREATE INDEX IF NOT EXISTS idx_consolidation_period_events_period
ON consolidation_period_events(period_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_consolidation_run_lines_run
ON consolidation_run_lines(run_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_consolidation_effects_run
ON consolidation_effects(run_id, effect_type, status);

CREATE TRIGGER IF NOT EXISTS consolidation_periods_guard_update
BEFORE UPDATE ON consolidation_close_periods
BEGIN
    SELECT CASE WHEN NEW.id<>OLD.id OR NEW.workspace_id<>OLD.workspace_id
      OR NEW.group_code<>OLD.group_code OR NEW.period_name<>OLD.period_name
      OR NEW.reporting_currency<>OLD.reporting_currency
      OR NEW.period_start_date<>OLD.period_start_date OR NEW.period_end_date<>OLD.period_end_date
      OR NEW.reporting_date<>OLD.reporting_date OR NEW.created_by<>OLD.created_by
      OR NEW.created_at<>OLD.created_at
      THEN RAISE(ABORT, 'consolidation period identity is immutable') END;
    SELECT CASE WHEN NEW.row_version<>OLD.row_version+1
      THEN RAISE(ABORT, 'consolidation period version must advance by one') END;
    SELECT CASE WHEN NOT ((OLD.status IN ('Open','Reopened') AND NEW.status='Locked')
                       OR (OLD.status='Locked' AND NEW.status='Reopened'))
      THEN RAISE(ABORT, 'invalid consolidation period transition') END;
    SELECT CASE WHEN NOT EXISTS (
      SELECT 1 FROM consolidation_period_events events
      WHERE events.period_id=OLD.id AND events.event_sequence=NEW.row_version
        AND events.from_status=OLD.status AND events.to_status=NEW.status
        AND events.actor_label=CASE WHEN NEW.status='Locked' THEN NEW.locked_by ELSE NEW.reopened_by END
        AND events.occurred_at=CASE WHEN NEW.status='Locked' THEN NEW.locked_at ELSE NEW.reopened_at END
        AND events.reason=CASE WHEN NEW.status='Locked' THEN NEW.lock_reason ELSE NEW.reopen_reason END
    ) THEN RAISE(ABORT, 'consolidation period transition requires its immutable event') END;
    SELECT CASE WHEN NEW.status='Locked' AND
      (NEW.locked_by='' OR NEW.locked_at='' OR NEW.lock_reason=''
       OR NEW.locked_at<CASE WHEN OLD.status='Reopened' THEN OLD.reopened_at ELSE OLD.created_at END)
      THEN RAISE(ABORT, 'locking a consolidation period requires actor timestamp and reason') END;
    SELECT CASE WHEN NEW.status='Locked' AND NOT EXISTS (
      SELECT 1 FROM consolidation_runs
      WHERE period_id=OLD.id AND prepared_at<=NEW.locked_at
    ) THEN RAISE(ABORT, 'consolidation period requires at least one governed run before lock') END;
    SELECT CASE WHEN NEW.status='Locked' AND EXISTS (
      SELECT 1 FROM consolidation_runs
      WHERE period_id=OLD.id AND prepared_at<=NEW.locked_at AND status NOT IN ('Posted','Reversed')
    ) THEN RAISE(ABORT, 'consolidation period has unfinished runs') END;
    SELECT CASE WHEN NEW.status='Reopened' AND
      (NEW.reopened_by='' OR NEW.reopened_at='' OR NEW.reopen_reason=''
       OR lower(trim(NEW.reopened_by))=lower(trim(OLD.locked_by))
       OR NEW.reopened_at<OLD.locked_at
       OR NEW.locked_by<>OLD.locked_by OR NEW.locked_at<>OLD.locked_at
       OR NEW.lock_reason<>OLD.lock_reason)
      THEN RAISE(ABORT, 'reopening a consolidation period requires an independent actor timestamp and reason') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_periods_immutable_delete
BEFORE DELETE ON consolidation_close_periods
BEGIN
    SELECT RAISE(ABORT, 'consolidation periods are immutable lifecycle records');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_period_events_guard_insert
BEFORE INSERT ON consolidation_period_events
BEGIN
    SELECT CASE WHEN NOT EXISTS (
      SELECT 1 FROM consolidation_close_periods periods
      WHERE periods.id=NEW.period_id AND periods.row_version=NEW.event_sequence-1
        AND periods.status=NEW.from_status
        AND ((NEW.from_status IN ('Open','Reopened') AND NEW.to_status='Locked'
              AND NEW.occurred_at>=CASE WHEN NEW.from_status='Reopened'
                                        THEN periods.reopened_at ELSE periods.created_at END)
          OR (NEW.from_status='Locked' AND NEW.to_status='Reopened'
              AND lower(trim(NEW.actor_label))<>lower(trim(periods.locked_by))
              AND NEW.occurred_at>=periods.locked_at))
    ) THEN RAISE(ABORT, 'consolidation period event does not match current governed state') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_period_events_immutable_update
BEFORE UPDATE ON consolidation_period_events
BEGIN
    SELECT RAISE(ABORT, 'consolidation period events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_period_events_immutable_delete
BEFORE DELETE ON consolidation_period_events
BEGIN
    SELECT RAISE(ABORT, 'consolidation period events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_runs_guard_insert
BEFORE INSERT ON consolidation_runs
BEGIN
    SELECT CASE WHEN NEW.status<>'Prepared' OR NEW.row_version<>1
      THEN RAISE(ABORT, 'consolidation runs must begin at Prepared version one') END;
    SELECT CASE WHEN NOT EXISTS (
      SELECT 1 FROM consolidation_close_periods periods
      WHERE periods.id=NEW.period_id AND periods.workspace_id=NEW.workspace_id
        AND periods.reporting_currency=NEW.reporting_currency
        AND periods.status IN ('Open','Reopened')
    ) THEN RAISE(ABORT, 'consolidation run scope must match an open governed period') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_runs_guard_update
BEFORE UPDATE ON consolidation_runs
BEGIN
    SELECT CASE WHEN NEW.id<>OLD.id OR NEW.period_id<>OLD.period_id
      OR NEW.workspace_id<>OLD.workspace_id OR NEW.run_number<>OLD.run_number
      OR NEW.worksheet_id<>OLD.worksheet_id
      OR NEW.worksheet_request_digest<>OLD.worksheet_request_digest
      OR NEW.worksheet_result_digest<>OLD.worksheet_result_digest
      OR NEW.translation_result_digest<>OLD.translation_result_digest
      OR NEW.worksheet_payload<>OLD.worksheet_payload
      OR NEW.worksheet_payload_digest<>OLD.worksheet_payload_digest
      OR NEW.reporting_currency<>OLD.reporting_currency
      OR NEW.journal_line_count<>OLD.journal_line_count OR NEW.journal_digest<>OLD.journal_digest
      OR NEW.prepared_by<>OLD.prepared_by OR NEW.prepared_at<>OLD.prepared_at
      THEN RAISE(ABORT, 'consolidation run source and preparation state are immutable') END;
    SELECT CASE WHEN NEW.row_version<>OLD.row_version+1
      THEN RAISE(ABORT, 'consolidation run version must advance by one') END;
    SELECT CASE WHEN NOT ((OLD.status='Prepared' AND NEW.status='Approved')
                       OR (OLD.status='Approved' AND NEW.status='Posted')
                       OR (OLD.status='Posted' AND NEW.status='ReversalPrepared')
                       OR (OLD.status='ReversalPrepared' AND NEW.status='Reversed'))
      THEN RAISE(ABORT, 'invalid consolidation run transition') END;
    SELECT CASE WHEN NEW.status='Approved' AND
      (NEW.approved_by='' OR NEW.approved_at='' OR NEW.approval_reason=''
       OR lower(trim(NEW.approved_by))=lower(trim(OLD.prepared_by))
       OR NEW.approved_at<OLD.prepared_at)
      THEN RAISE(ABORT, 'consolidation approval requires an independent actor timestamp and reason') END;
    SELECT CASE WHEN NEW.status='Approved' AND
      ((SELECT COUNT(*) FROM consolidation_run_lines WHERE run_id=OLD.id)<>OLD.journal_line_count
       OR (SELECT COALESCE(SUM(amount_minor),0) FROM consolidation_run_lines WHERE run_id=OLD.id)<>0)
      THEN RAISE(ABORT, 'consolidation approval requires the complete balanced journal') END;
    SELECT CASE WHEN NEW.status='Posted' AND
      (NEW.posted_by='' OR NEW.posted_at='' OR NEW.posting_reason=''
       OR lower(trim(NEW.posted_by)) IN (lower(trim(OLD.prepared_by)),lower(trim(OLD.approved_by)))
       OR NEW.posted_at<OLD.approved_at)
      THEN RAISE(ABORT, 'consolidation posting requires an independent actor timestamp and reason') END;
    SELECT CASE WHEN NEW.status='Posted' AND NOT EXISTS (
      SELECT 1 FROM consolidation_effects
      WHERE run_id=OLD.id AND effect_type='Posting' AND status='Committed'
    ) THEN RAISE(ABORT, 'consolidation posting requires a committed balanced effect') END;
    SELECT CASE WHEN NEW.status='ReversalPrepared' AND
      (NEW.reversal_requested_by='' OR NEW.reversal_requested_at=''
       OR NEW.reversal_request_reason='' OR NEW.reversal_requested_at<OLD.posted_at)
      THEN RAISE(ABORT, 'consolidation reversal preparation requires actor timestamp and reason') END;
    SELECT CASE WHEN NEW.status='Reversed' AND
      (NEW.reversed_by='' OR NEW.reversed_at='' OR NEW.reversal_reason=''
       OR lower(trim(NEW.reversed_by)) IN
          (lower(trim(OLD.reversal_requested_by)),lower(trim(OLD.posted_by)))
       OR NEW.reversed_at<OLD.reversal_requested_at)
      THEN RAISE(ABORT, 'consolidation reversal requires an independent approver timestamp and reason') END;
    SELECT CASE WHEN NEW.status='Reversed' AND NOT EXISTS (
      SELECT 1 FROM consolidation_effects
      WHERE run_id=OLD.id AND effect_type='Reversal' AND status='Committed'
    ) THEN RAISE(ABORT, 'consolidation reversal requires a committed compensating effect') END;
    SELECT CASE WHEN OLD.status IN ('Approved','Posted','ReversalPrepared') AND
      (NEW.approved_by<>OLD.approved_by OR NEW.approved_at<>OLD.approved_at
       OR NEW.approval_reason<>OLD.approval_reason)
      THEN RAISE(ABORT, 'consolidation approval history is immutable') END;
    SELECT CASE WHEN OLD.status IN ('Posted','ReversalPrepared') AND
      (NEW.posted_by<>OLD.posted_by OR NEW.posted_at<>OLD.posted_at
       OR NEW.posting_reason<>OLD.posting_reason)
      THEN RAISE(ABORT, 'consolidation posting history is immutable') END;
    SELECT CASE WHEN OLD.status='ReversalPrepared' AND
      (NEW.reversal_requested_by<>OLD.reversal_requested_by
       OR NEW.reversal_requested_at<>OLD.reversal_requested_at
       OR NEW.reversal_request_reason<>OLD.reversal_request_reason)
      THEN RAISE(ABORT, 'consolidation reversal-request history is immutable') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_runs_immutable_delete
BEFORE DELETE ON consolidation_runs
BEGIN
    SELECT RAISE(ABORT, 'consolidation runs cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_run_lines_guard_insert
BEFORE INSERT ON consolidation_run_lines
BEGIN
    SELECT CASE WHEN NOT EXISTS (
      SELECT 1 FROM consolidation_runs
      WHERE id=NEW.run_id AND status='Prepared' AND reporting_currency=NEW.currency_code
    ) THEN RAISE(ABORT, 'consolidation lines require a matching Prepared run') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_run_lines_immutable_update
BEFORE UPDATE ON consolidation_run_lines
BEGIN
    SELECT RAISE(ABORT, 'consolidation run lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_run_lines_immutable_delete
BEFORE DELETE ON consolidation_run_lines
BEGIN
    SELECT RAISE(ABORT, 'consolidation run lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_effects_guard_insert
BEFORE INSERT ON consolidation_effects
BEGIN
    SELECT CASE WHEN NEW.status<>'Building'
      THEN RAISE(ABORT, 'consolidation effects must begin in Building state') END;
    SELECT CASE WHEN NOT EXISTS (
      SELECT 1 FROM consolidation_runs runs
      WHERE runs.id=NEW.run_id
        AND ((NEW.effect_type='Posting' AND runs.status='Approved' AND NEW.source_effect_id='')
          OR (NEW.effect_type='Reversal' AND runs.status='ReversalPrepared'
              AND EXISTS (
                SELECT 1 FROM consolidation_effects source
                WHERE source.id=NEW.source_effect_id AND source.run_id=NEW.run_id
                  AND source.effect_type='Posting' AND source.status='Committed'
              )))
    ) THEN RAISE(ABORT, 'consolidation effect does not match the governed run state') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_effects_guard_update
BEFORE UPDATE ON consolidation_effects
BEGIN
    SELECT CASE WHEN OLD.status<>'Building' OR NEW.status<>'Committed'
      OR NEW.id<>OLD.id OR NEW.run_id<>OLD.run_id OR NEW.effect_type<>OLD.effect_type
      OR NEW.source_effect_id<>OLD.source_effect_id OR NEW.line_count<>OLD.line_count
      OR NEW.effect_digest<>OLD.effect_digest OR NEW.created_by<>OLD.created_by
      OR NEW.created_at<>OLD.created_at
      THEN RAISE(ABORT, 'invalid consolidation effect transition') END;
    SELECT CASE WHEN
      (SELECT COUNT(*) FROM consolidation_effect_lines WHERE effect_id=OLD.id)<>OLD.line_count
      OR (SELECT COALESCE(SUM(amount_minor),0) FROM consolidation_effect_lines WHERE effect_id=OLD.id)<>0
      THEN RAISE(ABORT, 'consolidation effect must be complete and balanced') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_effects_immutable_delete
BEFORE DELETE ON consolidation_effects
BEGIN
    SELECT RAISE(ABORT, 'consolidation effects cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_effect_lines_guard_insert
BEFORE INSERT ON consolidation_effect_lines
BEGIN
    SELECT CASE WHEN NOT EXISTS (
      SELECT 1 FROM consolidation_effects effects
      JOIN consolidation_runs runs ON runs.id=effects.run_id
      JOIN consolidation_run_lines lines ON lines.id=NEW.run_line_id AND lines.run_id=runs.id
      WHERE effects.id=NEW.effect_id AND effects.status='Building'
        AND lines.currency_code=NEW.currency_code
        AND lines.ordinal=NEW.ordinal
        AND ((effects.effect_type='Posting' AND NEW.amount_minor=lines.amount_minor)
          OR (effects.effect_type='Reversal' AND NEW.amount_minor=-lines.amount_minor))
    ) THEN RAISE(ABORT, 'consolidation effect line does not reproduce its governed run line') END;
END;

CREATE TRIGGER IF NOT EXISTS consolidation_effect_lines_immutable_update
BEFORE UPDATE ON consolidation_effect_lines
BEGIN
    SELECT RAISE(ABORT, 'consolidation effect lines are immutable');
END;

CREATE TRIGGER IF NOT EXISTS consolidation_effect_lines_immutable_delete
BEFORE DELETE ON consolidation_effect_lines
BEGIN
    SELECT RAISE(ABORT, 'consolidation effect lines are immutable');
END;
"""


ACCOUNT_RECONCILIATION_MONEY_MIGRATION_SQL = """
-- Add canonical Decimal text alongside legacy REAL compatibility columns. New
-- account-reconciliation service writes and reads the text columns; the legacy
-- columns remain temporarily for additive upgrade compatibility.
ALTER TABLE account_reconciliation_templates
    ADD COLUMN materiality_threshold_decimal TEXT NOT NULL DEFAULT '0';
ALTER TABLE trial_balance_rows
    ADD COLUMN balance_decimal TEXT NOT NULL DEFAULT '0';
ALTER TABLE account_reconciliation_records
    ADD COLUMN balance_decimal TEXT NOT NULL DEFAULT '0';
ALTER TABLE account_reconciliation_records
    ADD COLUMN materiality_threshold_decimal TEXT NOT NULL DEFAULT '0';
ALTER TABLE account_reconciliation_records
    ADD COLUMN currency_code TEXT NOT NULL DEFAULT 'LOCAL';
ALTER TABLE account_reconciliation_items
    ADD COLUMN amount_decimal TEXT NOT NULL DEFAULT '0';

-- Existing REAL values are copied with SQLite's shortest round-trippable text
-- representation. They are legacy compatibility data and are revalidated by the
-- service before any subsequent financial workflow uses them.
UPDATE account_reconciliation_templates
SET materiality_threshold_decimal = CASE
    WHEN materiality_threshold = 0 THEN '0'
    ELSE printf('%.17g', materiality_threshold)
END;
UPDATE trial_balance_rows
SET balance_decimal = CASE
    WHEN balance = 0 THEN '0'
    ELSE printf('%.17g', balance)
END;
UPDATE account_reconciliation_records
SET balance_decimal = CASE
        WHEN balance = 0 THEN '0'
        ELSE printf('%.17g', balance)
    END,
    materiality_threshold_decimal = CASE
        WHEN materiality_threshold = 0 THEN '0'
        ELSE printf('%.17g', materiality_threshold)
    END;
UPDATE account_reconciliation_items
SET amount_decimal = CASE
    WHEN amount = 0 THEN '0'
    ELSE printf('%.17g', amount)
END;

CREATE INDEX IF NOT EXISTS idx_trial_balance_rows_decimal_currency
ON trial_balance_rows(workspace_id, period_name, entity_code, currency, account_code);
CREATE INDEX IF NOT EXISTS idx_account_reconciliation_records_currency
ON account_reconciliation_records(workspace_id, period_name, currency_code, account_code);
"""


JOURNALS_INTERCOMPANY_MONEY_MIGRATION_SQL = """
-- Canonical Decimal text for legacy journal and intercompany amounts. The
-- existing REAL-compatible columns remain temporarily for export compatibility.
ALTER TABLE journal_entries
    ADD COLUMN amount_decimal TEXT NOT NULL DEFAULT '0';
ALTER TABLE intercompany_transactions
    ADD COLUMN amount_decimal TEXT NOT NULL DEFAULT '0';
ALTER TABLE intercompany_cases
    ADD COLUMN imbalance_amount_decimal TEXT NOT NULL DEFAULT '0';

UPDATE journal_entries
SET amount_decimal = CASE
    WHEN amount = 0 THEN '0'
    ELSE printf('%.17g', amount)
END;
UPDATE intercompany_transactions
SET amount_decimal = CASE
    WHEN amount = 0 THEN '0'
    ELSE printf('%.17g', amount)
END;
UPDATE intercompany_cases
SET imbalance_amount_decimal = CASE
    WHEN imbalance_amount = 0 THEN '0'
    ELSE printf('%.17g', imbalance_amount)
END;

CREATE INDEX IF NOT EXISTS idx_journal_entries_decimal_currency
ON journal_entries(workspace_id, period_name, currency, account_code);
CREATE INDEX IF NOT EXISTS idx_intercompany_transactions_decimal_currency
ON intercompany_transactions(workspace_id, period_name, currency, reference);
CREATE INDEX IF NOT EXISTS idx_intercompany_cases_decimal_currency
ON intercompany_cases(workspace_id, period_name, currency, reference);
"""


MATCHING_MONEY_MIGRATION_SQL = """
-- Canonical Decimal text for persisted match differences. The legacy REAL
-- column remains temporarily for additive upgrade and export compatibility.
ALTER TABLE match_results
    ADD COLUMN amount_difference_decimal TEXT NOT NULL DEFAULT '0';

UPDATE match_results
SET amount_difference_decimal = CASE
    WHEN amount_difference = 0 THEN '0'
    ELSE printf('%.17g', amount_difference)
END;

CREATE INDEX IF NOT EXISTS idx_match_results_amount_difference_decimal
ON match_results(job_id, status, amount_difference_decimal);
"""


EVIDENCE_OBJECT_STORAGE_MIGRATION_SQL = """
ALTER TABLE evidence_registry ADD COLUMN storage_backend TEXT NOT NULL DEFAULT 'local-filesystem';
ALTER TABLE evidence_registry ADD COLUMN storage_tenant_id TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_registry ADD COLUMN storage_key TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_registry ADD COLUMN storage_version_id TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_registry ADD COLUMN content_type TEXT NOT NULL DEFAULT 'application/octet-stream';
ALTER TABLE evidence_registry ADD COLUMN byte_size INTEGER NOT NULL DEFAULT 0;
ALTER TABLE evidence_registry ADD COLUMN retention_until TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_evidence_registry_storage
ON evidence_registry(workspace_id, storage_backend, storage_tenant_id, storage_key);
"""


CONSOLIDATION_OWNERSHIP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS consolidation_ownership_interests (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    group_code TEXT NOT NULL,
    interest_id TEXT NOT NULL,
    parent_entity_code TEXT NOT NULL,
    subsidiary_entity_code TEXT NOT NULL,
    direct_ownership_percentage TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL,
    source_digest TEXT NOT NULL CHECK (length(source_digest)=64),
    prepared_by TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, group_code, interest_id),
    CHECK (parent_entity_code <> subsidiary_entity_code),
    CHECK (length(direct_ownership_percentage) BETWEEN 1 AND 80),
    CHECK (effective_to='' OR effective_from <= effective_to),
    CHECK (prepared_by <> approved_by)
);
CREATE INDEX IF NOT EXISTS idx_consolidation_ownership_scope
ON consolidation_ownership_interests(workspace_id, group_code, subsidiary_entity_code, effective_from, effective_to);
CREATE TRIGGER IF NOT EXISTS consolidation_ownership_immutable_update
BEFORE UPDATE ON consolidation_ownership_interests
BEGIN
    SELECT RAISE(ABORT, 'consolidation ownership interests are immutable');
END;
CREATE TRIGGER IF NOT EXISTS consolidation_ownership_immutable_delete
BEFORE DELETE ON consolidation_ownership_interests
BEGIN
    SELECT RAISE(ABORT, 'consolidation ownership interests cannot be deleted');
END;
"""

POLICY_DELEGATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS policy_delegations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    delegator_id TEXT NOT NULL,
    delegatee_id TEXT NOT NULL,
    permissions_json TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    revoked_at TEXT,
    revoked_by TEXT,
    CHECK (delegator_id <> delegatee_id),
    CHECK (starts_at < expires_at),
    CHECK (created_by <> '' AND approved_by <> ''),
    CHECK (status='active' OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL)),
    CHECK (status='revoked' OR (revoked_at IS NULL AND revoked_by IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_policy_delegations_effective
ON policy_delegations(tenant_id, workspace_id, delegatee_id, starts_at, expires_at, status);
CREATE TRIGGER IF NOT EXISTS policy_delegations_guard_update
BEFORE UPDATE ON policy_delegations
BEGIN
    SELECT CASE WHEN NEW.id<>OLD.id OR NEW.tenant_id<>OLD.tenant_id OR NEW.workspace_id<>OLD.workspace_id
      OR NEW.delegator_id<>OLD.delegator_id OR NEW.delegatee_id<>OLD.delegatee_id
      OR NEW.permissions_json<>OLD.permissions_json OR NEW.starts_at<>OLD.starts_at
      OR NEW.expires_at<>OLD.expires_at OR NEW.created_by<>OLD.created_by
      OR NEW.approved_by<>OLD.approved_by
      THEN RAISE(ABORT, 'delegation grant is immutable') END;
    SELECT CASE WHEN NOT (OLD.status='active' AND NEW.status='revoked'
      AND NEW.revoked_at IS NOT NULL AND NEW.revoked_by IS NOT NULL
      AND NEW.revoked_by<>OLD.delegator_id)
      THEN RAISE(ABORT, 'delegation status transition is invalid') END;
END;
CREATE TRIGGER IF NOT EXISTS policy_delegations_immutable_delete
BEFORE DELETE ON policy_delegations
BEGIN
    SELECT RAISE(ABORT, 'delegation grants cannot be deleted');
END;
"""

WRITEBACK_INTENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS connector_writeback_intents (
    intent_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    status TEXT NOT NULL,
    intent_digest TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (intent_id, version),
    UNIQUE (tenant_id, workspace_id, intent_id, intent_digest)
);
CREATE INDEX IF NOT EXISTS idx_connector_writeback_intents_scope
    ON connector_writeback_intents(tenant_id, workspace_id, intent_id, version DESC);
CREATE TRIGGER IF NOT EXISTS connector_writeback_intents_no_update
BEFORE UPDATE ON connector_writeback_intents
BEGIN
    SELECT RAISE(ABORT, 'write-back intents are immutable');
END;
CREATE TRIGGER IF NOT EXISTS connector_writeback_intents_no_delete
BEFORE DELETE ON connector_writeback_intents
BEGIN
    SELECT RAISE(ABORT, 'write-back intents cannot be deleted');
END;
INSERT OR IGNORE INTO permissions (name, description)
VALUES ('connectors.writeback.propose', 'Propose a digest-bound governed connector write-back intent.');
INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles CROSS JOIN permissions
WHERE roles.name IN ('admin', 'controller') AND permissions.name='connectors.writeback.propose';
"""

WRITEBACK_APPROVAL_PERMISSION_SQL = """
INSERT OR IGNORE INTO permissions (name, description)
VALUES ('connectors.writeback.approve', 'Approve a governed connector write-back intent as a distinct human checker.');
INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles CROSS JOIN permissions
WHERE roles.name IN ('admin', 'controller') AND permissions.name='connectors.writeback.approve';
"""

WRITEBACK_RECONCILIATION_PERMISSION_SQL = """
INSERT OR IGNORE INTO permissions (name, description)
VALUES ('connectors.writeback.reconcile', 'Reconcile a provider acknowledgement to a dispatched write-back intent.');
INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles CROSS JOIN permissions
WHERE roles.name IN ('admin', 'controller') AND permissions.name='connectors.writeback.reconcile';
"""

WRITEBACK_DISPATCH_PERMISSION_SQL = """
INSERT OR IGNORE INTO permissions (name, description)
VALUES ('connectors.writeback.dispatch', 'Dispatch an approved write-back intent through an explicitly registered provider boundary.');
INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles CROSS JOIN permissions
WHERE roles.name IN ('admin', 'controller') AND permissions.name='connectors.writeback.dispatch';
"""

WRITEBACK_COMPENSATION_PERMISSION_SQL = """
INSERT OR IGNORE INTO permissions (name, description)
VALUES ('connectors.writeback.compensate', 'Request a separately governed compensation for a dispatched write-back intent.');
INSERT OR IGNORE INTO role_permissions (role_id, permission_name)
SELECT roles.id, permissions.name
FROM roles CROSS JOIN permissions
WHERE roles.name IN ('admin', 'controller') AND permissions.name='connectors.writeback.compensate';
"""
