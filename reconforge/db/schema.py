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
