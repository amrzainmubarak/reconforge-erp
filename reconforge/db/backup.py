"""Local DB backup and restore helpers for the migration bridge."""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from hashlib import sha256
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
from reconforge.io.structured import (
    StructuredDocumentError,
    StructuredDocumentPolicy,
    read_json_document,
)
from reconforge.platform.common import ensure_outbox_schema

BACKUP_FORMAT_VERSION = 1
BACKUP_WARNING = (
    "ReconForge local DB backups may contain sensitive local business data and local password hashes "
    "needed for restore. Protect backup files. This is not cloud backup, SaaS storage, an enterprise "
    "DR guarantee, or a compliance certification."
)
_IDENTIFIER_RE = re.compile(r"^[A-Z_a-z][A-Za-z0-9_]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BACKUP_JSON_INGRESS_PROFILE = "database-backup-json-ingress-v1"
BACKUP_JSON_MAX_FILE_BYTES = 64 * 1024 * 1024
BACKUP_JSON_MAX_NODES = 1_000_000
BACKUP_JSON_MAX_COLLECTION_ITEMS = 250_000
BACKUP_JSON_MAX_SCALAR_CHARACTERS = 8 * 1024 * 1024
BACKUP_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=BACKUP_JSON_MAX_FILE_BYTES,
    max_nodes=BACKUP_JSON_MAX_NODES,
    max_depth=64,
    max_collection_items=BACKUP_JSON_MAX_COLLECTION_ITEMS,
    max_scalar_characters=BACKUP_JSON_MAX_SCALAR_CHARACTERS,
    max_yaml_aliases=1,
)
_BACKUP_READ_CHUNK_BYTES = 1024 * 1024

BACKUP_TABLES = [
    "workspaces",
    "organizations",
    "currencies",
    "legal_entities",
    "branches",
    "periods",
    "units_of_measure",
    "warehouses",
    "inventory_locations",
    "charts_of_accounts",
    "accounting_dimensions",
    "accounting_dimension_values",
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "accounts",
    "ap_suppliers",
    "ap_purchase_orders",
    "ap_purchase_order_lines",
    "ap_goods_receipts",
    "ap_goods_receipt_lines",
    "ap_supplier_invoices",
    "ap_supplier_invoice_lines",
    "ap_three_way_matches",
    "ap_idempotency_keys",
    "ar_customers",
    "ar_invoices",
    "ar_invoice_lines",
    "ar_receipts",
    "ar_receipt_allocations",
    "ar_idempotency_keys",
    "inventory_items",
    "inventory_lots",
    "finance_journals",
    "ledger_entries",
    "ledger_lines",
    "ledger_line_dimensions",
    "inventory_movements",
    "inventory_movement_lines",
    "inventory_count_sessions",
    "inventory_count_lines",
    "inventory_reorder_rules",
    "inventory_valuation_policies",
    "inventory_valuation_documents",
    "inventory_valuation_input_costs",
    "inventory_valuation_lines",
    "inventory_cost_layers",
    "inventory_layer_consumptions",
    "inventory_valuation_reversals",
    "inventory_valuation_reversal_effects",
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
    "outbox_events",
    "exceptions_queue",
    "metric_definitions",
    "metric_snapshots",
    "ops_job_history",
    "ops_error_records",
    "durable_jobs",
    "durable_job_transitions",
    "durable_job_leases",
    "durable_job_lease_events",
    "durable_job_partition_effects",
    "workflow_objects",
    "workflow_transitions",
    "workflow_transition_events",
    "legacy_import_records",
    "audit_events",
    "audit_ledger_state",
]

EXCLUDED_BACKUP_TABLES = ["api_sessions"]

BACKUP_SELECT_QUERIES = {
    "workspaces": "SELECT * FROM workspaces ORDER BY created_at, id",
    "organizations": "SELECT * FROM organizations ORDER BY created_at, id",
    "currencies": "SELECT * FROM currencies ORDER BY code",
    "legal_entities": "SELECT * FROM legal_entities ORDER BY entity_code, id",
    "branches": "SELECT * FROM branches ORDER BY organization_id, branch_code, id",
    "periods": "SELECT * FROM periods ORDER BY start_date, id",
    "units_of_measure": "SELECT * FROM units_of_measure ORDER BY workspace_id, uom_code",
    "warehouses": "SELECT * FROM warehouses ORDER BY workspace_id, organization_id, warehouse_code",
    "inventory_locations": "SELECT * FROM inventory_locations ORDER BY warehouse_id, location_code",
    "charts_of_accounts": "SELECT * FROM charts_of_accounts ORDER BY workspace_id, chart_code",
    "accounting_dimensions": "SELECT * FROM accounting_dimensions ORDER BY workspace_id, dimension_code",
    "accounting_dimension_values": "SELECT * FROM accounting_dimension_values ORDER BY dimension_id, value_code",
    "users": "SELECT * FROM users ORDER BY username",
    "roles": "SELECT * FROM roles ORDER BY name",
    "permissions": "SELECT * FROM permissions ORDER BY name",
    "user_roles": "SELECT * FROM user_roles ORDER BY user_id, role_id",
    "role_permissions": "SELECT * FROM role_permissions ORDER BY role_id, permission_name",
    "accounts": "SELECT * FROM accounts ORDER BY account_code, id",
    "ap_suppliers": "SELECT * FROM ap_suppliers ORDER BY workspace_id, supplier_code, id",
    "ap_purchase_orders": "SELECT * FROM ap_purchase_orders ORDER BY workspace_id, po_number, id",
    "ap_purchase_order_lines": "SELECT * FROM ap_purchase_order_lines ORDER BY purchase_order_id, line_number, id",
    "ap_goods_receipts": "SELECT * FROM ap_goods_receipts ORDER BY workspace_id, receipt_number, id",
    "ap_goods_receipt_lines": "SELECT * FROM ap_goods_receipt_lines ORDER BY receipt_id, id",
    "ap_supplier_invoices": "SELECT * FROM ap_supplier_invoices ORDER BY workspace_id, invoice_number, id",
    "ap_supplier_invoice_lines": "SELECT * FROM ap_supplier_invoice_lines ORDER BY supplier_invoice_id, line_number, id",
    "ap_three_way_matches": "SELECT * FROM ap_three_way_matches ORDER BY workspace_id, supplier_invoice_id, id",
    "ap_idempotency_keys": "SELECT * FROM ap_idempotency_keys ORDER BY scope, idempotency_key",
    "ar_customers": "SELECT * FROM ar_customers ORDER BY workspace_id, customer_code, id",
    "ar_invoices": "SELECT * FROM ar_invoices ORDER BY workspace_id, invoice_date, invoice_number, id",
    "ar_invoice_lines": "SELECT * FROM ar_invoice_lines ORDER BY invoice_id, line_number, id",
    "ar_receipts": "SELECT * FROM ar_receipts ORDER BY workspace_id, receipt_date, receipt_number, id",
    "ar_receipt_allocations": "SELECT * FROM ar_receipt_allocations ORDER BY workspace_id, receipt_id, invoice_id, id",
    "ar_idempotency_keys": "SELECT * FROM ar_idempotency_keys ORDER BY scope, idempotency_key",
    "inventory_items": "SELECT * FROM inventory_items ORDER BY workspace_id, item_code",
    "inventory_lots": "SELECT * FROM inventory_lots ORDER BY item_id, organization_id, lot_serial_code",
    "finance_journals": "SELECT * FROM finance_journals ORDER BY workspace_id, organization_id, journal_code",
    "ledger_entries": "SELECT * FROM ledger_entries ORDER BY workspace_id, posting_date, entry_number",
    "ledger_lines": "SELECT * FROM ledger_lines ORDER BY entry_id, line_number",
    "ledger_line_dimensions": "SELECT * FROM ledger_line_dimensions ORDER BY line_id, dimension_value_id",
    "inventory_movements": "SELECT * FROM inventory_movements ORDER BY workspace_id, movement_date, movement_number",
    "inventory_movement_lines": "SELECT * FROM inventory_movement_lines ORDER BY movement_id, line_number",
    "inventory_count_sessions": "SELECT * FROM inventory_count_sessions ORDER BY workspace_id, count_date, count_number",
    "inventory_count_lines": "SELECT * FROM inventory_count_lines ORDER BY session_id, line_number",
    "inventory_reorder_rules": "SELECT * FROM inventory_reorder_rules ORDER BY workspace_id, organization_id, legal_entity_id, item_id, location_id",
    "inventory_valuation_policies": "SELECT * FROM inventory_valuation_policies ORDER BY workspace_id, organization_id, legal_entity_id, policy_code",
    "inventory_valuation_documents": "SELECT * FROM inventory_valuation_documents ORDER BY workspace_id, valuation_date, valuation_number",
    "inventory_valuation_input_costs": "SELECT * FROM inventory_valuation_input_costs ORDER BY valuation_document_id, movement_line_id",
    "inventory_valuation_lines": "SELECT * FROM inventory_valuation_lines ORDER BY valuation_document_id, line_number",
    "inventory_cost_layers": "SELECT * FROM inventory_cost_layers ORDER BY created_at, id",
    "inventory_layer_consumptions": "SELECT * FROM inventory_layer_consumptions ORDER BY valuation_line_id, cost_layer_id",
    "inventory_valuation_reversals": "SELECT * FROM inventory_valuation_reversals ORDER BY workspace_id, reversal_date, reversal_number",
    "inventory_valuation_reversal_effects": "SELECT * FROM inventory_valuation_reversal_effects ORDER BY reversal_id, original_valuation_line_id, id",
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
    "outbox_events": "SELECT * FROM outbox_events ORDER BY created_at, id",
    "exceptions_queue": "SELECT * FROM exceptions_queue ORDER BY status, risk_rating, created_at, id",
    "metric_definitions": "SELECT * FROM metric_definitions ORDER BY metric_key",
    "metric_snapshots": "SELECT * FROM metric_snapshots ORDER BY workspace_id, period_name, metric_key",
    "ops_job_history": "SELECT * FROM ops_job_history ORDER BY started_at, id",
    "ops_error_records": "SELECT * FROM ops_error_records ORDER BY created_at, id",
    "durable_jobs": "SELECT * FROM durable_jobs ORDER BY tenant_id, workspace_id, created_at, id",
    "durable_job_transitions": "SELECT * FROM durable_job_transitions ORDER BY job_id, job_version",
    "durable_job_leases": "SELECT * FROM durable_job_leases ORDER BY tenant_id, expires_at, job_id",
    "durable_job_lease_events": "SELECT * FROM durable_job_lease_events ORDER BY job_id, event_sequence",
    "durable_job_partition_effects": "SELECT * FROM durable_job_partition_effects ORDER BY job_id, ordinal",
    "workflow_objects": "SELECT * FROM workflow_objects ORDER BY object_type, object_id",
    "workflow_transitions": "SELECT * FROM workflow_transitions ORDER BY object_type, from_status, to_status, id",
    "workflow_transition_events": "SELECT * FROM workflow_transition_events ORDER BY created_at, id",
    "legacy_import_records": "SELECT * FROM legacy_import_records ORDER BY source_type, object_type, object_id",
    "audit_events": "SELECT * FROM audit_events ORDER BY sequence",
    "audit_ledger_state": "SELECT * FROM audit_ledger_state ORDER BY id",
}

BACKUP_DELETE_QUERIES = {
    "workspaces": "DELETE FROM workspaces",
    "organizations": "DELETE FROM organizations",
    "currencies": "DELETE FROM currencies",
    "legal_entities": "DELETE FROM legal_entities",
    "branches": "DELETE FROM branches",
    "periods": "DELETE FROM periods",
    "units_of_measure": "DELETE FROM units_of_measure",
    "warehouses": "DELETE FROM warehouses",
    "inventory_locations": "DELETE FROM inventory_locations",
    "charts_of_accounts": "DELETE FROM charts_of_accounts",
    "accounting_dimensions": "DELETE FROM accounting_dimensions",
    "accounting_dimension_values": "DELETE FROM accounting_dimension_values",
    "users": "DELETE FROM users",
    "roles": "DELETE FROM roles",
    "permissions": "DELETE FROM permissions",
    "user_roles": "DELETE FROM user_roles",
    "role_permissions": "DELETE FROM role_permissions",
    "accounts": "DELETE FROM accounts",
    "ap_suppliers": "DELETE FROM ap_suppliers",
    "ap_purchase_orders": "DELETE FROM ap_purchase_orders",
    "ap_purchase_order_lines": "DELETE FROM ap_purchase_order_lines",
    "ap_goods_receipts": "DELETE FROM ap_goods_receipts",
    "ap_goods_receipt_lines": "DELETE FROM ap_goods_receipt_lines",
    "ap_supplier_invoices": "DELETE FROM ap_supplier_invoices",
    "ap_supplier_invoice_lines": "DELETE FROM ap_supplier_invoice_lines",
    "ap_three_way_matches": "DELETE FROM ap_three_way_matches",
    "ap_idempotency_keys": "DELETE FROM ap_idempotency_keys",
    "ar_customers": "DELETE FROM ar_customers",
    "ar_invoices": "DELETE FROM ar_invoices",
    "ar_invoice_lines": "DELETE FROM ar_invoice_lines",
    "ar_receipts": "DELETE FROM ar_receipts",
    "ar_receipt_allocations": "DELETE FROM ar_receipt_allocations",
    "ar_idempotency_keys": "DELETE FROM ar_idempotency_keys",
    "inventory_items": "DELETE FROM inventory_items",
    "inventory_lots": "DELETE FROM inventory_lots",
    "finance_journals": "DELETE FROM finance_journals",
    "ledger_entries": "DELETE FROM ledger_entries",
    "ledger_lines": "DELETE FROM ledger_lines",
    "ledger_line_dimensions": "DELETE FROM ledger_line_dimensions",
    "inventory_movements": "DELETE FROM inventory_movements",
    "inventory_movement_lines": "DELETE FROM inventory_movement_lines",
    "inventory_count_sessions": "DELETE FROM inventory_count_sessions",
    "inventory_count_lines": "DELETE FROM inventory_count_lines",
    "inventory_reorder_rules": "DELETE FROM inventory_reorder_rules",
    "inventory_valuation_policies": "DELETE FROM inventory_valuation_policies",
    "inventory_valuation_documents": "DELETE FROM inventory_valuation_documents",
    "inventory_valuation_input_costs": "DELETE FROM inventory_valuation_input_costs",
    "inventory_valuation_lines": "DELETE FROM inventory_valuation_lines",
    "inventory_cost_layers": "DELETE FROM inventory_cost_layers",
    "inventory_layer_consumptions": "DELETE FROM inventory_layer_consumptions",
    "inventory_valuation_reversals": "DELETE FROM inventory_valuation_reversals",
    "inventory_valuation_reversal_effects": "DELETE FROM inventory_valuation_reversal_effects",
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
    "outbox_events": "DELETE FROM outbox_events",
    "exceptions_queue": "DELETE FROM exceptions_queue",
    "metric_definitions": "DELETE FROM metric_definitions",
    "metric_snapshots": "DELETE FROM metric_snapshots",
    "ops_job_history": "DELETE FROM ops_job_history",
    "ops_error_records": "DELETE FROM ops_error_records",
    "durable_jobs": "DELETE FROM durable_jobs",
    "durable_job_transitions": "DELETE FROM durable_job_transitions",
    "durable_job_leases": "DELETE FROM durable_job_leases",
    "durable_job_lease_events": "DELETE FROM durable_job_lease_events",
    "durable_job_partition_effects": "DELETE FROM durable_job_partition_effects",
    "workflow_objects": "DELETE FROM workflow_objects",
    "workflow_transitions": "DELETE FROM workflow_transitions",
    "workflow_transition_events": "DELETE FROM workflow_transition_events",
    "legacy_import_records": "DELETE FROM legacy_import_records",
    "audit_events": "DELETE FROM audit_events",
    "audit_ledger_state": "DELETE FROM audit_ledger_state",
}

BACKUP_INSERT_COLUMNS = {
    "workspaces": ("id", "name", "local_first_note", "created_at"),
    "organizations": ("id", "workspace_id", "name", "created_at", "organization_code", "active", "updated_at"),
    "currencies": ("code", "name", "minor_units", "active", "created_at", "updated_at"),
    "legal_entities": (
        "id", "organization_id", "entity_code", "name", "currency", "created_at", "active", "updated_at",
    ),
    "branches": (
        "id", "organization_id", "legal_entity_id", "branch_code", "name", "active", "created_at", "updated_at",
    ),
    "periods": (
        "id", "workspace_id", "name", "start_date", "end_date", "status", "created_at",
        "fiscal_year", "period_number", "status_reason", "updated_at",
    ),
    "units_of_measure": (
        "id", "workspace_id", "uom_code", "name", "category", "decimal_places",
        "active", "created_at", "updated_at",
    ),
    "warehouses": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "warehouse_code",
        "name", "active", "created_at", "updated_at",
    ),
    "inventory_locations": (
        "id", "warehouse_id", "parent_location_id", "location_code", "name", "location_type",
        "allow_negative", "active", "created_at", "updated_at",
    ),
    "charts_of_accounts": (
        "id", "workspace_id", "organization_id", "chart_code", "name", "description",
        "active", "created_at", "updated_at",
    ),
    "accounting_dimensions": (
        "id", "workspace_id", "organization_id", "dimension_code", "name", "dimension_type",
        "required_on_entries", "active", "created_at", "updated_at",
    ),
    "accounting_dimension_values": (
        "id", "dimension_id", "value_code", "name", "active", "created_at", "updated_at",
    ),
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
    "accounts": (
        "id", "workspace_id", "account_code", "account_name", "created_at", "chart_id",
        "parent_account_id", "account_type", "normal_balance", "allow_posting",
         "allow_manual_posting", "reconciliation_required", "active", "description", "updated_at",
     ),
    "ap_suppliers": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "supplier_code", "name",
        "currency_code", "tax_identifier", "status", "created_at", "updated_at", "row_version",
    ),
    "ap_purchase_orders": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "branch_id", "supplier_id",
        "po_number", "order_date", "expected_date", "currency_code", "status", "created_by",
        "approved_by", "approved_at", "created_at", "updated_at", "row_version",
    ),
    "ap_purchase_order_lines": (
        "id", "purchase_order_id", "line_number", "item_code", "description", "ordered_quantity",
        "unit_price_minor", "tax_minor", "created_at",
    ),
    "ap_goods_receipts": (
        "id", "workspace_id", "purchase_order_id", "receipt_number", "receipt_date", "status",
        "created_by", "posted_by", "posted_at", "created_at", "updated_at",
    ),
    "ap_goods_receipt_lines": ("id", "receipt_id", "purchase_order_line_id", "received_quantity", "created_at"),
    "ap_supplier_invoices": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "supplier_id", "purchase_order_id",
        "invoice_number", "invoice_date", "due_date", "currency_code", "tax_minor", "total_minor",
        "status", "created_by", "approved_by", "approved_at", "created_at", "updated_at", "row_version",
    ),
    "ap_supplier_invoice_lines": (
        "id", "supplier_invoice_id", "purchase_order_line_id", "line_number", "description",
        "invoiced_quantity", "unit_price_minor", "tax_minor", "line_total_minor", "created_at",
    ),
    "ap_three_way_matches": (
        "id", "workspace_id", "supplier_invoice_id", "purchase_order_id", "status", "quantity_variance",
        "price_variance_minor", "total_variance_minor", "reason", "created_at", "updated_at",
    ),
    "ap_idempotency_keys": ("scope", "idempotency_key", "response_json", "created_at"),
    "ar_customers": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "customer_code", "name",
        "currency_code", "tax_identifier", "payment_terms_days", "credit_limit_minor", "credit_hold",
        "status", "created_at", "updated_at", "row_version",
    ),
    "ar_invoices": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "customer_id", "invoice_number",
        "invoice_date", "due_date", "currency_code", "subtotal_minor", "tax_minor", "total_minor",
        "status", "created_by", "approved_by", "approved_at", "credit_override_reason", "cancelled_by", "cancelled_at",
        "cancel_reason", "created_at", "updated_at", "row_version",
    ),
    "ar_invoice_lines": (
        "id", "invoice_id", "line_number", "description", "quantity", "unit_price_minor", "tax_minor",
        "line_total_minor", "created_at",
    ),
    "ar_receipts": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "customer_id", "receipt_number",
        "receipt_date", "currency_code", "amount_minor", "status", "created_by", "posted_by", "posted_at",
        "created_at", "updated_at", "row_version",
    ),
    "ar_receipt_allocations": ("id", "workspace_id", "receipt_id", "invoice_id", "amount_minor", "created_at"),
    "ar_idempotency_keys": ("scope", "idempotency_key", "response_json", "created_at"),
    "inventory_items": (
        "id", "workspace_id", "organization_id", "item_code", "name", "item_type",
        "tracking_mode", "uom_id", "inventory_account_id", "description", "active",
        "created_at", "updated_at",
    ),
    "inventory_lots": (
        "id", "workspace_id", "organization_id", "item_id", "lot_serial_code",
        "tracking_type", "manufactured_on", "expires_on", "active", "created_at", "updated_at",
    ),
    "finance_journals": (
        "id", "workspace_id", "organization_id", "chart_id", "journal_code", "name",
        "journal_type", "currency_code", "active", "created_at", "updated_at",
    ),
    "ledger_entries": (
        "id", "workspace_id", "organization_id", "chart_id", "legal_entity_id", "period_id",
        "finance_journal_id", "entry_number", "posting_date", "currency_code", "description",
        "external_reference", "source_type", "status", "created_by", "validated_by",
        "validated_at", "validation_reason", "voided_by", "voided_at", "void_reason",
        "created_at", "updated_at",
    ),
    "ledger_lines": (
        "id", "entry_id", "line_number", "account_id", "description",
        "debit_minor", "credit_minor", "created_at",
    ),
    "ledger_line_dimensions": ("line_id", "dimension_value_id"),
    "inventory_movements": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "period_id",
        "movement_number", "movement_type", "movement_date", "source_reference", "description",
        "source_type", "status", "created_by", "posted_by", "posted_at", "post_reason",
        "voided_by", "voided_at", "void_reason", "created_at", "updated_at",
    ),
    "inventory_movement_lines": (
        "id", "movement_id", "line_number", "item_id", "uom_id", "inventory_lot_id",
        "from_location_id", "to_location_id", "quantity_scaled", "quantity_precision",
        "description", "created_at",
    ),
    "inventory_count_sessions": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "period_id",
        "location_id", "count_number", "count_date", "description", "status",
        "created_by", "started_by", "started_at", "submitted_by", "submitted_at",
        "submit_reason", "approved_by", "approved_at", "approval_reason",
        "cancelled_by", "cancelled_at", "cancel_reason", "adjustment_movement_id",
        "created_at", "updated_at",
    ),
    "inventory_count_lines": (
        "id", "session_id", "line_number", "item_id", "uom_id", "inventory_lot_id",
        "expected_quantity_scaled", "counted_quantity_scaled", "quantity_precision",
        "count_note", "counted_by", "counted_at", "created_at",
    ),
    "inventory_reorder_rules": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "item_id",
        "location_id", "minimum_quantity_scaled", "target_quantity_scaled",
        "quantity_precision", "lead_time_days", "active", "created_by", "created_at",
        "updated_at",
    ),
    "inventory_valuation_policies": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "policy_code",
        "costing_method", "currency_code", "finance_journal_id",
        "receipt_clearing_account_id", "cogs_account_id", "adjustment_account_id",
        "active", "created_by", "created_at", "updated_at",
    ),
    "inventory_valuation_documents": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "period_id",
        "movement_id", "policy_id", "valuation_number", "valuation_date", "currency_code",
        "status", "total_value_minor", "finance_entry_id", "created_by", "approved_by",
        "approved_at", "approval_reason", "cancelled_by", "cancelled_at", "cancel_reason",
        "created_at", "updated_at",
    ),
    "inventory_valuation_input_costs": (
        "id", "valuation_document_id", "movement_line_id", "total_cost_minor", "created_at",
    ),
    "inventory_valuation_lines": (
        "id", "valuation_document_id", "movement_line_id", "line_number", "flow_direction",
        "item_id", "uom_id", "inventory_lot_id", "quantity_scaled", "quantity_precision",
        "value_minor", "inventory_account_id", "offset_account_id", "created_at",
    ),
    "inventory_cost_layers": (
        "id", "source_valuation_line_id", "legal_entity_id", "item_id", "uom_id",
        "inventory_lot_id", "quantity_precision", "original_quantity_scaled",
        "remaining_quantity_scaled", "original_value_minor", "remaining_value_minor",
        "currency_code", "created_at",
    ),
    "inventory_layer_consumptions": (
        "id", "valuation_line_id", "cost_layer_id", "quantity_scaled", "value_minor", "created_at",
    ),
    "inventory_valuation_reversals": (
        "id", "workspace_id", "organization_id", "legal_entity_id", "period_id",
        "original_valuation_document_id", "reversal_movement_id", "reversal_number",
        "reversal_date", "currency_code", "status", "total_value_minor",
        "finance_entry_id", "created_by", "approved_by", "approved_at",
        "approval_reason", "cancelled_by", "cancelled_at", "cancel_reason",
        "created_at", "updated_at",
    ),
    "inventory_valuation_reversal_effects": (
        "id", "reversal_id", "original_valuation_line_id", "original_consumption_id",
        "cost_layer_id", "effect_type", "quantity_scaled", "value_minor", "created_at",
    ),
    "reconciliations": ("id", "workspace_id", "period_id", "account_id", "reconciliation_type", "status", "owner_user_id", "created_at"),
    "tasks": ("id", "workspace_id", "period_id", "task_type", "status", "owner_user_id", "created_at"),
    "controls": ("id", "workspace_id", "control_code", "name", "status", "owner_user_id", "created_at"),
    "evidence_objects": ("id", "workspace_id", "source_path", "checksum_sha256", "provenance_type", "redaction_status", "created_at"),
    "account_reconciliation_templates": (
        "id", "workspace_id", "account_code", "name", "risk_rating", "materiality_threshold",
        "materiality_threshold_decimal",
        "required_evidence", "owner", "reviewer", "created_at", "updated_at",
    ),
    "trial_balance_rows": (
        "id", "workspace_id", "period_name", "entity_code", "account_code", "account_name",
        "balance", "balance_decimal", "currency", "source_path", "source_row_number", "imported_at",
    ),
    "account_reconciliation_records": (
        "id", "workspace_id", "period_name", "entity_code", "account_code", "account_name",
        "template_id", "status", "balance", "balance_decimal", "materiality_threshold",
        "materiality_threshold_decimal", "currency_code", "risk_rating", "owner",
        "preparer", "reviewer", "prepared_at", "submitted_at", "reviewed_at", "completed_at",
        "aging_days", "created_at", "updated_at",
    ),
    "account_reconciliation_items": (
        "id", "reconciliation_id", "item_type", "description", "amount", "amount_decimal", "status",
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
        "provenance_type", "redaction_status", "evidence_status", "storage_backend",
        "storage_tenant_id", "storage_key", "storage_version_id", "content_type", "byte_size",
        "retention_until", "registered_by", "created_at", "updated_at",
    ),
    "evidence_requirements": (
        "id", "workspace_id", "object_type", "object_id", "requirement_code",
        "description", "required_status", "created_at",
    ),
    "evidence_links": ("id", "evidence_id", "object_type", "object_id", "link_type", "created_at"),
    "journal_entries": (
        "id", "workspace_id", "journal_id", "period_name", "entity_code", "posting_date",
        "account_code", "amount", "amount_decimal", "currency", "reference", "approver", "is_manual",
        "source_path", "imported_at",
    ),
    "journal_exceptions": ("id", "journal_entry_id", "policy_code", "risk_rating", "description", "status", "created_at"),
    "intercompany_transactions": (
        "id", "workspace_id", "transaction_id", "period_name", "entity_code",
        "counterparty_code", "posting_date", "amount", "amount_decimal", "currency", "reference",
        "source_path", "imported_at",
    ),
    "intercompany_cases": (
        "id", "workspace_id", "period_name", "entity_code", "counterparty_code",
        "reference", "imbalance_amount", "imbalance_amount_decimal", "currency", "status", "dispute_owner",
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
        "explanation", "amount_difference", "amount_difference_decimal", "date_difference_days", "status", "reason_code", "lineage_json", "created_at",
    ),
    "outbox_events": (
        "id", "event_type", "aggregate_type", "aggregate_id", "payload_json",
        "created_at", "published_at", "attempts", "last_error", "available_at",
        "locked_at", "locked_by", "dead_lettered_at",
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
    "durable_jobs": (
        "id", "schema_version", "version", "status", "idempotency_scope", "idempotency_key",
        "tenant_id", "workspace_id", "entity_id", "input_digest", "config_digest", "worker_version",
        "completed_units", "total_units", "checkpoint_digest", "retry_count", "retry_ceiling",
        "safe_error_code", "created_at", "updated_at", "started_at", "completed_at",
        "output_manifest_schema_version", "output_manifest_digest", "output_manifest_reference",
    ),
    "durable_job_transitions": (
        "job_id", "job_version", "from_status", "to_status", "actor_id", "occurred_at", "reason_code",
    ),
    "durable_job_leases": (
        "job_id", "tenant_id", "owner_id", "generation", "acquired_at", "renewed_at", "expires_at",
    ),
    "durable_job_lease_events": (
        "job_id", "event_sequence", "generation", "action", "owner_id", "occurred_at", "expires_at",
    ),
    "durable_job_partition_effects": (
        "job_id", "partition_key", "ordinal", "completed_units", "input_digest", "output_digest",
        "effect_reference", "committed_at", "job_version",
    ),
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
    "workspaces": "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES (?, ?, ?, ?)",
    "organizations": """
        INSERT INTO organizations (
            id, workspace_id, name, created_at, organization_code, active, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "currencies": """
        INSERT INTO currencies (code, name, minor_units, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    "legal_entities": """
        INSERT INTO legal_entities (
            id, organization_id, entity_code, name, currency, created_at, active, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "branches": """
        INSERT INTO branches (
            id, organization_id, legal_entity_id, branch_code, name, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "periods": """
        INSERT INTO periods (
            id, workspace_id, name, start_date, end_date, status, created_at,
            fiscal_year, period_number, status_reason, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "units_of_measure": """
        INSERT INTO units_of_measure (
            id, workspace_id, uom_code, name, category, decimal_places,
            active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "warehouses": """
        INSERT INTO warehouses (
            id, workspace_id, organization_id, legal_entity_id, warehouse_code,
            name, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_locations": """
        INSERT INTO inventory_locations (
            id, warehouse_id, parent_location_id, location_code, name, location_type,
            allow_negative, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "charts_of_accounts": """
        INSERT INTO charts_of_accounts (
            id, workspace_id, organization_id, chart_code, name, description,
            active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "accounting_dimensions": """
        INSERT INTO accounting_dimensions (
            id, workspace_id, organization_id, dimension_code, name, dimension_type,
            required_on_entries, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "accounting_dimension_values": """
        INSERT INTO accounting_dimension_values (
            id, dimension_id, value_code, name, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
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
    "accounts": """
        INSERT INTO accounts (
            id, workspace_id, account_code, account_name, created_at, chart_id,
            parent_account_id, account_type, normal_balance, allow_posting,
            allow_manual_posting, reconciliation_required, active, description, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_suppliers": """
        INSERT INTO ap_suppliers (
            id, workspace_id, organization_id, legal_entity_id, supplier_code, name,
            currency_code, tax_identifier, status, created_at, updated_at, row_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_purchase_orders": """
        INSERT INTO ap_purchase_orders (
            id, workspace_id, organization_id, legal_entity_id, branch_id, supplier_id,
            po_number, order_date, expected_date, currency_code, status, created_by,
            approved_by, approved_at, created_at, updated_at, row_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_purchase_order_lines": """
        INSERT INTO ap_purchase_order_lines (
            id, purchase_order_id, line_number, item_code, description, ordered_quantity,
            unit_price_minor, tax_minor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_goods_receipts": """
        INSERT INTO ap_goods_receipts (
            id, workspace_id, purchase_order_id, receipt_number, receipt_date, status,
            created_by, posted_by, posted_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_goods_receipt_lines": """
        INSERT INTO ap_goods_receipt_lines (
            id, receipt_id, purchase_order_line_id, received_quantity, created_at
        ) VALUES (?, ?, ?, ?, ?)
    """,
    "ap_supplier_invoices": """
        INSERT INTO ap_supplier_invoices (
            id, workspace_id, organization_id, legal_entity_id, supplier_id, purchase_order_id,
            invoice_number, invoice_date, due_date, currency_code, tax_minor, total_minor,
            status, created_by, approved_by, approved_at, created_at, updated_at, row_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_supplier_invoice_lines": """
        INSERT INTO ap_supplier_invoice_lines (
            id, supplier_invoice_id, purchase_order_line_id, line_number, description,
            invoiced_quantity, unit_price_minor, tax_minor, line_total_minor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_three_way_matches": """
        INSERT INTO ap_three_way_matches (
            id, workspace_id, supplier_invoice_id, purchase_order_id, status, quantity_variance,
            price_variance_minor, total_variance_minor, reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ap_idempotency_keys": """
        INSERT INTO ap_idempotency_keys (scope, idempotency_key, response_json, created_at)
        VALUES (?, ?, ?, ?)
    """,
    "ar_customers": """
        INSERT INTO ar_customers (
            id, workspace_id, organization_id, legal_entity_id, customer_code, name,
            currency_code, tax_identifier, payment_terms_days, credit_limit_minor, credit_hold,
            status, created_at, updated_at, row_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ar_invoices": """
        INSERT INTO ar_invoices (
            id, workspace_id, organization_id, legal_entity_id, customer_id, invoice_number,
            invoice_date, due_date, currency_code, subtotal_minor, tax_minor, total_minor,
            status, created_by, approved_by, approved_at, credit_override_reason, cancelled_by, cancelled_at, cancel_reason,
            created_at, updated_at, row_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ar_invoice_lines": """
        INSERT INTO ar_invoice_lines (
            id, invoice_id, line_number, description, quantity, unit_price_minor, tax_minor,
            line_total_minor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ar_receipts": """
        INSERT INTO ar_receipts (
            id, workspace_id, organization_id, legal_entity_id, customer_id, receipt_number,
            receipt_date, currency_code, amount_minor, status, created_by, posted_by, posted_at,
            created_at, updated_at, row_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ar_receipt_allocations": """
        INSERT INTO ar_receipt_allocations (id, workspace_id, receipt_id, invoice_id, amount_minor, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    "ar_idempotency_keys": """
        INSERT INTO ar_idempotency_keys (scope, idempotency_key, response_json, created_at)
        VALUES (?, ?, ?, ?)
    """,
    "inventory_items": """
        INSERT INTO inventory_items (
            id, workspace_id, organization_id, item_code, name, item_type,
            tracking_mode, uom_id, inventory_account_id, description, active,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_lots": """
        INSERT INTO inventory_lots (
            id, workspace_id, organization_id, item_id, lot_serial_code,
            tracking_type, manufactured_on, expires_on, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "finance_journals": """
        INSERT INTO finance_journals (
            id, workspace_id, organization_id, chart_id, journal_code, name,
            journal_type, currency_code, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ledger_entries": """
        INSERT INTO ledger_entries (
            id, workspace_id, organization_id, chart_id, legal_entity_id, period_id,
            finance_journal_id, entry_number, posting_date, currency_code, description,
            external_reference, source_type, status, created_by, validated_by,
            validated_at, validation_reason, voided_by, voided_at, void_reason,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ledger_lines": """
        INSERT INTO ledger_lines (
            id, entry_id, line_number, account_id, description,
            debit_minor, credit_minor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "ledger_line_dimensions": """
        INSERT INTO ledger_line_dimensions (line_id, dimension_value_id) VALUES (?, ?)
    """,
    "inventory_movements": """
        INSERT INTO inventory_movements (
            id, workspace_id, organization_id, legal_entity_id, period_id,
            movement_number, movement_type, movement_date, source_reference, description,
            source_type, status, created_by, posted_by, posted_at, post_reason,
            voided_by, voided_at, void_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_movement_lines": """
        INSERT INTO inventory_movement_lines (
            id, movement_id, line_number, item_id, uom_id, inventory_lot_id,
            from_location_id, to_location_id, quantity_scaled, quantity_precision,
            description, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_count_sessions": """
        INSERT INTO inventory_count_sessions (
            id, workspace_id, organization_id, legal_entity_id, period_id,
            location_id, count_number, count_date, description, status,
            created_by, started_by, started_at, submitted_by, submitted_at,
            submit_reason, approved_by, approved_at, approval_reason,
            cancelled_by, cancelled_at, cancel_reason, adjustment_movement_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_count_lines": """
        INSERT INTO inventory_count_lines (
            id, session_id, line_number, item_id, uom_id, inventory_lot_id,
            expected_quantity_scaled, counted_quantity_scaled, quantity_precision,
            count_note, counted_by, counted_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_reorder_rules": """
        INSERT INTO inventory_reorder_rules (
            id, workspace_id, organization_id, legal_entity_id, item_id,
            location_id, minimum_quantity_scaled, target_quantity_scaled,
            quantity_precision, lead_time_days, active, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_valuation_policies": """
        INSERT INTO inventory_valuation_policies (
            id, workspace_id, organization_id, legal_entity_id, policy_code,
            costing_method, currency_code, finance_journal_id,
            receipt_clearing_account_id, cogs_account_id, adjustment_account_id,
            active, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_valuation_documents": """
        INSERT INTO inventory_valuation_documents (
            id, workspace_id, organization_id, legal_entity_id, period_id,
            movement_id, policy_id, valuation_number, valuation_date, currency_code,
            status, total_value_minor, finance_entry_id, created_by, approved_by,
            approved_at, approval_reason, cancelled_by, cancelled_at, cancel_reason,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_valuation_input_costs": """
        INSERT INTO inventory_valuation_input_costs (
            id, valuation_document_id, movement_line_id, total_cost_minor, created_at
        ) VALUES (?, ?, ?, ?, ?)
    """,
    "inventory_valuation_lines": """
        INSERT INTO inventory_valuation_lines (
            id, valuation_document_id, movement_line_id, line_number, flow_direction,
            item_id, uom_id, inventory_lot_id, quantity_scaled, quantity_precision,
            value_minor, inventory_account_id, offset_account_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_cost_layers": """
        INSERT INTO inventory_cost_layers (
            id, source_valuation_line_id, legal_entity_id, item_id, uom_id,
            inventory_lot_id, quantity_precision, original_quantity_scaled,
            remaining_quantity_scaled, original_value_minor, remaining_value_minor,
            currency_code, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_layer_consumptions": """
        INSERT INTO inventory_layer_consumptions (
            id, valuation_line_id, cost_layer_id, quantity_scaled, value_minor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """,
    "inventory_valuation_reversals": """
        INSERT INTO inventory_valuation_reversals (
            id, workspace_id, organization_id, legal_entity_id, period_id,
            original_valuation_document_id, reversal_movement_id, reversal_number,
            reversal_date, currency_code, status, total_value_minor, finance_entry_id,
            created_by, approved_by, approved_at, approval_reason,
            cancelled_by, cancelled_at, cancel_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "inventory_valuation_reversal_effects": """
        INSERT INTO inventory_valuation_reversal_effects (
            id, reversal_id, original_valuation_line_id, original_consumption_id,
            cost_layer_id, effect_type, quantity_scaled, value_minor, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
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
            materiality_threshold_decimal,
            required_evidence, owner, reviewer, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "trial_balance_rows": """
        INSERT INTO trial_balance_rows (
            id, workspace_id, period_name, entity_code, account_code, account_name,
            balance, balance_decimal, currency, source_path, source_row_number, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "account_reconciliation_records": """
        INSERT INTO account_reconciliation_records (
            id, workspace_id, period_name, entity_code, account_code, account_name,
            template_id, status, balance, balance_decimal, materiality_threshold,
            materiality_threshold_decimal, currency_code, risk_rating, owner,
            preparer, reviewer, prepared_at, submitted_at, reviewed_at, completed_at,
            aging_days, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "account_reconciliation_items": """
        INSERT INTO account_reconciliation_items (
            id, reconciliation_id, item_type, description, amount, amount_decimal, status,
            evidence_required, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            provenance_type, redaction_status, evidence_status, storage_backend,
            storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
            retention_until, registered_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            account_code, amount, amount_decimal, currency, reference, approver, is_manual,
            source_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            counterparty_code, posting_date, amount, amount_decimal, currency, reference,
            source_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "intercompany_cases": """
        INSERT INTO intercompany_cases (
            id, workspace_id, period_name, entity_code, counterparty_code,
            reference, imbalance_amount, imbalance_amount_decimal, currency, status, dispute_owner,
            settlement_status, aging_days, evidence_note, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            explanation, amount_difference, amount_difference_decimal,
            date_difference_days, status, reason_code, lineage_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "outbox_events": """
        INSERT INTO outbox_events (
            id, event_type, aggregate_type, aggregate_id, payload_json,
            created_at, published_at, attempts, last_error, available_at,
            locked_at, locked_by, dead_lettered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    "durable_jobs": """
        INSERT INTO durable_jobs (
            id, schema_version, version, status, idempotency_scope, idempotency_key,
            tenant_id, workspace_id, entity_id, input_digest, config_digest, worker_version,
            completed_units, total_units, checkpoint_digest, retry_count, retry_ceiling,
            safe_error_code, created_at, updated_at, started_at, completed_at,
            output_manifest_schema_version, output_manifest_digest, output_manifest_reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    "durable_job_transitions": """
        INSERT INTO durable_job_transitions (
            job_id, job_version, from_status, to_status, actor_id, occurred_at, reason_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "durable_job_leases": """
        INSERT INTO durable_job_leases (
            job_id, tenant_id, owner_id, generation, acquired_at, renewed_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "durable_job_lease_events": """
        INSERT INTO durable_job_lease_events (
            job_id, event_sequence, generation, action, owner_id, occurred_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    "durable_job_partition_effects": """
        INSERT INTO durable_job_partition_effects (
            job_id, partition_key, ordinal, completed_units, input_digest,
            output_digest, effect_reference, committed_at, job_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _path_is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DBBridgeError("Backup JSON could not be parsed.") from exc
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_attribute)


def _bounded_json_checksum(path: Path) -> tuple[str, int]:
    if _path_is_reparse(path):
        raise DBBridgeError("Backup JSON could not be parsed.")
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise DBBridgeError("Backup JSON could not be parsed.")
        if metadata.st_size > BACKUP_JSON_POLICY.max_file_bytes:
            raise StructuredDocumentError("document_size_limit")
        digest = sha256()
        total = 0
        with path.open("rb") as handle:
            if os.fstat(handle.fileno()).st_size != metadata.st_size:
                raise StructuredDocumentError("document_size_changed")
            for chunk in iter(lambda: handle.read(_BACKUP_READ_CHUNK_BYTES), b""):
                total += len(chunk)
                if total > BACKUP_JSON_POLICY.max_file_bytes:
                    raise StructuredDocumentError("document_size_limit")
                digest.update(chunk)
            if total != metadata.st_size or os.fstat(handle.fileno()).st_size != metadata.st_size:
                raise StructuredDocumentError("document_size_changed")
    except DBBridgeError:
        raise
    except StructuredDocumentError as exc:
        raise DBBridgeError("Backup JSON could not be parsed.") from exc
    except OSError as exc:
        raise DBBridgeError("Backup JSON could not be parsed.") from exc
    return digest.hexdigest(), total


def _read_json_file(path: Path) -> tuple[dict[str, Any], str, int]:
    before_checksum, before_size = _bounded_json_checksum(path)
    try:
        payload = read_json_document(path, policy=BACKUP_JSON_POLICY)
    except (OSError, StructuredDocumentError) as exc:
        raise DBBridgeError("Backup JSON could not be parsed.") from exc
    if not isinstance(payload, dict):
        raise DBBridgeError("Backup JSON must contain an object.")
    after_checksum, after_size = _bounded_json_checksum(path)
    if before_checksum != after_checksum or before_size != after_size:
        raise DBBridgeError("Backup JSON changed during validation.")
    return payload, after_checksum, after_size


def _strict_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _validate_manifest_document(
    manifest: dict[str, Any],
) -> tuple[str, int, int]:
    required_keys = {
        "manifest_version",
        "created_at",
        "schema_version",
        "privacy_warning",
        "artifacts",
    }
    artifacts = manifest.get("artifacts")
    artifact = artifacts.get("backup.json") if isinstance(artifacts, dict) else None
    schema_version = _strict_positive_int(manifest.get("schema_version"))
    manifest_version = _strict_positive_int(manifest.get("manifest_version"))
    if (
        set(manifest) != required_keys
        or manifest_version != 1
        or not isinstance(manifest.get("created_at"), str)
        or not manifest["created_at"]
        or schema_version is None
        or schema_version > MIGRATIONS[-1].version
        or not isinstance(manifest.get("privacy_warning"), str)
        or not manifest["privacy_warning"]
        or not isinstance(artifacts, dict)
        or set(artifacts) != {"backup.json"}
        or not isinstance(artifact, dict)
        or set(artifact) != {"sha256", "bytes"}
    ):
        raise DBBridgeError("Backup manifest is invalid.")
    checksum = artifact.get("sha256")
    byte_count = artifact.get("bytes")
    if (
        not isinstance(checksum, str)
        or _SHA256_RE.fullmatch(checksum) is None
        or isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
        or byte_count > BACKUP_JSON_POLICY.max_file_bytes
    ):
        raise DBBridgeError("Backup manifest is invalid.")
    return checksum, byte_count, schema_version


def _validate_backup_document(backup: dict[str, Any]) -> int:
    required_keys = {
        "backup_format_version",
        "created_at",
        "schema_version",
        "latest_supported_schema_version",
        "privacy_warning",
        "restore_sensitive_material",
        "excluded_tables",
        "tables",
    }
    schema_version = _strict_positive_int(backup.get("schema_version"))
    format_version = _strict_positive_int(backup.get("backup_format_version"))
    latest_supported = _strict_positive_int(backup.get("latest_supported_schema_version"))
    tables = backup.get("tables")
    excluded_tables = backup.get("excluded_tables")
    if (
        set(backup) != required_keys
        or format_version != BACKUP_FORMAT_VERSION
        or not isinstance(backup.get("created_at"), str)
        or not backup["created_at"]
        or schema_version is None
        or schema_version > MIGRATIONS[-1].version
        or latest_supported is None
        or latest_supported < schema_version
        or latest_supported > MIGRATIONS[-1].version
        or not isinstance(backup.get("privacy_warning"), str)
        or not backup["privacy_warning"]
        or not isinstance(backup.get("restore_sensitive_material"), str)
        or not backup["restore_sensitive_material"]
        or excluded_tables != EXCLUDED_BACKUP_TABLES
        or not isinstance(tables, dict)
        or not set(tables).issubset(BACKUP_TABLES)
    ):
        raise DBBridgeError("Backup document is invalid.")
    for table, rows in tables.items():
        if not isinstance(table, str) or not isinstance(rows, list):
            raise DBBridgeError("Backup table payload is invalid.")
        for row in rows:
            if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
                raise DBBridgeError("Backup table row is invalid.")
    return schema_version


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
        ensure_outbox_schema(connection)
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
    manifest, _manifest_checksum, _manifest_size = _read_json_file(manifest_path)
    backup, actual_checksum, actual_bytes = _read_json_file(backup_path)
    expected_checksum, expected_bytes, manifest_schema_version = _validate_manifest_document(
        manifest
    )
    if actual_checksum != expected_checksum or actual_bytes != expected_bytes:
        raise DBBridgeError("Backup checksum verification failed.")
    schema_version = _validate_backup_document(backup)
    if (
        schema_version != manifest_schema_version
        or backup["created_at"] != manifest["created_at"]
        or backup["privacy_warning"] != manifest["privacy_warning"]
    ):
        raise DBBridgeError("Backup manifest does not match the backup document.")
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


def _legacy_organization_code(row: dict[str, Any]) -> str:
    digest = sha256(str(row.get("id", "legacy")).encode("utf-8")).hexdigest()[:12].upper()
    return f"LEGACY-{digest}"


def _restore_row_defaults(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Fill additive fields when restoring a backup created before schema version 7."""

    restored = dict(row)
    if table == "organizations":
        restored.setdefault("organization_code", _legacy_organization_code(restored))
        restored.setdefault("active", 1)
        restored.setdefault("updated_at", restored.get("created_at", ""))
    elif table == "legal_entities":
        restored.setdefault("active", 1)
        restored.setdefault("updated_at", restored.get("created_at", ""))
    elif table == "periods":
        start_date = str(restored.get("start_date", ""))
        restored.setdefault("fiscal_year", int(start_date[:4]) if start_date[:4].isdigit() else 0)
        restored.setdefault("period_number", int(start_date[5:7]) if start_date[5:7].isdigit() else 0)
        restored.setdefault("status_reason", "")
        restored.setdefault("updated_at", restored.get("created_at", ""))
    return restored


def _quote_identifier(value: str, *, kind: str) -> str:
    identifier = str(value).strip()
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise DBBridgeError(f"Invalid {kind} identifier.")
    return f'"{identifier}"'


def _table_info_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    quoted_table = _quote_identifier(table, kind="table")
    return {
        str(column["name"])
        for column in connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
    }


def _table_info_definitions(connection: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    quoted_table = _quote_identifier(table, kind="table")
    return {
        str(column["name"]): {
            "notnull": bool(column["notnull"]),
            "default": column["dflt_value"],
        }
        for column in connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
    }


def _build_insert_query(table: str, columns: tuple[str, ...]) -> str:
    quoted_table = _quote_identifier(table, kind="table")
    quoted_columns = ", ".join(_quote_identifier(column, kind="column") for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    # Table and column identifiers are validated against _IDENTIFIER_RE via _quote_identifier.
    return f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"  # nosec B608


def _insert_rows(connection: sqlite3.Connection, *, table: str, rows: object) -> None:
    if rows is None:
        return
    if not isinstance(rows, list):
        raise DBBridgeError("Backup table rows are invalid.")
    if not rows:
        return
    if not _table_exists(connection, table):
        raise DBBridgeError(f"Backup table is not supported by this ReconForge version: {table}.")
    columns = BACKUP_INSERT_COLUMNS.get(table)
    preferred_query = BACKUP_INSERT_QUERIES.get(table)
    if columns is None or preferred_query is None:
        raise DBBridgeError("Unsupported restore table.")
    actual_columns = _table_info_columns(connection, table)
    table_definitions = _table_info_definitions(connection, table)

    insert_columns = tuple(column for column in columns if column in actual_columns)
    if not insert_columns:
        raise DBBridgeError(f"Backup table row does not contain supported columns: {table}.")

    for row in rows:
        if not isinstance(row, dict):
            raise DBBridgeError("Backup table row is invalid.")
        if not row:
            continue
        restored_row = _restore_row_defaults(table, row)
        unknown_columns = set(restored_row) - set(columns)
        if unknown_columns:
            raise DBBridgeError(f"Backup table contains unsupported columns: {table}.")
        row_insert_columns: list[str] = []
        values: list[Any] = []
        for column in insert_columns:
            if column in restored_row:
                row_insert_columns.append(column)
                values.append(restored_row[column])
                continue
            definition = table_definitions.get(column, {})
            if definition.get("default") is not None:
                # Omit the column so SQLite evaluates its declared default.
                # Parsing SQL defaults in Python can change exact numeric text,
                # timestamps, or expressions before the database sees them.
                continue
            elif definition.get("notnull"):
                raise DBBridgeError(f"Backup row omits required column: {table}.{column}.")
        if not row_insert_columns:
            raise DBBridgeError(f"Backup table row does not contain supported columns: {table}.")
        if len(values) != len(row_insert_columns):
            raise DBBridgeError(f"Backup row insert value mismatch: {table}.")
        selected_columns = tuple(row_insert_columns)
        query = preferred_query if selected_columns == columns else _build_insert_query(table, selected_columns)
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
    ledger_statuses: list[tuple[str, str]] = []
    inventory_statuses: list[tuple[str, str]] = []
    count_statuses: list[tuple[str, str, bool, bool]] = []
    count_line_results: list[tuple[str, object, object, object, object]] = []
    valuation_statuses: list[tuple[str, str, object, object, str, str]] = []
    reversal_statuses: list[tuple[str, str, object, object, str, str]] = []
    try:
        backup_schema_version = int(backup["schema_version"])
        run_migrations(temp_path, target_version=backup_schema_version)
        connection = connect(temp_path, require_exists=True)
        try:
            ensure_outbox_schema(connection)
            _clear_restore_tables(connection)
            tables = backup["tables"]
            if not isinstance(tables, dict):
                raise DBBridgeError("Backup table payload is invalid.")
            for table in BACKUP_TABLES:
                rows = tables.get(table, [])
                if table == "ledger_entries" and isinstance(rows, list):
                    draft_rows: list[object] = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise DBBridgeError("Backup table row is invalid.")
                        status = str(row.get("status", "Draft"))
                        if status not in {"Draft", "Validated", "Voided"}:
                            raise DBBridgeError("Backup contains an invalid ledger-entry status.")
                        ledger_statuses.append((str(row.get("id", "")), status))
                        draft_rows.append({**row, "status": "Draft"})
                    rows = draft_rows
                if table == "inventory_movements" and isinstance(rows, list):
                    draft_rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise DBBridgeError("Backup table row is invalid.")
                        status = str(row.get("status", "Draft"))
                        if status not in {"Draft", "Posted", "Voided"}:
                            raise DBBridgeError("Backup contains an invalid inventory-movement status.")
                        inventory_statuses.append((str(row.get("id", "")), status))
                        draft_rows.append({**row, "status": "Draft"})
                    rows = draft_rows
                if table == "inventory_count_sessions" and isinstance(rows, list):
                    draft_rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise DBBridgeError("Backup table row is invalid.")
                        status = str(row.get("status", "Draft"))
                        if status not in {"Draft", "Counting", "Submitted", "Approved", "Cancelled"}:
                            raise DBBridgeError("Backup contains an invalid inventory-count status.")
                        count_statuses.append(
                            (
                                str(row.get("id", "")),
                                status,
                                bool(row.get("started_at")),
                                bool(row.get("submitted_at")),
                            )
                        )
                        draft_rows.append({**row, "status": "Draft"})
                    rows = draft_rows
                if table == "inventory_count_lines" and isinstance(rows, list):
                    draft_rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise DBBridgeError("Backup table row is invalid.")
                        result = (
                            str(row.get("id", "")),
                            row.get("counted_quantity_scaled"),
                            row.get("count_note", ""),
                            row.get("counted_by", ""),
                            row.get("counted_at"),
                        )
                        if any(value not in {None, ""} for value in result[1:]):
                            count_line_results.append(result)
                        draft_rows.append(
                            {
                                **row,
                                "counted_quantity_scaled": None,
                                "count_note": "",
                                "counted_by": "",
                                "counted_at": None,
                            }
                        )
                    rows = draft_rows
                if table == "inventory_valuation_documents" and isinstance(rows, list):
                    draft_rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise DBBridgeError("Backup table row is invalid.")
                        status = str(row.get("status", "Draft"))
                        if status not in {"Draft", "Approved", "Cancelled"}:
                            raise DBBridgeError("Backup contains an invalid inventory-valuation status.")
                        valuation_statuses.append(
                            (
                                str(row.get("id", "")),
                                status,
                                row.get("total_value_minor", 0),
                                row.get("finance_entry_id"),
                                str(row.get("valuation_date", "")),
                                str(row.get("valuation_number", "")),
                            )
                        )
                        draft_rows.append(
                            {
                                **row,
                                "status": "Draft",
                                "total_value_minor": 0,
                                "finance_entry_id": None,
                            }
                        )
                    rows = draft_rows
                if table == "inventory_valuation_reversals" and isinstance(rows, list):
                    draft_rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            raise DBBridgeError("Backup table row is invalid.")
                        status = str(row.get("status", "Draft"))
                        if status not in {"Draft", "Approved", "Cancelled"}:
                            raise DBBridgeError(
                                "Backup contains an invalid inventory-valuation reversal status."
                            )
                        reversal_statuses.append(
                            (
                                str(row.get("id", "")),
                                status,
                                row.get("total_value_minor", 0),
                                row.get("finance_entry_id"),
                                str(row.get("reversal_date", "")),
                                str(row.get("reversal_number", "")),
                            )
                        )
                        draft_rows.append(
                            {
                                **row,
                                "status": "Draft",
                                "total_value_minor": 0,
                                "finance_entry_id": None,
                            }
                        )
                    rows = draft_rows
                _insert_rows(connection, table=table, rows=rows)
                restored_tables.append(table)
            protected_finance_ids = {
                str(finance_entry_id)
                for _id, _status, _total, finance_entry_id, _date, _number in (
                    valuation_statuses + reversal_statuses
                )
                if finance_entry_id
            }
            for entry_id, status in ledger_statuses:
                if entry_id in protected_finance_ids:
                    continue
                if status in {"Validated", "Voided"}:
                    connection.execute(
                        "UPDATE ledger_entries SET status = 'Validated' WHERE id = ? AND status = 'Draft'",
                        (entry_id,),
                    )
                if status == "Voided":
                    connection.execute(
                        "UPDATE ledger_entries SET status = 'Voided' WHERE id = ? AND status = 'Validated'",
                        (entry_id,),
                    )
            for movement_id, status in inventory_statuses:
                if status in {"Posted", "Voided"}:
                    connection.execute(
                        "UPDATE inventory_movements SET status = 'Posted' WHERE id = ? AND status = 'Draft'",
                        (movement_id,),
                    )
                if status == "Voided":
                    connection.execute(
                        "UPDATE inventory_movements SET status = 'Voided' WHERE id = ? AND status = 'Posted'",
                        (movement_id,),
                    )
            for session_id, status, was_started, _was_submitted in count_statuses:
                if status in {"Counting", "Submitted", "Approved"} or (status == "Cancelled" and was_started):
                    connection.execute(
                        "UPDATE inventory_count_sessions SET status = 'Counting' WHERE id = ? AND status = 'Draft'",
                        (session_id,),
                    )
            for line_id, quantity, note, counted_by, counted_at in count_line_results:
                connection.execute(
                    """
                    UPDATE inventory_count_lines
                    SET counted_quantity_scaled = ?, count_note = ?, counted_by = ?, counted_at = ?
                    WHERE id = ?
                    """,
                    (quantity, note, counted_by, counted_at, line_id),
                )
            for session_id, status, _was_started, was_submitted in count_statuses:
                if status in {"Submitted", "Approved"} or (status == "Cancelled" and was_submitted):
                    connection.execute(
                        "UPDATE inventory_count_sessions SET status = 'Submitted' WHERE id = ? AND status = 'Counting'",
                        (session_id,),
                    )
                if status == "Approved":
                    connection.execute(
                        "UPDATE inventory_count_sessions SET status = 'Approved' WHERE id = ? AND status = 'Submitted'",
                        (session_id,),
                    )
                if status == "Cancelled":
                    connection.execute(
                        "UPDATE inventory_count_sessions SET status = 'Cancelled' WHERE id = ?",
                        (session_id,),
                    )
            for document_id, status, total_value, finance_entry_id, _date, _number in sorted(
                valuation_statuses, key=lambda item: (item[4], item[5], item[0])
            ):
                if status == "Approved":
                    connection.execute(
                        """
                        UPDATE inventory_valuation_documents
                        SET status = 'Approved', total_value_minor = ?, finance_entry_id = ?
                        WHERE id = ? AND status = 'Draft'
                        """,
                        (total_value, finance_entry_id, document_id),
                    )
                if status == "Cancelled":
                    connection.execute(
                        """
                        UPDATE inventory_valuation_documents
                        SET status = 'Cancelled' WHERE id = ? AND status = 'Draft'
                        """,
                        (document_id,),
                    )
            for reversal_id, status, total_value, finance_entry_id, _date, _number in sorted(
                reversal_statuses, key=lambda item: (item[4], item[5], item[0])
            ):
                if status == "Approved":
                    connection.execute(
                        """
                        UPDATE inventory_valuation_reversals
                        SET status = 'Approved', total_value_minor = ?, finance_entry_id = ?
                        WHERE id = ? AND status = 'Draft'
                        """,
                        (total_value, finance_entry_id, reversal_id),
                    )
                if status == "Cancelled":
                    connection.execute(
                        """
                        UPDATE inventory_valuation_reversals
                        SET status = 'Cancelled' WHERE id = ? AND status = 'Draft'
                        """,
                        (reversal_id,),
                    )
            for entry_id, status in ledger_statuses:
                if entry_id not in protected_finance_ids:
                    continue
                if status in {"Validated", "Voided"}:
                    connection.execute(
                        "UPDATE ledger_entries SET status = 'Validated' WHERE id = ? AND status = 'Draft'",
                        (entry_id,),
                    )
                if status == "Voided":
                    connection.execute(
                        "UPDATE ledger_entries SET status = 'Voided' WHERE id = ? AND status = 'Validated'",
                        (entry_id,),
                    )
            if backup_schema_version >= 11:
                if backup_schema_version >= 12:
                    layer_balance_issue = connection.execute(
                        """
                        SELECT layers.id
                        FROM inventory_cost_layers layers
                        WHERE layers.remaining_quantity_scaled
                            <> layers.original_quantity_scaled - COALESCE((
                                SELECT SUM(consumptions.quantity_scaled)
                                FROM inventory_layer_consumptions consumptions
                                WHERE consumptions.cost_layer_id = layers.id
                            ), 0) + COALESCE((
                                SELECT SUM(CASE effects.effect_type
                                    WHEN 'Restore' THEN effects.quantity_scaled
                                    ELSE -effects.quantity_scaled END)
                                FROM inventory_valuation_reversal_effects effects
                                WHERE effects.cost_layer_id = layers.id
                            ), 0)
                           OR layers.remaining_value_minor
                            <> layers.original_value_minor - COALESCE((
                                SELECT SUM(consumptions.value_minor)
                                FROM inventory_layer_consumptions consumptions
                                WHERE consumptions.cost_layer_id = layers.id
                            ), 0) + COALESCE((
                                SELECT SUM(CASE effects.effect_type
                                    WHEN 'Restore' THEN effects.value_minor
                                    ELSE -effects.value_minor END)
                                FROM inventory_valuation_reversal_effects effects
                                WHERE effects.cost_layer_id = layers.id
                            ), 0)
                        LIMIT 1
                        """
                    ).fetchone()
                else:
                    layer_balance_issue = connection.execute(
                        """
                        SELECT layers.id
                        FROM inventory_cost_layers layers
                        WHERE layers.original_quantity_scaled - layers.remaining_quantity_scaled
                            <> COALESCE((
                                SELECT SUM(consumptions.quantity_scaled)
                                FROM inventory_layer_consumptions consumptions
                                WHERE consumptions.cost_layer_id = layers.id
                            ), 0)
                           OR layers.original_value_minor - layers.remaining_value_minor
                            <> COALESCE((
                                SELECT SUM(consumptions.value_minor)
                                FROM inventory_layer_consumptions consumptions
                                WHERE consumptions.cost_layer_id = layers.id
                            ), 0)
                        LIMIT 1
                        """
                    ).fetchone()
                if layer_balance_issue is not None:
                    raise DBBridgeError("Backup contains inconsistent FIFO layer balances.")
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
        finally:
            connection.close()
        run_migrations(temp_path)
        connection = connect(temp_path, require_exists=True)
        try:
            foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_issues:
                raise DBBridgeError("Backup restore contains invalid table relationships.")
            append_audit_event(
                connection,
                actor_label=actor_label,
                object_type="db_bridge",
                object_id="restore",
                action="db_backup_restored",
                metadata={
                    "backup_file": backup_path.name,
                    "schema_version": backup_schema_version,
                    "restored_to_schema_version": MIGRATIONS[-1].version,
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
