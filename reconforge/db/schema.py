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
