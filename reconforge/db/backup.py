"""Local DB backup and restore helpers for the migration bridge."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconforge.audit import append_audit_event
from reconforge.db.connection import connect, resolve_db_path
from reconforge.db.exporter import (
    DBBridgeError,
    checksum_file,
    resolve_input_file,
    resolve_local_path,
    resolve_output_dir,
    write_json_file,
)
from reconforge.db.migrations import MIGRATIONS, database_status, run_migrations
from reconforge.domain.models import utc_now_text

BACKUP_FORMAT_VERSION = 1
BACKUP_WARNING = (
    "ReconForge local DB backups may contain sensitive local business data and local password hashes "
    "needed for restore. Protect backup files. This is not cloud backup, SaaS storage, an enterprise "
    "DR guarantee, or a compliance certification."
)

BACKUP_TABLES = [
    "schema_migrations",
    "workspaces",
    "organizations",
    "legal_entities",
    "periods",
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "accounts",
    "reconciliations",
    "tasks",
    "controls",
    "evidence_objects",
    "account_reconciliation_templates",
    "trial_balance_rows",
    "account_reconciliation_records",
    "account_reconciliation_items",
    "account_reconciliation_support",
    "close_periods",
    "close_tasks_db",
    "close_task_dependencies",
    "approval_requests",
    "certification_records",
    "evidence_registry",
    "evidence_requirements",
    "evidence_links",
    "journal_entries",
    "journal_exceptions",
    "intercompany_transactions",
    "intercompany_cases",
    "control_library",
    "control_test_plans",
    "control_test_samples",
    "control_test_results",
    "remediation_plans",
    "match_jobs",
    "match_rules",
    "match_results",
    "exceptions_queue",
    "metric_definitions",
    "metric_snapshots",
    "ops_job_history",
    "ops_error_records",
    "workflow_objects",
    "workflow_transitions",
    "workflow_transition_events",
    "legacy_import_records",
    "audit_events",
    "audit_ledger_state",
]

EXCLUDED_BACKUP_TABLES = ["api_sessions"]

BACKUP_SELECT_QUERIES = {
    "schema_migrations": "SELECT * FROM schema_migrations ORDER BY version",
    "workspaces": "SELECT * FROM workspaces ORDER BY created_at, id",
    "organizations": "SELECT * FROM organizations ORDER BY created_at, id",
    "legal_entities": "SELECT * FROM legal_entities ORDER BY entity_code, id",
    "periods": "SELECT * FROM periods ORDER BY start_date, id",
    "users": "SELECT * FROM users ORDER BY username",
    "roles": "SELECT * FROM roles ORDER BY name",
    "permissions": "SELECT * FROM permissions ORDER BY name",
    "user_roles": "SELECT * FROM user_roles ORDER BY user_id, role_id",
    "role_permissions": "SELECT * FROM role_permissions ORDER BY role_id, permission_name",
    "accounts": "SELECT * FROM accounts ORDER BY account_code, id",
    "reconciliations": "SELECT * FROM reconciliations ORDER BY created_at, id",
    "tasks": "SELECT * FROM tasks ORDER BY created_at, id",
    "controls": "SELECT * FROM controls ORDER BY control_code, id",
    "evidence_objects": "SELECT * FROM evidence_objects ORDER BY created_at, id",
    "account_reconciliation_templates": "SELECT * FROM account_reconciliation_templates ORDER BY workspace_id, account_code",
    "trial_balance_rows": "SELECT * FROM trial_balance_rows ORDER BY workspace_id, period_name, entity_code, account_code, source_row_number",
    "account_reconciliation_records": "SELECT * FROM account_reconciliation_records ORDER BY workspace_id, period_name, entity_code, account_code",
    "account_reconciliation_items": "SELECT * FROM account_reconciliation_items ORDER BY reconciliation_id, created_at, id",
    "account_reconciliation_support": "SELECT * FROM account_reconciliation_support ORDER BY reconciliation_id, evidence_id",
    "close_periods": "SELECT * FROM close_periods ORDER BY workspace_id, period_name",
    "close_tasks_db": "SELECT * FROM close_tasks_db ORDER BY close_period_id, task_code",
    "close_task_dependencies": "SELECT * FROM close_task_dependencies ORDER BY close_period_id, task_id, depends_on_task_id",
    "approval_requests": "SELECT * FROM approval_requests ORDER BY created_at, id",
    "certification_records": "SELECT * FROM certification_records ORDER BY object_type, object_id",
    "evidence_registry": "SELECT * FROM evidence_registry ORDER BY workspace_id, evidence_code",
    "evidence_requirements": "SELECT * FROM evidence_requirements ORDER BY workspace_id, object_type, object_id, requirement_code",
    "evidence_links": "SELECT * FROM evidence_links ORDER BY object_type, object_id, evidence_id",
    "journal_entries": "SELECT * FROM journal_entries ORDER BY workspace_id, period_name, journal_id",
    "journal_exceptions": "SELECT * FROM journal_exceptions ORDER BY journal_entry_id, policy_code",
    "intercompany_transactions": "SELECT * FROM intercompany_transactions ORDER BY workspace_id, period_name, transaction_id",
    "intercompany_cases": "SELECT * FROM intercompany_cases ORDER BY workspace_id, period_name, entity_code, counterparty_code, reference",
    "control_library": "SELECT * FROM control_library ORDER BY workspace_id, control_code",
    "control_test_plans": "SELECT * FROM control_test_plans ORDER BY workspace_id, period_name, control_id",
    "control_test_samples": "SELECT * FROM control_test_samples ORDER BY test_plan_id, sample_reference",
    "control_test_results": "SELECT * FROM control_test_results ORDER BY test_plan_id, created_at, id",
    "remediation_plans": "SELECT * FROM remediation_plans ORDER BY source_type, source_id",
    "match_jobs": "SELECT * FROM match_jobs ORDER BY created_at, id",
    "match_rules": "SELECT * FROM match_rules ORDER BY job_id, rule_name",
    "match_results": "SELECT * FROM match_results ORDER BY job_id, left_id, right_id, match_type",
    "exceptions_queue": "SELECT * FROM exceptions_queue ORDER BY status, risk_rating, created_at, id",
    "metric_definitions": "SELECT * FROM metric_definitions ORDER BY metric_key",
    "metric_snapshots": "SELECT * FROM metric_snapshots ORDER BY workspace_id, period_name, metric_key",
    "ops_job_history": "SELECT * FROM ops_job_history ORDER BY started_at, id",
    "ops_error_records": "SELECT * FROM ops_error_records ORDER BY created_at, id",
    "workflow_objects": "SELECT * FROM workflow_objects ORDER BY object_type, object_id",
    "workflow_transitions": "SELECT * FROM workflow_transitions ORDER BY object_type, from_status, to_status, id",
    "workflow_transition_events": "SELECT * FROM workflow_transition_events ORDER BY created_at, id",
    "legacy_import_records": "SELECT * FROM legacy_import_records ORDER BY source_type, object_type, object_id",
    "audit_events": "SELECT * FROM audit_events ORDER BY sequence",
    "audit_ledger_state": "SELECT * FROM audit_ledger_state ORDER BY id",
}

BACKUP_DELETE_QUERIES = {
    "schema_migrations": "DELETE FROM schema_migrations",
    "workspaces": "DELETE FROM workspaces",
    "organizations": "DELETE FROM organizations",
    "legal_entities": "DELETE FROM legal_entities",
    "periods": "DELETE FROM periods",
    "users": "DELETE FROM users",
    "roles": "DELETE FROM roles",
    "permissions": "DELETE FROM permissions",
    "user_roles": "DELETE FROM user_roles",
    "role_permissions": "DELETE FROM role_permissions",
    "accounts": "DELETE FROM accounts",
    "reconciliations": "DELETE FROM reconciliations",
    "tasks": "DELETE FROM tasks",
    "controls": "DELETE FROM controls",
    "evidence_objects": "DELETE FROM evidence_objects",
    "account_reconciliation_templates": "DELETE FROM account_reconciliation_templates",
    "trial_balance_rows": "DELETE FROM trial_balance_rows",
    "account_reconciliation_records": "DELETE FROM account_reconciliation_records",
    "account_reconciliation_items": "DELETE FROM account_reconciliation_items",
    "account_reconciliation_support": "DELETE FROM account_reconciliation_support",
    "close_periods": "DELETE FROM close_periods",
    "close_tasks_db": "DELETE FROM close_tasks_db",
    "close_task_dependencies": "DELETE FROM close_task_dependencies",
    "approval_requests": "DELETE FROM approval_requests",
    "certification_records": "DELETE FROM certification_records",
    "evidence_registry": "DELETE FROM evidence_registry",
    "evidence_requirements": "DELETE FROM evidence_requirements",
    "evidence_links": "DELETE FROM evidence_links",
    "journal_entries": "DELETE FROM journal_entries",
    "journal_exceptions": "DELETE FROM journal_exceptions",
    "intercompany_transactions": "DELETE FROM intercompany_transactions",
    "intercompany_cases": "DELETE FROM intercompany_cases",
    "control_library": "DELETE FROM control_library",
    "control_test_plans": "DELETE FROM control_test_plans",
    "control_test_samples": "DELETE FROM control_test_samples",
    "control_test_results": "DELETE FROM control_test_results",
    "remediation_plans": "DELETE FROM remediation_plans",
    "match_jobs": "DELETE FROM match_jobs",
    "match_rules": "DELETE FROM match_rules",
    "match_results": "DELETE FROM match_results",
    "exceptions_queue": "DELETE FROM exceptions_queue",
    "metric_definitions": "DELETE FROM metric_definitions",
    "metric_snapshots": "DELETE FROM metric_snapshots",
    "ops_job_history": "DELETE FROM ops_job_history",
    "ops_error_records": "DELETE FROM ops_error_records",
    "workflow_objects": "DELETE FROM workflow_objects",
    "workflow_transitions": "DELETE FROM workflow_transitions",
    "workflow_transition_events": "DELETE FROM workflow_transition_events",
    "legacy_import_records": "DELETE FROM legacy_import_records",
    "audit_events": "DELETE FROM audit_events",
    "audit_ledger_state": "DELETE FROM audit_ledger_state",
}

BACKUP_INSERT_COLUMNS = {
    "schema_migrations": ("version", "name", "applied_at"),
    "workspaces": ("id", "name", "local_first_note", "created_at"),
    "organizations": ("id", "workspace_id", "name", "created_at"),
    "legal_entities": ("id", "organization_id", "entity_code", "name", "currency", "created_at"),
    "periods": ("id", "workspace_id", "name", "start_date", "end_date", "status", "created_at"),
    "users": (
        "id",
        "username",
        "display_name",
        "email",
        "disabled",
        "created_at",
        "password_hash",
        "password_salt",
        "password_iterations",
        "password_algorithm",
        "password_changed_at",
        "failed_login_count",
        "locked_until",
    ),
    "roles": ("id", "name"),
    "permissions": ("name", "description"),
    "user_roles": ("user_id", "role_id"),
    "role_permissions": ("role_id", "permission_name"),
    "accounts": ("id", "workspace_id", "account_code", "account_name", "created_at"),
    "reconciliations": ("id", "workspace_id", "period_id", "account_id", "reconciliation_type", "status", "owner_user_id", "created_at"),
    "tasks": ("id", "workspace_id", "period_id", "task_type", "status", "owner_user_id", "created_at"),
    "controls": ("id", "workspace_id", "control_code", "name", "status", "owner_user_id", "created_at"),
    "evidence_objects": ("id", "workspace_id", "source_path", "checksum_sha256", "provenance_type", "redaction_status", "created_at"),
    "account_reconciliation_templates": (
        "id", "workspace_id", "account_code", "name", "risk_rating", "materiality_threshold",
        "required_evidence", "owner", "reviewer", "created_at", "updated_at",
    ),
    "trial_balance_rows": (
        "id", "workspace_id", "period_name", "entity_code", "account_code", "account_name",
        "balance", "currency", "source_path", "source_row_number", "imported_at",
    ),
    "account_reconciliation_records": (
        "id", "workspace_id", "period_name", "entity_code", "account_code", "account_name",
        "template_id", "status", "balance", "materiality_threshold", "risk_rating", "owner",
        "preparer", "reviewer", "prepared_at", "submitted_at", "reviewed_at", "completed_at",
        "aging_days", "created_at", "updated_at",
    ),
    "account_reconciliation_items": (
        "id", "reconciliation_id", "item_type", "description", "amount", "status",
        "evidence_required", "created_at",
    ),
    "account_reconciliation_support": ("id", "reconciliation_id", "evidence_id", "note", "created_at"),
    "close_periods": (
        "id", "workspace_id", "period_name", "start_date", "end_date", "status",
        "readiness_score", "locked_at", "reopened_at", "created_at", "updated_at",
    ),
    "close_tasks_db": (
        "id", "close_period_id", "task_code", "name", "owner", "category", "risk_rating",
        "due_date", "status", "blocker_reason", "updated_by", "created_at", "updated_at",
    ),
    "close_task_dependencies": ("id", "close_period_id", "task_id", "depends_on_task_id", "created_at"),
    "approval_requests": (
        "id", "object_type", "object_id", "title", "requested_by", "assigned_to",
        "status", "reason", "decision_reason", "override_reason", "decided_by",
        "created_at", "updated_at",
    ),
    "certification_records": (
        "id", "object_type", "object_id", "period_name", "entity_code", "status",
        "prepared_by", "reviewed_by", "note", "created_at", "updated_at",
    ),
    "evidence_registry": (
        "id", "workspace_id", "evidence_code", "source_path", "checksum_sha256",
        "provenance_type", "redaction_status", "evidence_status", "registered_by",
        "created_at", "updated_at",
    ),
    "evidence_requirements": (
        "id", "workspace_id", "object_type", "object_id", "requirement_code",
        "description", "required_status", "created_at",
    ),
    "evidence_links": ("id", "evidence_id", "object_type", "object_id", "link_type", "created_at"),
    "journal_entries": (
        "id", "workspace_id", "journal_id", "period_name", "entity_code", "posting_date",
        "account_code", "amount", "currency", "reference", "approver", "is_manual",
        "source_path", "imported_at",
    ),
    "journal_exceptions": ("id", "journal_entry_id", "policy_code", "risk_rating", "description", "status", "created_at"),
    "intercompany_transactions": (
        "id", "workspace_id", "transaction_id", "period_name", "entity_code",
        "counterparty_code", "posting_date", "amount", "currency", "reference",
        "source_path", "imported_at",
    ),
    "intercompany_cases": (
        "id", "workspace_id", "period_name", "entity_code", "counterparty_code",
        "reference", "imbalance_amount", "currency", "status", "dispute_owner",
        "settlement_status", "aging_days", "evidence_note", "created_at", "updated_at",
    ),
    "control_library": (
        "id", "workspace_id", "control_code", "name", "owner", "frequency",
        "description", "risk_rating", "created_at", "updated_at",
    ),
    "control_test_plans": (
        "id", "workspace_id", "control_id", "period_name", "status", "planned_by",
        "sample_size", "created_at", "updated_at",
    ),
    "control_test_samples": ("id", "test_plan_id", "sample_reference", "status", "created_at"),
    "control_test_results": (
        "id", "test_plan_id", "result_status", "effectiveness_status", "tested_by",
        "note", "evidence_id", "created_at", "updated_at",
    ),
    "remediation_plans": (
        "id", "source_type", "source_id", "owner", "status", "target_date",
        "action_plan", "created_at", "updated_at",
    ),
    "match_jobs": (
        "id", "workspace_id", "name", "left_source", "right_source", "status",
        "rule_json", "created_by", "created_at", "completed_at",
    ),
    "match_rules": ("id", "job_id", "rule_name", "rule_json", "created_at"),
    "match_results": (
        "id", "job_id", "left_id", "right_id", "match_type", "confidence",
        "explanation", "amount_difference", "date_difference_days", "status", "created_at",
    ),
    "exceptions_queue": (
        "id", "workspace_id", "source_type", "source_id", "period_name", "entity_code",
        "account_code", "control_code", "risk_rating", "owner", "status", "escalation_level",
        "sla_target_date", "description", "created_at", "updated_at",
    ),
    "metric_definitions": ("id", "metric_key", "name", "description", "lineage", "created_at"),
    "metric_snapshots": (
        "id", "workspace_id", "metric_key", "period_name", "value", "value_text", "lineage", "computed_at",
    ),
    "ops_job_history": ("id", "workspace_id", "job_type", "status", "summary", "started_at", "completed_at"),
    "ops_error_records": ("id", "workspace_id", "source", "error_code", "message", "created_at"),
    "workflow_objects": ("object_type", "object_id", "status", "updated_at", "id", "created_at"),
    "workflow_transitions": ("id", "object_type", "from_status", "to_status", "required_permission", "sod_rule", "reason_required", "active"),
    "workflow_transition_events": ("id", "workflow_object_id", "from_status", "to_status", "actor_user_id", "actor_label", "reason", "created_at"),
    "legacy_import_records": (
        "id",
        "source_type",
        "object_type",
        "object_id",
        "status",
        "source_path",
        "source_checksum_sha256",
        "summary_json",
        "imported_at",
    ),
    "audit_events": (
        "id",
        "sequence",
        "previous_hash",
        "event_hash",
        "actor_user_id",
        "actor_label",
        "object_type",
        "object_id",
        "action",
        "before_hash",
        "after_hash",
        "metadata_json",
        "created_at",
    ),
    "audit_ledger_state": ("id", "last_sequence", "last_event_hash", "updated_at"),
}

BACKUP_INSERT_QUERIES = {
    "schema_migrations": "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
    "workspaces": "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES (?, ?, ?, ?)",
    "organizations": "INSERT INTO organizations (id, workspace_id, name, created_at) VALUES (?, ?, ?, ?)",
    "legal_entities": "INSERT INTO legal_entities (id, organization_id, entity_code, name, currency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    "periods": "INSERT INTO periods (id, workspace_id, name, start_date, end_date, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "users": """
        INSERT INTO users (
            id, username, display_name, email, disabled, created_at,
            password_hash, password_salt, password_iterations, password_algorithm,
            password_changed_at, failed_login_count, locked_until
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "roles": "INSERT INTO roles (id, name) VALUES (?, ?)",
    "permissions": "INSERT INTO permissions (name, description) VALUES (?, ?)",
    "user_roles": "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
    "role_permissions": "INSERT INTO role_permissions (role_id, permission_name) VALUES (?, ?)",
    "accounts": "INSERT INTO accounts (id, workspace_id, account_code, account_name, created_at) VALUES (?, ?, ?, ?, ?)",
    "reconciliations": """
        INSERT INTO reconciliations (
            id, workspace_id, period_id, account_id, reconciliation_type,
            status, owner_user_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "tasks": "INSERT INTO tasks (id, workspace_id, period_id, task_type, status, owner_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "controls": "INSERT INTO controls (id, workspace_id, control_code, name, status, owner_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "evidence_objects": """
        INSERT INTO evidence_objects (
            id, workspace_id, source_path, checksum_sha256, provenance_type,
            redaction_status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "account_reconciliation_templates": """
        INSERT INTO account_reconciliation_templates (
            id, workspace_id, account_code, name, risk_rating, materiality_threshold,
            required_evidence, owner, reviewer, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "trial_balance_rows": """
        INSERT INTO trial_balance_rows (
            id, workspace_id, period_name, entity_code, account_code, account_name,
            balance, currency, source_path, source_row_number, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "account_reconciliation_records": """
        INSERT INTO account_reconciliation_records (
            id, workspace_id, period_name, entity_code, account_code, account_name,
            template_id, status, balance, materiality_threshold, risk_rating, owner,
            preparer, reviewer, prepared_at, submitted_at, reviewed_at, completed_at,
            aging_days, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "account_reconciliation_items": """
        INSERT INTO account_reconciliation_items (
            id, reconciliation_id, item_type, description, amount, status,
            evidence_required, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "account_reconciliation_support": """
        INSERT INTO account_reconciliation_support (id, reconciliation_id, evidence_id, note, created_at)
        VALUES (?, ?, ?, ?, ?)
    """,
    "close_periods": """
        INSERT INTO close_periods (
            id, workspace_id, period_name, start_date, end_date, status,
            readiness_score, locked_at, reopened_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "close_tasks_db": """
        INSERT INTO close_tasks_db (
            id, close_period_id, task_code, name, owner, category, risk_rating,
            due_date, status, blocker_reason, updated_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "close_task_dependencies": """
        INSERT INTO close_task_dependencies (id, close_period_id, task_id, depends_on_task_id, created_at)
        VALUES (?, ?, ?, ?, ?)
    """,
    "approval_requests": """
        INSERT INTO approval_requests (
            id, object_type, object_id, title, requested_by, assigned_to,
            status, reason, decision_reason, override_reason, decided_by,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "certification_records": """
        INSERT INTO certification_records (
            id, object_type, object_id, period_name, entity_code, status,
            prepared_by, reviewed_by, note, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "evidence_registry": """
        INSERT INTO evidence_registry (
            id, workspace_id, evidence_code, source_path, checksum_sha256,
            provenance_type, redaction_status, evidence_status, registered_by,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "evidence_requirements": """
        INSERT INTO evidence_requirements (
            id, workspace_id, object_type, object_id, requirement_code,
            description, required_status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "evidence_links": """
        INSERT INTO evidence_links (id, evidence_id, object_type, object_id, link_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    "journal_entries": """
        INSERT INTO journal_entries (
            id, workspace_id, journal_id, period_name, entity_code, posting_date,
            account_code, amount, currency, reference, approver, is_manual,
            source_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "journal_exceptions": """
        INSERT INTO journal_exceptions (
            id, journal_entry_id, policy_code, risk_rating, description, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "intercompany_transactions": """
        INSERT INTO intercompany_transactions (
            id, workspace_id, transaction_id, period_name, entity_code,
            counterparty_code, posting_date, amount, currency, reference,
            source_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "intercompany_cases": """
        INSERT INTO intercompany_cases (
            id, workspace_id, period_name, entity_code, counterparty_code,
            reference, imbalance_amount, currency, status, dispute_owner,
            settlement_status, aging_days, evidence_note, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "control_library": """
        INSERT INTO control_library (
            id, workspace_id, control_code, name, owner, frequency,
            description, risk_rating, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "control_test_plans": """
        INSERT INTO control_test_plans (
            id, workspace_id, control_id, period_name, status, planned_by,
            sample_size, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "control_test_samples": """
        INSERT INTO control_test_samples (id, test_plan_id, sample_reference, status, created_at)
        VALUES (?, ?, ?, ?, ?)
    """,
    "control_test_results": """
        INSERT INTO control_test_results (
            id, test_plan_id, result_status, effectiveness_status, tested_by,
            note, evidence_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "remediation_plans": """
        INSERT INTO remediation_plans (
            id, source_type, source_id, owner, status, target_date,
            action_plan, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "match_jobs": """
        INSERT INTO match_jobs (
            id, workspace_id, name, left_source, right_source, status,
            rule_json, created_by, created_at, completed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "match_rules": """
        INSERT INTO match_rules (id, job_id, rule_name, rule_json, created_at)
        VALUES (?, ?, ?, ?, ?)
    """,
    "match_results": """
        INSERT INTO match_results (
            id, job_id, left_id, right_id, match_type, confidence,
            explanation, amount_difference, date_difference_days, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "exceptions_queue": """
        INSERT INTO exceptions_queue (
            id, workspace_id, source_type, source_id, period_name, entity_code,
            account_code, control_code, risk_rating, owner, status, escalation_level,
            sla_target_date, description, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "metric_definitions": """
        INSERT INTO metric_definitions (id, metric_key, name, description, lineage, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    "metric_snapshots": """
        INSERT INTO metric_snapshots (
            id, workspace_id, metric_key, period_name, value, value_text, lineage, computed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ops_job_history": """
        INSERT INTO ops_job_history (id, workspace_id, job_type, status, summary, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "ops_error_records": """
        INSERT INTO ops_error_records (id, workspace_id, source, error_code, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    "workflow_objects": "INSERT INTO workflow_objects (object_type, object_id, status, updated_at, id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    "workflow_transitions": """
        INSERT INTO workflow_transitions (
            id, object_type, from_status, to_status, required_permission,
            sod_rule, reason_required, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "workflow_transition_events": """
        INSERT INTO workflow_transition_events (
            id, workflow_object_id, from_status, to_status,
            actor_user_id, actor_label, reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "legacy_import_records": """
        INSERT INTO legacy_import_records (
            id, source_type, object_type, object_id, status, source_path,
            source_checksum_sha256, summary_json, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "audit_events": """
        INSERT INTO audit_events (
            id, sequence, previous_hash, event_hash, actor_user_id, actor_label,
            object_type, object_id, action, before_hash, after_hash, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "audit_ledger_state": "INSERT INTO audit_ledger_state (id, last_sequence, last_event_hash, updated_at) VALUES (?, ?, ?, ?)",
}


@dataclass(frozen=True)
class DBBackupResult:
    """Files written for one local DB backup."""

    output_dir: Path
    backup_path: Path
    manifest_path: Path
    checksum_sha256: str
    schema_version: int


@dataclass(frozen=True)
class DBRestoreResult:
    """Result from one local DB restore."""

    db_path: Path
    backup_path: Path
    schema_version: int
    restored_tables: list[str]
    dry_run: bool = False


@dataclass(frozen=True)
class DBBackupVerificationResult:
    """Result from local backup manifest/checksum verification."""

    backup_path: Path
    schema_version: int
    checksum_sha256: str
    ok: bool


def _schema_version(db_path: Path | str) -> int:
    status = database_status(db_path)
    if status.pending_versions:
        raise DBBridgeError("ReconForge database has pending migrations. Run 'reconforge db migrate' first.")
    return status.current_version


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(connection, table):
        return []
    query = BACKUP_SELECT_QUERIES.get(table)
    if query is None:
        raise DBBridgeError("Unsupported backup table.")
    rows = connection.execute(query).fetchall()
    return [dict(row) for row in rows]


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DBBridgeError("Backup JSON could not be parsed.") from exc
    if not isinstance(payload, dict):
        raise DBBridgeError("Backup JSON must contain an object.")
    return payload


def _backup_payload(connection: sqlite3.Connection, *, created_at: str, schema_version: int) -> dict[str, Any]:
    return {
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": created_at,
        "schema_version": schema_version,
        "latest_supported_schema_version": MIGRATIONS[-1].version,
        "privacy_warning": BACKUP_WARNING,
        "restore_sensitive_material": "Includes local credential verifier fields needed for restore.",
        "excluded_tables": EXCLUDED_BACKUP_TABLES,
        "tables": {table: _table_rows(connection, table) for table in BACKUP_TABLES},
    }


def create_backup(
    db_path: Path | str,
    output_dir: Path | str,
    *,
    actor_label: str = "local-cli",
) -> DBBackupResult:
    """Create a local JSON backup and checksum manifest."""

    resolved_db_path = resolve_db_path(db_path)
    schema_version = _schema_version(resolved_db_path)
    resolved_output_dir = resolve_output_dir(output_dir)
    created_at = utc_now_text()
    backup_path = resolved_output_dir / "backup.json"
    manifest_path = resolved_output_dir / "manifest.json"
    connection = connect(resolved_db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label=actor_label,
            object_type="db_bridge",
            object_id="backup",
            action="db_backup_created",
            metadata={
                "schema_version": schema_version,
                "backup_dir_name": resolved_output_dir.name,
                "excluded_tables": EXCLUDED_BACKUP_TABLES,
            },
        )
        payload = _backup_payload(connection, created_at=created_at, schema_version=schema_version)
        write_json_file(backup_path, payload)
        checksum = checksum_file(backup_path)
        manifest = {
            "manifest_version": 1,
            "created_at": created_at,
            "schema_version": schema_version,
            "privacy_warning": BACKUP_WARNING,
            "artifacts": {
                "backup.json": {
                    "sha256": checksum,
                    "bytes": backup_path.stat().st_size,
                },
            },
        }
        write_json_file(manifest_path, manifest)
    except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as exc:
        raise DBBridgeError("Unable to create local DB backup.") from exc
    finally:
        connection.close()
    return DBBackupResult(
        output_dir=resolved_output_dir,
        backup_path=backup_path,
        manifest_path=manifest_path,
        checksum_sha256=checksum,
        schema_version=schema_version,
    )


def _backup_paths(input_path: Path | str) -> tuple[Path, Path]:
    resolved = resolve_local_path(input_path)
    backup_path = resolved / "backup.json" if resolved.is_dir() else resolve_input_file(resolved)
    manifest_path = backup_path.parent / "manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        raise DBBridgeError("Backup manifest not found.")
    return backup_path, manifest_path


def _validate_backup(input_path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    backup_path, manifest_path = _backup_paths(input_path)
    manifest = _read_json_file(manifest_path)
    backup = _read_json_file(backup_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get("backup.json"), dict):
        raise DBBridgeError("Backup manifest is invalid.")
    expected_checksum = str(artifacts["backup.json"].get("sha256", ""))
    actual_checksum = checksum_file(backup_path)
    if not expected_checksum or actual_checksum != expected_checksum:
        raise DBBridgeError("Backup checksum verification failed.")
    format_version = int(backup.get("backup_format_version", 0))
    if format_version != BACKUP_FORMAT_VERSION:
        raise DBBridgeError("Unsupported backup format version.")
    schema_version = int(backup.get("schema_version", 0))
    if schema_version <= 0 or schema_version > MIGRATIONS[-1].version:
        raise DBBridgeError("Unsupported backup schema version.")
    if not isinstance(backup.get("tables"), dict):
        raise DBBridgeError("Backup table payload is invalid.")
    return backup_path, manifest, backup


def _temp_restore_path(target: Path) -> Path:
    return target.with_name(f"{target.stem}.restore_tmp{target.suffix}")


def _clear_restore_tables(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    for table in reversed(BACKUP_TABLES):
        if _table_exists(connection, table):
            query = BACKUP_DELETE_QUERIES.get(table)
            if query is None:
                raise DBBridgeError("Unsupported restore table.")
            connection.execute(query)
    if _table_exists(connection, "sqlite_sequence"):
        connection.execute("DELETE FROM sqlite_sequence")
    connection.commit()


def _insert_rows(connection: sqlite3.Connection, *, table: str, rows: object) -> None:
    if rows is None:
        return
    if not isinstance(rows, list):
        raise DBBridgeError("Backup table rows are invalid.")
    if not _table_exists(connection, table):
        raise DBBridgeError(f"Backup table is not supported by this ReconForge version: {table}.")
    columns = BACKUP_INSERT_COLUMNS.get(table)
    query = BACKUP_INSERT_QUERIES.get(table)
    if columns is None or query is None:
        raise DBBridgeError("Unsupported restore table.")
    for row in rows:
        if not isinstance(row, dict):
            raise DBBridgeError("Backup table row is invalid.")
        if not row:
            continue
        unknown_columns = set(row) - set(columns)
        if unknown_columns:
            raise DBBridgeError(f"Backup table contains unsupported columns: {table}.")
        values = [row.get(column) for column in columns]
        connection.execute(query, values)


def restore_backup(
    db_path: Path | str,
    input_path: Path | str,
    *,
    force: bool = False,
    dry_run: bool = False,
    actor_label: str = "local-cli",
) -> DBRestoreResult:
    """Restore a local DB backup after checksum validation."""

    backup_path, _manifest, backup = _validate_backup(input_path)
    target = resolve_db_path(db_path)
    if dry_run:
        return DBRestoreResult(
            db_path=target,
            backup_path=backup_path,
            schema_version=int(backup["schema_version"]),
            restored_tables=[],
            dry_run=True,
        )
    if target.exists() and not force:
        raise DBBridgeError("Restore target already exists. Re-run with --force to overwrite it.")
    temp_path = _temp_restore_path(target)
    if temp_path.exists():
        if temp_path.is_symlink():
            raise DBBridgeError("Unsafe temporary restore path.")
        temp_path.unlink()
    restored_tables: list[str] = []
    try:
        run_migrations(temp_path)
        connection = connect(temp_path, require_exists=True)
        try:
            _clear_restore_tables(connection)
            tables = backup["tables"]
            if not isinstance(tables, dict):
                raise DBBridgeError("Backup table payload is invalid.")
            for table in BACKUP_TABLES:
                _insert_rows(connection, table=table, rows=tables.get(table, []))
                restored_tables.append(table)
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
            append_audit_event(
                connection,
                actor_label=actor_label,
                object_type="db_bridge",
                object_id="restore",
                action="db_backup_restored",
                metadata={
                    "backup_file": backup_path.name,
                    "schema_version": int(backup["schema_version"]),
                    "restored_table_count": len(restored_tables),
                },
            )
        finally:
            connection.close()
        temp_path.replace(target)
    except DBBridgeError:
        if temp_path.exists():
            temp_path.unlink()
        raise
    except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as exc:
        if temp_path.exists():
            temp_path.unlink()
        raise DBBridgeError("Unable to restore local DB backup.") from exc
    return DBRestoreResult(
        db_path=target,
        backup_path=backup_path,
        schema_version=int(backup["schema_version"]),
        restored_tables=restored_tables,
    )


def verify_backup(input_path: Path | str) -> DBBackupVerificationResult:
    """Validate a local backup manifest, checksum, format, and schema support."""

    backup_path, manifest, backup = _validate_backup(input_path)
    artifacts = manifest.get("artifacts")
    checksum = ""
    if isinstance(artifacts, dict) and isinstance(artifacts.get("backup.json"), dict):
        checksum = str(artifacts["backup.json"].get("sha256", ""))
    return DBBackupVerificationResult(
        backup_path=backup_path,
        schema_version=int(backup["schema_version"]),
        checksum_sha256=checksum,
        ok=True,
    )
