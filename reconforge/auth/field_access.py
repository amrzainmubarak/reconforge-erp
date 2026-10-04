"""Deterministic field authorization and masking primitives."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

REDACTED_VALUE = "[REDACTED]"

AUTH_ME_FIELDS = frozenset(
    {
        "id",
        "username",
        "display_name",
        "email",
        "disabled",
        "created_at",
        "roles",
        "principal_type",
        "step_up_active",
        "step_up_expires_at",
        "step_up_method",
        "permissions",
        "authorized_scopes",
    }
)
AUTH_ME_SCOPE_FIELDS = frozenset({"workspaces", "organizations", "legal_entities"})
SCOPE_GRANT_FIELDS = frozenset(
    {"id", "principal_type", "principal_id", "scope_type", "scope_id", "granted_by", "granted_at"}
)
IDENTITY_USER_FIELDS = frozenset(
    {
        "id",
        "username",
        "display_name",
        "disabled",
        "lifecycle_version",
        "roles",
        "active_sessions",
        "created_at",
        "disabled_at",
        "state_digest",
    }
)
IDENTITY_SESSION_FIELDS = frozenset(
    {
        "id",
        "user_id",
        "username",
        "status",
        "lifecycle_version",
        "created_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "revocation_reason_code",
        "client_ip_recorded",
        "user_agent_recorded",
        "state_digest",
    }
)
IDENTITY_PAGINATION_FIELDS = frozenset({"limit", "returned", "next_cursor"})
IDENTITY_USER_PAGE_FIELDS = frozenset({"users", "pagination"})
IDENTITY_SESSION_PAGE_FIELDS = frozenset({"sessions", "pagination"})
IDENTITY_USER_STATUS_FIELDS = frozenset(
    {"user", "transitioned", "revoked_sessions", "audit_event_id"}
)
IDENTITY_SESSION_REVOCATION_FIELDS = frozenset(
    {"session", "transitioned", "revoked_current_session", "audit_event_id"}
)
LOCAL_ROLE_FIELDS = frozenset({"id", "name"})
LOCAL_ROLE_PERMISSIONS_FIELDS = frozenset({"role", "permissions"})
ACCESS_PERMISSION_FIELDS = frozenset({"name", "description", "active_role_count", "state_digest"})
ACCESS_ROLE_FIELDS = frozenset(
    {
        "id",
        "name",
        "description",
        "active",
        "lifecycle_version",
        "permissions",
        "active_user_count",
        "created_at",
        "updated_at",
        "retired_at",
        "state_digest",
    }
)
ACCESS_PAGINATION_FIELDS = frozenset({"limit", "returned", "next_cursor"})
ACCESS_ROLE_PAGE_FIELDS = frozenset({"roles", "pagination"})
ACCESS_ROLE_CHANGE_FIELDS = frozenset({"role", "transitioned", "revoked_sessions", "audit_event_id"})
ACCESS_USER_ROLE_ASSIGNMENT_FIELDS = frozenset(
    {
        "user_id",
        "username",
        "lifecycle_version",
        "role_ids",
        "role_names",
        "transitioned",
        "revoked_sessions",
        "audit_event_id",
        "state_digest",
    }
)
ACCESS_POLICY_ANALYSIS_FINDING_FIELDS = frozenset(
    {
        "code",
        "conflict_id",
        "grant_ids",
        "permissions",
        "principal_id",
        "reason",
        "scope_digests",
        "severity",
    }
)
ACCESS_POLICY_ANALYSIS_FIELDS = frozenset(
    {
        "active_grant_count",
        "algorithm_version",
        "findings",
        "policy_id",
        "policy_version",
        "request_digest",
        "result_digest",
        "revoked_grant_count",
        "schema_version",
        "status",
    }
)
SECURITY_INTEGRATION_FIELDS = frozenset(
    {
        "kind",
        "id",
        "status",
        "lifecycle_version",
        "credential_count",
        "active_credential_count",
        "created_at",
        "expires_at",
        "last_used_at",
        "scope_digest",
        "state_digest",
    }
)
SECURITY_PAGINATION_FIELDS = frozenset({"limit", "returned", "next_cursor"})
SECURITY_INTEGRATION_PAGE_FIELDS = frozenset({"integrations", "pagination"})
SECURITY_INTEGRATION_DISABLE_FIELDS = frozenset(
    {"integration", "transitioned", "revoked_credentials", "audit_event_id"}
)
SECURITY_RETENTION_POLICY_FIELDS = frozenset(
    {
        "id",
        "name",
        "description",
        "data_classification",
        "duration_days",
        "active",
        "lifecycle_version",
        "created_at",
        "updated_at",
        "retired_at",
        "state_digest",
    }
)
SECURITY_RETENTION_POLICY_PAGE_FIELDS = frozenset({"policies", "pagination"})
SECURITY_RETENTION_POLICY_CHANGE_FIELDS = frozenset({"policy", "transitioned", "audit_event_id"})
SECURITY_EVIDENCE_RETENTION_FIELDS = frozenset(
    {
        "evidence_id",
        "policy_id",
        "policy_lifecycle_version",
        "retention_version",
        "previous_retention_until",
        "policy_retention_until",
        "effective_retention_until",
        "retention_extended",
        "transitioned",
        "audit_event_id",
        "state_digest",
    }
)
METRIC_DASHBOARD_FIELDS = frozenset(
    {"id", "workspace_id", "metric_key", "period_name", "value", "value_text", "lineage", "computed_at", "name", "description"}
)
METRIC_LINEAGE_FIELDS = frozenset({"metric_key", "name", "description", "lineage"})

# These are response-contract fields, not database columns.  Keeping the
# allowlist here makes the sensitive evidence boundary explicit and gives
# every adapter the same fail-closed projection policy.
EVIDENCE_DRILL_DOWN_FIELDS = frozenset(
    {
        "tenant_id",
        "workspace_id",
        "id",
        "evidence_id",
        "evidence_code",
        "source_name",
        "source_path",
        "source_reference",
        "checksum_sha256",
        "provenance_type",
        "redaction_status",
        "evidence_status",
        "storage_backend",
        "storage_tenant_id",
        "storage_key",
        "storage_version_id",
        "content_type",
        "byte_size",
        "retention_until",
        "retention_version",
        "last_verified_at",
        "last_verified_sha256",
        "verification_status",
        "registered_by",
        "created_at",
        "updated_at",
        "links",
    }
)
EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS = frozenset(
    {
        "source_path",
        "source_reference",
        "checksum_sha256",
        "storage_backend",
        "storage_tenant_id",
        "storage_key",
        "storage_version_id",
        "content_type",
        "byte_size",
        "retention_until",
        "retention_version",
        "last_verified_at",
        "last_verified_sha256",
        "verification_status",
    }
)
EVIDENCE_DRILL_DOWN_LINK_FIELDS = frozenset(
    {"tenant_id", "id", "evidence_id", "object_type", "object_id", "link_type", "created_at"}
)
EVIDENCE_LINK_RESPONSE_FIELDS = frozenset({"link", "source"})
EVIDENCE_REQUIREMENT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "object_type",
        "object_id",
        "requirement_code",
        "description",
        "required_status",
        "created_at",
        "updated_at",
    }
)
EVIDENCE_VERIFICATION_FIELDS = frozenset(
    {"evidence_id", "ok", "expected_sha256", "actual_sha256"}
)
EVIDENCE_COVERAGE_FIELDS = frozenset(
    {
        "tenant_id",
        "workspace_id",
        "object_count",
        "requirement_count",
        "covered_object_count",
        "coverage_pct",
        "objects",
    }
)
EVIDENCE_COVERAGE_OBJECT_FIELDS = frozenset(
    {"object_type", "object_id", "requirement_count", "linked_evidence_count"}
)
WRITEBACK_APPROVAL_FIELDS = frozenset({"actor_id", "approved_at", "assurance", "reason"})
WRITEBACK_ACKNOWLEDGEMENT_FIELDS = frozenset(
    {"provider_reference", "acknowledged_at", "response_digest", "idempotency_key", "accepted"}
)
WRITEBACK_INTENT_FIELDS = frozenset(
    {
        "schema_version",
        "intent_id",
        "tenant_id",
        "workspace_id",
        "connector_id",
        "operation",
        "payload_digest",
        "idempotency_key",
        "requested_by",
        "requested_at",
        "feature_enabled",
        "status",
        "approval",
        "acknowledgement",
        "compensation_reason",
        "compensation_requested_by",
        "compensation_requested_at",
    }
)
WRITEBACK_RECOVERY_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "observation_id",
        "evidence_node_id",
        "intent_id",
        "tenant_id",
        "workspace_id",
        "connector_id",
        "proposal_digest",
        "observation_digest",
        "observed_by",
        "observed_at",
        "observation",
    }
)
WRITEBACK_RECOVERY_OBSERVATION_DETAIL_FIELDS = frozenset(
    {
        "outcome",
        "idempotency_key",
        "http_status",
        "body_digest",
        "provider_reference",
        "provider_response_digest",
    }
)
WORKFLOW_OBJECT_FIELDS = frozenset(
    {"id", "object_type", "object_id", "status", "created_at", "updated_at"}
)
WORKFLOW_TRANSITION_FIELDS = frozenset(
    {"id", "object_type", "from_status", "to_status", "required_permission", "sod_rule", "reason_required", "active"}
)
WORKFLOW_EVENT_FIELDS = frozenset(
    {"id", "workflow_object_id", "from_status", "to_status", "actor_user_id", "actor_label", "reason", "created_at"}
)
CLOSE_PERIOD_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "fiscal_period_id",
        "period_name",
        "organization_id",
        "organization_code",
        "workspace",
        "fiscal_period_name",
        "start_date",
        "end_date",
        "status",
        "readiness_score",
        "created_at",
        "updated_at",
        "locked_at",
        "reopened_at",
        "locked_by",
        "reopened_by",
    }
)
CLOSE_TASK_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "close_period_id",
        "task_code",
        "name",
        "owner",
        "owner_user_id",
        "category",
        "risk_rating",
        "due_date",
        "status",
        "blocker_reason",
        "updated_by",
        "created_at",
        "updated_at",
        "period_name",
        "fiscal_period_id",
    }
)
CLOSE_READINESS_FIELDS = frozenset(
    {"period_id", "period_name", "total_tasks", "complete_tasks", "blocked_tasks", "readiness_score"}
)
EXCEPTION_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "source_type",
        "source_id",
        "period_name",
        "entity_code",
        "account_code",
        "control_code",
        "risk_rating",
        "owner",
        "status",
        "escalation_level",
        "sla_target_date",
        "description",
        "created_at",
        "updated_at",
    }
)
EXCEPTION_REVIEW_HISTORY_FIELDS = frozenset(
    {
        "id",
        "exception_id",
        "action",
        "from_status",
        "to_status",
        "from_owner",
        "to_owner",
        "actor_label",
        "actor_id",
        "reason",
        "occurred_at",
    }
)
EXCEPTION_REVIEW_FIELDS = EXCEPTION_FIELDS | frozenset(
    {"organization_id", "legal_entity_id", "row_version", "history"}
)
ACCOUNT_RECONCILIATION_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "period_name",
        "entity_code",
        "account_code",
        "account_name",
        "template_id",
        "status",
        "balance",
        "balance_decimal",
        "materiality_threshold",
        "materiality_threshold_decimal",
        "currency_code",
        "risk_rating",
        "owner",
        "preparer",
        "reviewer",
        "prepared_at",
        "submitted_at",
        "reviewed_at",
        "completed_at",
        "aging_days",
        "created_by",
        "created_at",
        "updated_at",
        "row_version",
        "items",
    }
)
ACCOUNT_RECONCILIATION_ITEM_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "reconciliation_id",
        "item_type",
        "description",
        "amount",
        "amount_decimal",
        "status",
        "evidence_required",
        "created_at",
        "updated_at",
    }
)
RECONCILIATION_RUN_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "name",
        "left_source",
        "right_source",
        "status",
        "algorithm_version",
        "rule_json",
        "rule",
        "input_hash",
        "idempotency_key",
        "created_by",
        "created_at",
        "completed_at",
        "left_input_count",
        "right_input_count",
        "result_count",
        "matched_count",
        "exception_count",
        "input_manifest_hash",
        "result_set_hash",
        "execution_status",
        "execution_worker_id",
        "execution_claimed_at",
        "execution_lease_until",
        "execution_progress",
        "execution_attempt",
        "execution_started_at",
        "execution_finished_at",
        "execution_error",
        "cancel_requested",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "inputs",
        "results",
        "exceptions",
    }
)
RECONCILIATION_INPUT_FIELDS = frozenset(
    {
        "tenant_id",
        "run_id",
        "side",
        "source_id",
        "record_hash",
        "amount_decimal",
        "amount_original",
        "currency_code",
        "date_original",
        "date_value",
        "reference_original",
        "reference_normalized",
        "attributes_json",
        "attributes",
        "valid",
        "allowed_uses",
        "created_at",
    }
)
RECONCILIATION_RESULT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "run_id",
        "left_id",
        "right_id",
        "match_type",
        "confidence",
        "explanation",
        "amount_difference",
        "date_difference_days",
        "status",
        "reason_code",
        "lineage_json",
        "lineage",
        "created_at",
    }
)
RECONCILIATION_EXCEPTION_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "run_id",
        "exception_type",
        "source_side",
        "source_id",
        "title",
        "explanation",
        "severity",
        "risk_score",
        "workflow_status",
        "owner_id",
        "reason_code",
        "evidence_json",
        "evidence",
        "created_at",
        "updated_at",
    }
)
FINANCE_ENTRY_FIELDS = frozenset(
    {
        # Local Finance Core and the tenant-scoped PostgreSQL ledger expose
        # different physical names.  This is the union of their deliberate
        # API contract, not a license to serialize repository rows wholesale.
        "tenant_id",
        "id",
        "workspace_id",
        "organization_id",
        "chart_id",
        "legal_entity_id",
        "finance_journal_id",
        "journal_id",
        "organization_code",
        "entity_code",
        "entry_number",
        "posting_date",
        "currency_code",
        "description",
        "external_reference",
        "source_type",
        "source_id",
        "entry_fingerprint",
        "status",
        "created_by",
        "validated_by",
        "validated_at",
        "validation_reason",
        "voided_by",
        "voided_at",
        "void_reason",
        "created_at",
        "updated_at",
        "posted_at",
        "journal_code",
        "chart_code",
        "period_id",
        "period_name",
        "currency_minor_units",
        "total_debit_minor",
        "total_credit_minor",
        "total_debit",
        "total_credit",
        "debit_total",
        "credit_total",
        "balanced",
        "line_count",
        "lines",
    }
)
FINANCE_ENTRY_LINE_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "entry_id",
        "line_number",
        "account_id",
        "account_code",
        "account_name",
        "description",
        "reference",
        "currency_code",
        "debit_minor",
        "credit_minor",
        "debit_amount",
        "credit_amount",
        "debit",
        "credit",
        "dimensions",
        "created_at",
    }
)
FINANCE_SUMMARY_FIELDS = frozenset(
    {
        "schema_version",
        "workspace",
        "tenant_id",
        "charts",
        "accounts",
        "dimensions",
        "dimension_values",
        "journals",
        "draft_entries",
        "validated_entries",
        "voided_entries",
        "posted_entries",
        "source",
        "unsupported_collections",
    }
)
FINANCE_SUMMARY_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
FINANCE_CHART_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "organization_id",
        "organization_code",
        "workspace",
        "chart_code",
        "name",
        "description",
        "active",
        "created_at",
        "updated_at",
    }
)
FINANCE_ACCOUNT_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "chart_id",
        "chart_code",
        "parent_account_id",
        "parent_account_code",
        "account_code",
        "account_name",
        "account_type",
        "normal_balance",
        "allow_posting",
        "allow_manual_posting",
        "reconciliation_required",
        "active",
        "description",
        "created_at",
        "updated_at",
        "source_backend",
        "workspace",
    }
)
FINANCE_DIMENSION_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "organization_id",
        "organization_code",
        "workspace",
        "dimension_code",
        "name",
        "dimension_type",
        "required_on_entries",
        "active",
        "created_at",
        "updated_at",
    }
)
FINANCE_DIMENSION_VALUE_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "dimension_id",
        "dimension_code",
        "workspace",
        "value_code",
        "name",
        "active",
        "created_at",
        "updated_at",
    }
)
FINANCE_JOURNAL_FIELDS = frozenset(
    {
        "id",
        "workspace_id",
        "organization_id",
        "organization_code",
        "workspace",
        "chart_id",
        "chart_code",
        "journal_code",
        "name",
        "currency_code",
        "journal_type",
        "active",
        "created_at",
        "updated_at",
    }
)
FINANCE_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "source",
        "workspace",
        "summary",
        "charts",
        "accounts",
        "dimensions",
        "dimension_values",
        "journals",
        "entries",
    }
)
FINANCE_SNAPSHOT_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
INVENTORY_VALUATION_DOCUMENT_FIELDS = frozenset(
    {
        # This is the deliberate public union of the local SQLite and
        # tenant-scoped PostgreSQL document projections.  Repository rows
        # remain closed even when either adapter gains a future column.
        "tenant_id",
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "period_id",
        "movement_id",
        "policy_id",
        "valuation_number",
        "valuation_date",
        "currency_code",
        "status",
        "total_value",
        "finance_entry_id",
        "created_by",
        "approved_by",
        "approved_at",
        "approval_reason",
        "cancelled_by",
        "cancelled_at",
        "cancel_reason",
        "created_at",
        "updated_at",
        "row_version",
        "movement_number",
        "movement_type",
        "movement_status",
        "organization_code",
        "entity_code",
        "period_name",
        "policy_code",
        "costing_method",
        "finance_entry_number",
        "finance_entry_status",
        "input_costs",
        "lines",
        "layer_consumptions",
    }
)
INVENTORY_VALUATION_INPUT_COST_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "valuation_document_id",
        "movement_line_id",
        "total_cost",
        "created_at",
        "line_number",
    }
)
INVENTORY_VALUATION_LINE_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "valuation_document_id",
        "movement_line_id",
        "line_number",
        "flow_direction",
        "item_id",
        "uom_id",
        "inventory_lot_id",
        "quantity",
        "quantity_precision",
        "value",
        "inventory_account_id",
        "offset_account_id",
        "created_at",
        "item_code",
        "uom_code",
        "lot_serial_code",
        "inventory_account_code",
        "offset_account_code",
    }
)
INVENTORY_LAYER_CONSUMPTION_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "valuation_line_id",
        "cost_layer_id",
        "quantity",
        "value",
        "created_at",
        "line_number",
        "layer_id",
        "source_valuation_line_id",
    }
)
INVENTORY_VALUATION_POLICY_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "policy_code",
        "costing_method",
        "currency_code",
        "finance_journal_id",
        "receipt_clearing_account_id",
        "cogs_account_id",
        "adjustment_account_id",
        "active",
        "created_by",
        "created_at",
        "updated_at",
        "row_version",
        "organization_code",
        "entity_code",
        "journal_code",
        "receipt_clearing_account_code",
        "cogs_account_code",
        "adjustment_account_code",
    }
)
INVENTORY_COST_LAYER_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "source_valuation_line_id",
        "legal_entity_id",
        "item_id",
        "uom_id",
        "inventory_lot_id",
        "quantity_precision",
        "original_quantity",
        "remaining_quantity",
        "original_value",
        "remaining_value",
        "currency_code",
        "created_at",
        "row_version",
        "item_code",
        "uom_code",
        "lot_serial_code",
        "entity_code",
        "valuation_number",
        "layer_status",
    }
)
INVENTORY_VALUATION_SUMMARY_FIELDS = frozenset(
    {"workspace", "policies", "draft_documents", "approved_documents", "open_layers", "unvalued_posted_movements"}
)
INVENTORY_VALUATION_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "source",
        "workspace",
        "summary",
        "policies",
        "documents",
        "open_cost_layers",
        "boundary_note",
    }
)
INVENTORY_VALUATION_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
INVENTORY_VALUATION_REVERSAL_FIELDS = frozenset(
    {
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "period_id",
        "original_valuation_document_id", "reversal_movement_id", "reversal_number", "reversal_date",
        "currency_code", "status", "total_value", "original_total_value", "finance_entry_id",
        "created_by", "approved_by", "approved_at", "approval_reason", "cancelled_by", "cancelled_at",
        "cancel_reason", "created_at", "updated_at", "row_version", "original_valuation_number",
        "original_movement_id", "original_finance_entry_id", "original_movement_number",
        "original_movement_type", "reversal_movement_number", "reversal_movement_type", "reversal_movement_status",
        "organization_code", "entity_code", "period_name", "finance_entry_number", "finance_entry_status", "effects",
    }
)
INVENTORY_VALUATION_REVERSAL_EFFECT_FIELDS = frozenset(
    {
        "tenant_id", "id", "reversal_id", "original_valuation_line_id", "original_consumption_id",
        "cost_layer_id", "effect_type", "quantity", "value", "created_at", "line_number", "flow_direction",
        "quantity_precision", "item_code", "uom_code", "lot_serial_code", "layer_valuation_number",
    }
)
INVENTORY_VALUATION_REVERSAL_SUMMARY_FIELDS = frozenset(
    {"workspace", "draft_reversals", "approved_reversals", "cancelled_reversals", "approved_effects", "finance_drafts"}
)
INVENTORY_VALUATION_REVERSAL_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "generated_at", "source", "workspace", "summary", "reversals", "boundary_note"}
)
INVENTORY_UOM_FIELDS = frozenset(
    {"tenant_id", "id", "workspace_id", "uom_code", "name", "category", "decimal_places", "active", "created_at", "updated_at", "row_version"}
)
INVENTORY_ITEM_FIELDS = frozenset(
    {
        "tenant_id", "id", "workspace_id", "organization_id", "item_code", "name", "item_type", "tracking_mode",
        "uom_id", "inventory_account_id", "description", "active", "created_at", "updated_at", "row_version",
        "organization_code", "uom_code", "decimal_places", "inventory_account_code",
    }
)
INVENTORY_WAREHOUSE_FIELDS = frozenset(
    {"tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "warehouse_code", "name", "active", "created_at", "updated_at", "row_version", "organization_code", "entity_code"}
)
INVENTORY_LOCATION_FIELDS = frozenset(
    {"tenant_id", "id", "warehouse_id", "parent_location_id", "location_code", "name", "location_type", "allow_negative", "active", "created_at", "updated_at", "row_version", "warehouse_code", "organization_code", "parent_location_code"}
)
INVENTORY_LOT_FIELDS = frozenset(
    {"tenant_id", "id", "workspace_id", "organization_id", "item_id", "lot_serial_code", "tracking_type", "manufactured_on", "expires_on", "active", "created_at", "updated_at", "row_version", "item_code", "organization_code"}
)
INVENTORY_MOVEMENT_FIELDS = frozenset(
    {
        # Deliberate union for local SQLite and tenant-scoped PostgreSQL
        # movement responses.  This is narrower than either repository row.
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "period_id",
        "movement_number", "movement_type", "movement_date", "source_reference", "description",
        "source_type", "status", "created_by", "posted_by", "posted_at", "post_reason",
        "voided_by", "voided_at", "void_reason", "created_at", "updated_at", "row_version",
        "organization_code", "entity_code", "period_name", "line_count", "lines",
    }
)
INVENTORY_MOVEMENT_LINE_FIELDS = frozenset(
    {
        "tenant_id", "id", "movement_id", "line_number", "item_id", "uom_id", "inventory_lot_id",
        "from_location_id", "to_location_id", "quantity_scaled", "quantity_precision", "quantity",
        "description", "created_at", "item_code", "item_name", "uom_code", "lot_serial_code",
        "from_location", "to_location",
    }
)
INVENTORY_ON_HAND_FIELDS = frozenset(
    {"schema_version", "source", "workspace", "organization_code", "entity_code", "summary", "balances"}
)
INVENTORY_ON_HAND_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
INVENTORY_ON_HAND_SUMMARY_FIELDS = frozenset({"rows", "negative_rows"})
INVENTORY_ON_HAND_BALANCE_FIELDS = frozenset(
    {
        "tenant_id", "location_id", "warehouse_code", "location_code", "allow_negative", "item_id", "item_code",
        "item_name", "uom_code", "inventory_lot_id", "lot_serial_code", "quantity_precision", "quantity_scaled",
        "quantity", "negative",
    }
)
INVENTORY_CONTROL_EXCEPTION_FIELDS = frozenset(
    {"schema_version", "generated_at", "as_of", "source", "workspace", "organization_code", "entity_code", "summary", "exceptions"}
)
INVENTORY_CONTROL_EXCEPTION_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
INVENTORY_CONTROL_EXCEPTION_SUMMARY_FIELDS = frozenset({"total", "high", "medium"})
INVENTORY_CONTROL_EXCEPTION_ITEM_FIELDS = frozenset(
    {
        "exception_id", "control_code", "risk_rating", "item_code", "warehouse_code", "location_code",
        "lot_serial_code", "quantity", "description",
    }
)
INVENTORY_CORE_SUMMARY_FIELDS = frozenset(
    {"workspace", "units_of_measure", "items", "warehouses", "locations", "lots_and_serials", "draft_movements", "posted_movements", "voided_movements"}
)
INVENTORY_CORE_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version", "generated_at", "source", "workspace", "summary", "units_of_measure", "items",
        "warehouses", "locations", "lots_and_serials", "movements",
    }
)
INVENTORY_CORE_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
INVENTORY_PLANNING_SESSION_FIELDS = frozenset(
    {
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "period_id", "location_id",
        "count_number", "count_date", "description", "status", "created_by", "started_by", "started_at",
        "submitted_by", "submitted_at", "submit_reason", "approved_by", "approved_at", "approval_reason",
        "cancelled_by", "cancelled_at", "cancel_reason", "adjustment_movement_id", "created_at", "updated_at",
        "row_version", "organization_code", "entity_code", "period_name", "warehouse_code", "location_code",
        "location_name", "adjustment_movement_number", "lines", "summary",
    }
)
INVENTORY_PLANNING_LINE_FIELDS = frozenset(
    {
        "tenant_id", "id", "session_id", "line_number", "item_id", "uom_id", "inventory_lot_id",
        "expected_quantity_scaled", "counted_quantity_scaled", "quantity_precision", "count_note", "counted_by",
        "counted_at", "created_at", "row_version", "item_code", "item_name", "uom_code", "lot_serial_code",
        "expected_quantity", "counted_quantity", "variance_quantity_scaled", "variance_quantity",
    }
)
INVENTORY_PLANNING_SESSION_SUMMARY_FIELDS = frozenset({"lines", "counted_lines", "variance_lines"})
INVENTORY_PLANNING_SUMMARY_FIELDS = frozenset(
    {"workspace", "count_sessions", "counting_sessions", "submitted_sessions", "approved_sessions", "reorder_rules", "active_reorder_rules"}
)
INVENTORY_REORDER_RULE_FIELDS = frozenset(
    {
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "item_id", "location_id",
        "minimum_quantity_scaled", "target_quantity_scaled", "quantity_precision", "lead_time_days", "active",
        "created_by", "created_at", "updated_at", "row_version", "organization_code", "entity_code", "item_code",
        "item_name", "warehouse_code", "location_code", "uom_code", "on_hand_quantity_scaled",
        "minimum_quantity", "target_quantity", "on_hand_quantity",
    }
)
INVENTORY_REORDER_SIGNALS_FIELDS = frozenset(
    {"schema_version", "generated_at", "source", "workspace", "organization_code", "entity_code", "summary", "pagination", "signals"}
)
INVENTORY_REORDER_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
INVENTORY_REORDER_SUMMARY_FIELDS = frozenset({"total", "high", "medium"})
INVENTORY_REORDER_PAGINATION_FIELDS = frozenset({"limit", "offset", "returned"})
INVENTORY_REORDER_SIGNAL_FIELDS = frozenset(
    {
        "signal_id", "rule_id", "risk_rating", "item_code", "item_name", "warehouse_code", "location_code",
        "uom_code", "quantity_precision", "on_hand_quantity_scaled", "on_hand_quantity", "minimum_quantity_scaled",
        "minimum_quantity", "target_quantity_scaled", "target_quantity", "suggested_quantity_scaled",
        "suggested_quantity", "lead_time_days", "description",
    }
)
INVENTORY_PLANNING_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "generated_at", "source", "workspace", "summary", "count_sessions", "reorder_rules"}
)
INDIVIDUAL_CASHFLOW_FIELDS = frozenset(
    {"schema_version", "algorithm_version", "input_digests", "decisions", "decision_digest", "status_counts"}
)
INDIVIDUAL_CASHFLOW_DECISION_FIELDS = frozenset(
    {
        "actual", "budget", "budget_id", "category", "flow_type", "period", "reason_code", "status",
        "transaction_ids", "variance",
    }
)
INDIVIDUAL_CASHFLOW_MONEY_FIELDS = frozenset(
    {
        "amount", "currency", "currency_policy_digest", "currency_registry_digest", "currency_registry_version",
        "minor_units", "rounding_policy", "schema_version",
    }
)
INDIVIDUAL_CASHFLOW_STATUS_FIELDS = frozenset({"no_activity", "over_budget", "unbudgeted", "within_budget"})
PAYABLES_SUPPLIER_FIELDS = frozenset(
    {
        # Deliberate union for local SQLite and tenant-scoped PostgreSQL
        # supplier responses; repository rows are never serialized wholesale.
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "supplier_code", "name",
        "currency_code", "tax_identifier", "status", "created_at", "updated_at", "row_version",
    }
)
PAYABLES_PURCHASE_ORDER_FIELDS = frozenset(
    {
        # Deliberate union for local SQLite and tenant-scoped PostgreSQL
        # purchase-order responses.  Nested lines use a separate contract.
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "branch_id", "supplier_id",
        "po_number", "order_date", "expected_date", "currency_code", "status", "created_by", "approved_by",
        "approved_at", "created_at", "updated_at", "row_version", "lines",
    }
)
PAYABLES_PURCHASE_ORDER_LINE_FIELDS = frozenset(
    {
        "tenant_id", "id", "purchase_order_id", "line_number", "item_code", "description", "ordered_quantity",
        "ordered_quantity_text", "unit_price_minor", "tax_minor", "created_at",
    }
)
PAYABLES_RECEIPT_FIELDS = frozenset(
    {
        # Deliberate union for local SQLite and tenant-scoped PostgreSQL
        # goods-receipt responses.  Receipt lines use a separate contract.
        "tenant_id", "id", "workspace_id", "purchase_order_id", "receipt_number", "receipt_date", "status",
        "created_by", "posted_by", "posted_at", "created_at", "updated_at", "row_version", "lines",
    }
)
PAYABLES_RECEIPT_LINE_FIELDS = frozenset(
    {"tenant_id", "id", "receipt_id", "purchase_order_line_id", "received_quantity", "received_quantity_text", "created_at"}
)
PAYABLES_SUPPLIER_INVOICE_FIELDS = frozenset(
    {
        # Deliberate union for local SQLite and tenant-scoped PostgreSQL
        # invoice responses.  Lines and match results use child contracts.
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "supplier_id",
        "purchase_order_id", "invoice_number", "invoice_date", "due_date", "currency_code", "tax_minor",
        "total_minor", "status", "created_by", "approved_by", "approved_at", "created_at", "updated_at",
        "row_version", "lines", "three_way_match",
    }
)
PAYABLES_SUPPLIER_INVOICE_LINE_FIELDS = frozenset(
    {
        "tenant_id", "id", "supplier_invoice_id", "purchase_order_line_id", "line_number", "description",
        "invoiced_quantity", "invoiced_quantity_text", "unit_price_minor", "tax_minor", "line_total_minor",
        "created_at",
    }
)
PAYABLES_THREE_WAY_MATCH_FIELDS = frozenset(
    {
        "tenant_id", "id", "match_id", "invoice_id", "supplier_invoice_id", "purchase_order_id", "status",
        "quantity_variance", "price_variance_minor", "total_variance_minor", "reason", "created_at", "updated_at",
    }
)
RECEIVABLES_CUSTOMER_FIELDS = frozenset(
    {
        # Deliberate union for local SQLite and tenant-scoped PostgreSQL
        # customer responses; repository rows are never serialized wholesale.
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "customer_code", "name",
        "currency_code", "tax_identifier", "payment_terms_days", "credit_limit_minor", "credit_hold", "status",
        "created_at", "updated_at", "row_version", "monetary_policy", "credit_limit_minor_text",
    }
)
RECEIVABLES_INVOICE_FIELDS = frozenset(
    {
        # Exact integer minor units and canonical quantity text are retained
        # for compatibility; unknown adapter/storage fields are excluded.
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "customer_id", "invoice_number",
        "invoice_date", "due_date", "currency_code", "subtotal_minor", "tax_minor", "total_minor", "status",
        "created_by", "approved_by", "approved_at", "credit_override_reason", "cancelled_by", "cancelled_at",
        "cancel_reason", "created_at", "updated_at", "row_version", "lines", "allocated_minor", "outstanding_minor",
        "monetary_policy", "subtotal_minor_text", "tax_minor_text", "total_minor_text", "allocated_minor_text", "outstanding_minor_text",
    }
)
RECEIVABLES_INVOICE_LINE_FIELDS = frozenset(
    {"tenant_id", "id", "invoice_id", "line_number", "description", "quantity", "quantity_text", "unit_price_minor", "tax_minor", "line_total_minor", "created_at", "unit_price_minor_text", "tax_minor_text", "line_total_minor_text"}
)
RECEIVABLES_RECEIPT_FIELDS = frozenset(
    {
        "tenant_id", "id", "workspace_id", "organization_id", "legal_entity_id", "customer_id", "receipt_number",
        "receipt_date", "currency_code", "amount_minor", "status", "created_by", "posted_by", "posted_at",
        "created_at", "updated_at", "row_version", "allocations", "allocated_minor", "unallocated_minor",
        "monetary_policy", "amount_minor_text", "allocated_minor_text", "unallocated_minor_text",
    }
)
RECEIVABLES_ALLOCATION_FIELDS = frozenset(
    {"tenant_id", "id", "workspace_id", "receipt_id", "invoice_id", "amount_minor", "amount_minor_text", "created_at"}
)
RECEIVABLES_CREDIT_EXPOSURE_FIELDS = frozenset(
    {"customer_id", "customer_code", "currency_code", "credit_limit_minor", "exposure_minor", "available_credit_minor", "credit_hold", "status", "credit_limit_minor_text", "exposure_minor_text", "available_credit_minor_text"}
)
RECEIVABLES_AGING_FIELDS = frozenset(
    {"as_of_date", "currency_code", "items", "bucket_totals_minor", "total_outstanding_minor"}
)
RECEIVABLES_GROUPED_AGING_FIELDS = frozenset({"schema_version", "as_of_date", "currency_groups"})
RECEIVABLES_AGING_GROUP_FIELDS = RECEIVABLES_AGING_FIELDS - {"as_of_date"}
RECEIVABLES_AGING_ITEM_FIELDS = frozenset(
    {
        "invoice_id", "organization_id", "legal_entity_id", "invoice_number", "customer_code", "customer_name",
        "currency_code", "invoice_date", "due_date", "total_minor", "outstanding_minor", "days_overdue", "bucket",
    }
)
PROFESSIONAL_INVOICE_PAYMENT_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "workspace_id",
        "decision_digest",
        "artifact_digest",
        "algorithm_version",
        "prepared_by",
        "prepared_at",
        "created_at",
        "report",
    }
)
PROFESSIONAL_INVOICE_PAYMENT_REPORT_FIELDS = frozenset(
    {
        "algorithm_version",
        "artifact_digest",
        "artifact_type",
        "amount_tolerance",
        "decision_digest",
        "decisions",
        "input_digests",
        "payment_window_days",
        "schema_version",
        "status_counts",
    }
)
PROFESSIONAL_INVOICE_PAYMENT_MONEY_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "currency_policy_digest",
        "currency_registry_digest",
        "currency_registry_version",
        "minor_units",
        "rounding_policy",
        "schema_version",
    }
)
PROFESSIONAL_INVOICE_PAYMENT_DECISION_FIELDS = frozenset(
    {
        "amount_variance",
        "client_id",
        "days_from_due_date",
        "invoice_id",
        "payment_ids",
        "reason_code",
        "status",
    }
)
PROFESSIONAL_INVOICE_PAYMENT_STATUS_KEYS = frozenset(
    {"matched", "exception", "unmatched_invoice", "unmatched_payment", "ambiguous"}
)
RETAIL_SETTLEMENT_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "workspace_id",
        "decision_digest",
        "artifact_digest",
        "algorithm_version",
        "prepared_by",
        "prepared_at",
        "created_at",
        "report",
    }
)
RETAIL_SETTLEMENT_REPORT_FIELDS = frozenset(
    {
        "algorithm_version",
        "artifact_digest",
        "artifact_type",
        "decision_digest",
        "decisions",
        "input_digests",
        "schema_version",
        "status_counts",
        "tolerance",
    }
)
RETAIL_SETTLEMENT_MONEY_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "currency_policy_digest",
        "currency_registry_digest",
        "currency_registry_version",
        "minor_units",
        "rounding_policy",
        "schema_version",
    }
)
RETAIL_SETTLEMENT_DECISION_FIELDS = frozenset(
    {
        "batch_id",
        "card_gross_variance",
        "expected_card_net",
        "net_variance",
        "pos_total_net_sales",
        "reason_code",
        "refund_variance",
        "settlement_ids",
        "settlement_net",
        "status",
        "store_id",
    }
)
RETAIL_SETTLEMENT_STATUS_KEYS = frozenset(
    {"matched", "exception", "unmatched_pos", "unmatched_settlement", "ambiguous"}
)
BANK_STATEMENT_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "workspace_id",
        "decision_digest",
        "artifact_digest",
        "algorithm_version",
        "prepared_by",
        "prepared_at",
        "created_at",
        "report",
    }
)
BANK_STATEMENT_REPORT_FIELDS = frozenset(
    {
        "algorithm_version",
        "artifact_digest",
        "artifact_type",
        "amount_tolerance",
        "date_window_days",
        "decision_digest",
        "decisions",
        "input_digests",
        "schema_version",
        "status_counts",
    }
)
BANK_STATEMENT_MONEY_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "currency_policy_digest",
        "currency_registry_digest",
        "currency_registry_version",
        "minor_units",
        "rounding_policy",
        "schema_version",
    }
)
BANK_STATEMENT_DECISION_FIELDS = frozenset(
    {
        "account_id",
        "amount_variance",
        "bank_line_id",
        "days_variance",
        "ledger_record_ids",
        "reason_code",
        "status",
    }
)
BANK_STATEMENT_STATUS_KEYS = frozenset(
    {"matched", "exception", "unmatched_bank", "unmatched_ledger", "ambiguous"}
)
MANUFACTURING_COST_CONTROL_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "workspace_id",
        "decision_digest",
        "artifact_digest",
        "algorithm_version",
        "prepared_by",
        "prepared_at",
        "created_at",
        "report",
    }
)
MANUFACTURING_COST_CONTROL_REPORT_FIELDS = frozenset(
    {
        "algorithm_version",
        "artifact_digest",
        "artifact_type",
        "amount_tolerance",
        "decision_digest",
        "decisions",
        "input_digests",
        "max_scrap_quantity",
        "schema_version",
        "status_counts",
    }
)
MANUFACTURING_COST_CONTROL_MONEY_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "currency_policy_digest",
        "currency_registry_digest",
        "currency_registry_version",
        "minor_units",
        "rounding_policy",
        "schema_version",
    }
)
MANUFACTURING_COST_CONTROL_QUANTITY_FIELDS = frozenset({"scale", "unit", "value"})
MANUFACTURING_COST_CONTROL_DECISION_FIELDS = frozenset(
    {
        "actual_material_cost",
        "completed_quantity",
        "completion_cost",
        "completion_cost_variance",
        "expected_material_cost",
        "issued_quantity",
        "material_cost_variance",
        "order_id",
        "planned_quantity",
        "product_id",
        "reason_codes",
        "scrap_quantity",
        "status",
    }
)
MANUFACTURING_COST_CONTROL_STATUS_KEYS = frozenset({"reconciled", "exception", "unmatched"})
MASTER_CURRENCY_FIELDS = frozenset(
    {"tenant_id", "code", "name", "minor_units", "active", "created_at", "updated_at", "source_backend"}
)
MASTER_ORGANIZATION_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "organization_code",
        "name",
        "base_currency",
        "active",
        "created_at",
        "updated_at",
        "workspace",
        "source_backend",
    }
)
MASTER_ENTITY_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "organization_id",
        "entity_code",
        "name",
        "currency",
        "currency_code",
        "active",
        "created_at",
        "updated_at",
        "workspace",
        "workspace_id",
        "source_backend",
    }
)
MASTER_BRANCH_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "organization_id",
        "legal_entity_id",
        "branch_code",
        "entity_code",
        "name",
        "active",
        "created_at",
        "updated_at",
        "workspace",
        "workspace_id",
        "source_backend",
    }
)
MASTER_PERIOD_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "name",
        "start_date",
        "end_date",
        "status",
        "created_at",
        "fiscal_year",
        "period_number",
        "status_reason",
        "updated_at",
        "workspace",
        "source_backend",
    }
)
MASTER_SUMMARY_FIELDS = frozenset(
    {"workspace", "organizations", "legal_entities", "branches", "periods", "active_currencies", "source", "unsupported_collections"}
)
MASTER_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "source",
        "workspace",
        "summary",
        "currency_registry",
        "currencies",
        "organizations",
        "legal_entities",
        "branches",
        "periods",
        "unsupported_collections",
    }
)
MASTER_SNAPSHOT_SUMMARY_FIELDS = frozenset(
    {"workspace", "organizations", "legal_entities", "branches", "periods", "active_currencies", "source", "unsupported_collections"}
)
MASTER_SNAPSHOT_SOURCE_FIELDS = frozenset({"kind", "local_first", "external_calls", "server_mode"})
MASTER_REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        "scope",
        "status",
        "ok",
        "registry",
        "master_currency_count",
        "active_master_currency_count",
        "input_digest",
        "issues",
        "binding",
    }
)
MASTER_REGISTRY_DETAILS_FIELDS = frozenset({"registry_version", "digest"})
MASTER_REGISTRY_ISSUE_FIELDS = frozenset(
    {"code", "currency_code", "message", "master_minor_units", "registry_minor_units"}
)
MASTER_REGISTRY_BINDING_FIELDS = frozenset(
    {"status", "registry_version", "registry_digest", "bound_at", "bound_by"}
)
MASTER_REGISTRY_BINDING_RESPONSE_FIELDS = frozenset({"binding", "source"})
CONSOLIDATION_SUMMARY_FIELDS = frozenset(
    {
        "workspace",
        "periods",
        "locked_periods",
        "prepared_runs",
        "approved_runs",
        "posted_runs",
        "reversal_prepared_runs",
        "reversed_runs",
    }
)
CONSOLIDATION_PERIOD_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "group_code",
        "period_name",
        "reporting_currency",
        "period_start_date",
        "period_end_date",
        "reporting_date",
        "status",
        "row_version",
        "created_by",
        "created_at",
        "updated_at",
        "locked_by",
        "locked_at",
        "lock_reason",
        "reopened_by",
        "reopened_at",
        "reopen_reason",
    }
)
CONSOLIDATION_JOURNAL_LINE_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "run_id",
        "ordinal",
        "elimination_id",
        "source_line_id",
        "entity_code",
        "group_account_code",
        "account_type",
        "amount_decimal",
        "amount_minor",
        "currency_code",
        "source_reference",
        "source_digest",
    }
)
CONSOLIDATION_EFFECT_LINE_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "effect_id",
        "run_line_id",
        "ordinal",
        "amount_decimal",
        "amount_minor",
        "currency_code",
    }
)
CONSOLIDATION_EFFECT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "run_id",
        "effect_type",
        "source_effect_id",
        "status",
        "line_count",
        "effect_digest",
        "created_by",
        "created_at",
        "actor",
        "lines",
    }
)
CONSOLIDATION_RUN_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "period_id",
        "workspace_id",
        "run_number",
        "worksheet_id",
        "worksheet_request_digest",
        "worksheet_result_digest",
        "translation_result_digest",
        "worksheet_payload_digest",
        "worksheet_digest",
        "reporting_currency",
        "journal_line_count",
        "journal_digest",
        "status",
        "row_version",
        "prepared_by",
        "prepared_at",
        "approved_by",
        "approved_at",
        "approval_reason",
        "posted_by",
        "posted_at",
        "posting_reason",
        "reversal_requested_by",
        "reversal_requested_at",
        "reversal_request_reason",
        "reversed_by",
        "reversed_at",
        "reversal_reason",
        "reasons",
        "worksheet",
        "translation_evidence",
        "management_statement",
        "journal_lines",
        "effects",
        "intercompany_evidence",
        "impairment_evidence",
        "deferred_tax_evidence",
        "ppa_evidence",
        "ownership_change_evidence",
        "close_bundle",
    }
)
CONSOLIDATION_CERTIFICATION_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "object_type",
        "object_id",
        "period_name",
        "entity_code",
        "status",
        "prepared_by",
        "reviewed_by",
        "note",
        "evidence_digest",
        "created_by",
        "prepared_at",
        "reviewed_at",
        "created_at",
        "updated_at",
        "row_version",
    }
)
CONSOLIDATION_CERTIFICATION_RESPONSE_FIELDS = frozenset({"certification", "source"})
CONSOLIDATION_EVIDENCE_LINK_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "run_id",
        "artifact_id",
        "artifact_result_digest",
        "matched_elimination_ids",
        "unresolved_count",
        "entity_code",
        "period_id",
        "reporting_currency",
        "total_impairment_loss",
        "net_deferred_tax",
        "posted",
        "link_digest",
        "actor",
        "created_at",
        "posting",
    }
)
CONSOLIDATION_EVIDENCE_LINK_RESPONSE_FIELDS = frozenset({"link", "source"})
CONSOLIDATION_OWNERSHIP_INTEREST_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "workspace",
        "group_code",
        "interest_id",
        "parent_entity_code",
        "subsidiary_entity_code",
        "direct_ownership_percentage",
        "effective_from",
        "effective_to",
        "version",
        "source_digest",
        "prepared_by",
        "approved_by",
        "approved_at",
        "created_at",
    }
)
CONSOLIDATION_OWNERSHIP_SOURCE_FIELDS = MASTER_SNAPSHOT_SOURCE_FIELDS | frozenset({"workspace"})
CONSOLIDATION_OWNERSHIP_INTEREST_RESPONSE_FIELDS = frozenset({"interest", "source"})
CONSOLIDATION_OWNERSHIP_EFFECTIVE_RESPONSE_FIELDS = frozenset({"interests", "source"})
CONSOLIDATION_PPA_ARTIFACT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "organization_id",
        "legal_entity_id",
        "acquisition_id",
        "subsidiary_entity_code",
        "period_id",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "request_payload",
        "result_payload",
        "posted",
        "prepared_by",
        "approved_by",
        "approved_at",
        "created_at",
    }
)
CONSOLIDATION_PPA_PAYLOAD_MONEY_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "currency_policy_digest",
        "currency_registry_digest",
        "currency_registry_version",
        "minor_units",
        "rounding_policy",
        "schema_version",
    }
)
CONSOLIDATION_PPA_ITEM_FIELDS = frozenset(
    {
        "account_code",
        "book_value",
        "class_code",
        "fair_value",
        "fair_value_adjustment",
        "item_id",
        "item_kind",
        "source_reference",
        "valuation_reference",
    }
)
CONSOLIDATION_PPA_BRIDGE_LINE_FIELDS = frozenset(
    {"account_code", "amount", "line_type", "source_reference"}
)
CONSOLIDATION_PPA_BRIDGE_FIELDS = frozenset(
    {
        "acquisition_id",
        "algorithm_version",
        "bargain_purchase",
        "goodwill",
        "lines",
        "posted",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "schema_version",
    }
)
CONSOLIDATION_PPA_REQUEST_PAYLOAD_FIELDS = frozenset(
    {
        "acquisition_date",
        "acquisition_id",
        "allow_bargain_purchase",
        "approved_at",
        "approved_by",
        "bargain_purchase_account_code",
        "consideration",
        "consideration_account_code",
        "goodwill_account_code",
        "identifiable_net_assets_account_code",
        "items",
        "nci_account_code",
        "nci_fair_value",
        "period_id",
        "policy_id",
        "policy_version",
        "prepared_at",
        "prepared_by",
        "reporting_currency",
        "source_digest",
        "source_reference",
        "subsidiary_entity_code",
    }
)
CONSOLIDATION_PPA_RESULT_PAYLOAD_FIELDS = frozenset(
    {
        "acquisition_id",
        "algorithm_version",
        "book_net_assets",
        "bridge",
        "fair_value_adjustment",
        "fair_value_net_assets",
        "items",
        "posted",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "schema_version",
    }
)
CONSOLIDATION_PPA_RESPONSE_FIELDS = frozenset({"artifact", "source"})
CONSOLIDATION_OWNERSHIP_CHANGE_ARTIFACT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "change_id",
        "subsidiary_entity_code",
        "period_id",
        "effective_date",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "request_payload",
        "result_payload",
        "posted",
        "prepared_by",
        "approved_by",
        "approved_at",
        "created_at",
    }
)
CONSOLIDATION_OWNERSHIP_CHANGE_REQUEST_FIELDS = frozenset(
    {
        "approved_at",
        "approved_by",
        "change_id",
        "consideration_account_code",
        "consideration_effect",
        "effective_date",
        "nci_account_code",
        "net_assets",
        "new_group_ownership_percentage",
        "parent_equity_account_code",
        "period_id",
        "policy_id",
        "policy_version",
        "prepared_at",
        "prepared_by",
        "prior_group_ownership_percentage",
        "reporting_currency",
        "source_digest",
        "source_reference",
        "subsidiary_entity_code",
    }
)
CONSOLIDATION_OWNERSHIP_CHANGE_RESULT_FIELDS = frozenset(
    {
        "algorithm_version",
        "change_id",
        "lines",
        "new_nci_percentage",
        "nci_rounding_delta",
        "posted",
        "prior_nci_percentage",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "schema_version",
        "unrounded_nci_effect",
    }
)
CONSOLIDATION_OWNERSHIP_CHANGE_LINE_FIELDS = frozenset(
    {"account_code", "line_type", "amount", "source_reference"}
)
CONSOLIDATION_OWNERSHIP_CHANGE_RESPONSE_FIELDS = frozenset({"artifact", "source"})
CONSOLIDATION_INTERCOMPANY_ARTIFACT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "reporting_currency",
        "version",
        "request_digest",
        "result_digest",
        "request_payload",
        "result_payload",
        "posted",
        "prepared_by",
        "prepared_at",
        "created_at",
        "posting",
    }
)
CONSOLIDATION_INTERCOMPANY_REQUEST_FIELDS = frozenset(
    {"lines", "prepared_at", "prepared_by", "reporting_currency", "version"}
)
CONSOLIDATION_INTERCOMPANY_LINE_FIELDS = frozenset(
    {
        "account_type",
        "amount",
        "counterparty_code",
        "entity_code",
        "group_account_code",
        "line_id",
        "period_name",
        "reference",
        "source_digest",
        "source_reference",
        "transaction_id",
    }
)
CONSOLIDATION_INTERCOMPANY_RESULT_FIELDS = frozenset(
    {
        "algorithm_version",
        "prepared_at",
        "prepared_by",
        "reporting_currency",
        "request_digest",
        "resolutions",
        "result_digest",
        "schema_version",
        "version",
    }
)
CONSOLIDATION_INTERCOMPANY_RESOLUTION_FIELDS = frozenset(
    {"group_key", "proposal", "reason", "source_group_digest", "source_transaction_ids", "status"}
)
CONSOLIDATION_INTERCOMPANY_PROPOSAL_FIELDS = frozenset(
    {"elimination_id", "elimination_type", "lines", "prepared_at", "prepared_by", "rationale", "version"}
)
CONSOLIDATION_INTERCOMPANY_PROPOSAL_LINE_FIELDS = frozenset(
    {"account_type", "amount", "entity_code", "group_account_code", "line_id", "source_digest", "source_reference"}
)
CONSOLIDATION_INTERCOMPANY_RESPONSE_FIELDS = frozenset({"artifact", "source"})
CONSOLIDATION_IMPAIRMENT_ARTIFACT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "organization_id",
        "legal_entity_id",
        "impairment_test_id",
        "entity_code",
        "period_id",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "request_payload",
        "result_payload",
        "posted",
        "prepared_by",
        "approved_by",
        "approved_at",
        "created_at",
    }
)
CONSOLIDATION_IMPAIRMENT_REQUEST_FIELDS = frozenset(
    {
        "approved_at",
        "approved_by",
        "entity_code",
        "impairment_test_id",
        "period_id",
        "policy_id",
        "policy_version",
        "prepared_at",
        "prepared_by",
        "reporting_currency",
        "source_digest",
        "source_reference",
        "units",
    }
)
CONSOLIDATION_IMPAIRMENT_UNIT_FIELDS = frozenset(
    {
        "account_code",
        "carrying_amount",
        "recoverable_amount",
        "source_digest",
        "source_reference",
        "unit_id",
        "unit_kind",
    }
)
CONSOLIDATION_IMPAIRMENT_RESULT_FIELDS = frozenset(
    {
        "algorithm_version",
        "impairment_test_id",
        "posted",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "schema_version",
        "total_carrying_amount",
        "total_impairment_loss",
        "total_recoverable_amount",
        "units",
    }
)
CONSOLIDATION_IMPAIRMENT_RESULT_UNIT_FIELDS = CONSOLIDATION_IMPAIRMENT_UNIT_FIELDS | frozenset(
    {"impairment_loss", "recoverable_headroom", "status"}
)
CONSOLIDATION_IMPAIRMENT_RESPONSE_FIELDS = frozenset({"artifact", "source"})
CONSOLIDATION_DEFERRED_TAX_ARTIFACT_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "organization_id",
        "legal_entity_id",
        "acquisition_id",
        "subsidiary_entity_code",
        "period_id",
        "acquisition_date",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "request_payload",
        "result_payload",
        "posted",
        "prepared_by",
        "approved_by",
        "approved_at",
        "created_at",
    }
)
CONSOLIDATION_DEFERRED_TAX_REQUEST_FIELDS = frozenset(
    {
        "acquisition_date",
        "acquisition_id",
        "approved_at",
        "approved_by",
        "deferred_tax_asset_account_code",
        "deferred_tax_liability_account_code",
        "items",
        "period_id",
        "policy_id",
        "policy_version",
        "prepared_at",
        "prepared_by",
        "reporting_currency",
        "source_digest",
        "source_reference",
        "subsidiary_entity_code",
    }
)
CONSOLIDATION_DEFERRED_TAX_ITEM_FIELDS = frozenset(
    {
        "account_code",
        "fair_value",
        "item_id",
        "item_kind",
        "source_reference",
        "tax_basis",
        "tax_basis_reference",
        "tax_rate",
    }
)
CONSOLIDATION_DEFERRED_TAX_RESULT_FIELDS = frozenset(
    {
        "acquisition_id",
        "algorithm_version",
        "deferred_tax_asset",
        "deferred_tax_liability",
        "items",
        "net_deferred_tax",
        "posted",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "schema_version",
    }
)
CONSOLIDATION_DEFERRED_TAX_RESULT_ITEM_FIELDS = CONSOLIDATION_DEFERRED_TAX_ITEM_FIELDS | frozenset(
    {"classification", "tax_amount", "temporary_difference"}
)
CONSOLIDATION_DEFERRED_TAX_RESPONSE_FIELDS = frozenset({"artifact", "source"})

# Legacy audit events have two physical response shapes: the local SQLite
# ledger uses ``id``/``actor_label``/``object_id`` while the PostgreSQL ledger
# uses ``event_id``/``actor_id``/``resource_id``.  Keep one closed response
# policy for both adapters.  Sensitive values are retained only as a stable
# redaction marker for backward-compatible keys; unknown adapter fields are
# denied rather than copied into the API response.
AUDIT_EVENT_FIELDS = frozenset(
    {
        "id",
        "sequence",
        "event_sequence",
        "previous_hash",
        "previous_event_hash",
        "event_hash",
        "event_id",
        "actor_user_id",
        "actor_id",
        "actor_label",
        "object_type",
        "resource_type",
        "object_id",
        "resource_id",
        "action",
        "before_hash",
        "before_state_hash",
        "after_hash",
        "after_state_hash",
        "created_at",
        "occurred_at",
        "tenant_id",
        "request_id",
        "reason",
        "metadata",
    }
)
AUDIT_EVENT_SENSITIVE_FIELDS = frozenset(
    {
        "tenant_id",
        "actor_user_id",
        "actor_id",
        "actor_label",
        "object_id",
        "resource_id",
        "request_id",
        "reason",
        "metadata",
    }
)
AUDIT_VERIFICATION_FIELDS = frozenset({"ok", "checked_events", "head_hash", "issues"})
AUDIT_VERIFICATION_ISSUE_FIELDS = frozenset({"sequence", "message"})


@dataclass(frozen=True)
class FieldProjection:
    """Allowlisted projection with explicit masked and denied field evidence."""

    visible: dict[str, object]
    masked_fields: tuple[str, ...]
    denied_fields: tuple[str, ...]
    projection_digest: str


def project_fields(
    values: Mapping[str, object],
    *,
    allowed_fields: frozenset[str],
    masked_fields: frozenset[str] = frozenset(),
    mask_value: object = REDACTED_VALUE,
) -> FieldProjection:
    """Project only authorized fields; masking never silently becomes access."""
    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping")
    if not masked_fields.issubset(allowed_fields):
        raise ValueError("masked fields must be a subset of allowed fields")
    visible: dict[str, object] = {}
    masked: list[str] = []
    denied: list[str] = []
    for name in sorted(values):
        if name not in allowed_fields:
            denied.append(name)
        elif name in masked_fields:
            visible[name] = mask_value
            masked.append(name)
        else:
            visible[name] = values[name]
    digest_payload = {
        "masked_fields": masked,
        "denied_fields": denied,
        "mask_value": mask_value,
        "visible": visible,
        "version": "field-projection-v1",
    }
    digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    return FieldProjection(visible, tuple(masked), tuple(denied), digest)


def project_evidence_drill_down_record(
    values: Mapping[str, object],
    *,
    include_sensitive: bool,
    legacy_mask_value: str = "***redacted***",
) -> FieldProjection:
    """Return the versioned, fail-closed evidence response projection.

    The repositories may expose different physical schemas (SQLite and
    PostgreSQL) and may gain columns over time.  The API therefore projects
    both modes from one response allowlist.  Public reads retain the existing
    redaction token for compatibility; sensitive reads still cannot expose an
    unreviewed future column.
    """

    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping")
    record = dict(values)
    links = record.get("links")
    if isinstance(links, list):
        projected_links: list[dict[str, object]] = []
        for link in links:
            if not isinstance(link, Mapping):
                raise TypeError("evidence links must be mappings")
            link_projection = project_fields(
                link,
                allowed_fields=EVIDENCE_DRILL_DOWN_LINK_FIELDS,
                masked_fields=frozenset(),
            )
            projected_links.append(link_projection.visible)
        record["links"] = projected_links
    elif links is not None:
        raise TypeError("evidence links must be a list")

    masked_fields = frozenset() if include_sensitive else EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS
    return project_fields(
        record,
        allowed_fields=EVIDENCE_DRILL_DOWN_FIELDS,
        masked_fields=masked_fields,
        mask_value=legacy_mask_value,
    )


def project_auth_me(values: Mapping[str, object]) -> FieldProjection:
    """Return the bounded identity snapshot exposed by ``/auth/me``."""

    record = dict(values)
    scopes = record.get("authorized_scopes")
    if scopes is not None:
        if not isinstance(scopes, Mapping):
            raise TypeError("auth identity authorized scopes must be a mapping")
        record["authorized_scopes"] = project_fields(
            scopes, allowed_fields=AUTH_ME_SCOPE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=AUTH_ME_FIELDS)


def project_scope_grant(values: Mapping[str, object]) -> FieldProjection:
    """Return the non-revoked scope-grant fields safe for administration reads."""

    return project_fields(values, allowed_fields=SCOPE_GRANT_FIELDS)


def project_identity_user(values: Mapping[str, object]) -> FieldProjection:
    """Return the reviewed identity fields safe for administration responses."""

    return project_fields(values, allowed_fields=IDENTITY_USER_FIELDS)


def project_identity_session(values: Mapping[str, object]) -> FieldProjection:
    """Return the reviewed session metadata without credentials or raw network data."""

    return project_fields(values, allowed_fields=IDENTITY_SESSION_FIELDS)


def project_identity_user_page(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed identity-user page with a bounded pagination envelope."""

    record = dict(values)
    users = record.get("users")
    if users is not None:
        if not isinstance(users, (list, tuple)):
            raise TypeError("identity users collection must be a list or tuple")
        projected_users = [
            project_identity_user(user).visible
            for user in users
            if isinstance(user, Mapping)
        ]
        if len(projected_users) != len(users):
            raise TypeError("identity user record must be a mapping")
        record["users"] = projected_users
    pagination = record.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, Mapping):
            raise TypeError("identity pagination must be a mapping")
        record["pagination"] = project_fields(pagination, allowed_fields=IDENTITY_PAGINATION_FIELDS).visible
    return project_fields(record, allowed_fields=IDENTITY_USER_PAGE_FIELDS)


def project_identity_session_page(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed identity-session page with bounded pagination metadata."""

    record = dict(values)
    sessions = record.get("sessions")
    if sessions is not None:
        if not isinstance(sessions, (list, tuple)):
            raise TypeError("identity sessions collection must be a list or tuple")
        projected_sessions = [
            project_identity_session(session).visible
            for session in sessions
            if isinstance(session, Mapping)
        ]
        if len(projected_sessions) != len(sessions):
            raise TypeError("identity session record must be a mapping")
        record["sessions"] = projected_sessions
    pagination = record.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, Mapping):
            raise TypeError("identity pagination must be a mapping")
        record["pagination"] = project_fields(pagination, allowed_fields=IDENTITY_PAGINATION_FIELDS).visible
    return project_fields(record, allowed_fields=IDENTITY_SESSION_PAGE_FIELDS)


def project_identity_user_status(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed user status transition response."""

    record = dict(values)
    user = record.get("user")
    if user is not None:
        if not isinstance(user, Mapping):
            raise TypeError("identity status user must be a mapping")
        record["user"] = project_identity_user(user).visible
    return project_fields(record, allowed_fields=IDENTITY_USER_STATUS_FIELDS)


def project_identity_session_revocation(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed session revocation response."""

    record = dict(values)
    session = record.get("session")
    if session is not None:
        if not isinstance(session, Mapping):
            raise TypeError("identity revocation session must be a mapping")
        record["session"] = project_identity_session(session).visible
    return project_fields(record, allowed_fields=IDENTITY_SESSION_REVOCATION_FIELDS)


def project_local_role(values: Mapping[str, object]) -> FieldProjection:
    """Return the closed local-role inspection fields."""

    return project_fields(values, allowed_fields=LOCAL_ROLE_FIELDS)


def project_local_role_permissions(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed local-role permission listing."""

    record = dict(values)
    permissions = record.get("permissions")
    if not isinstance(permissions, (list, tuple)) or not all(isinstance(item, str) for item in permissions):
        raise TypeError("local role permissions must be a list or tuple of strings")
    record["permissions"] = list(permissions)
    if not isinstance(record.get("role"), str):
        raise TypeError("local role name must be a string")
    return project_fields(record, allowed_fields=LOCAL_ROLE_PERMISSIONS_FIELDS)


def project_access_permission(values: Mapping[str, object]) -> FieldProjection:
    """Return the reviewed permission registry fields."""

    return project_fields(values, allowed_fields=ACCESS_PERMISSION_FIELDS)


def project_access_role(values: Mapping[str, object]) -> FieldProjection:
    """Return the reviewed role lifecycle fields."""

    return project_fields(values, allowed_fields=ACCESS_ROLE_FIELDS)


def project_access_role_page(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed role page with bounded pagination metadata."""

    record = dict(values)
    roles = record.get("roles")
    if roles is not None:
        if not isinstance(roles, (list, tuple)):
            raise TypeError("access roles collection must be a list or tuple")
        projected_roles = [
            project_access_role(role).visible
            for role in roles
            if isinstance(role, Mapping)
        ]
        if len(projected_roles) != len(roles):
            raise TypeError("access role record must be a mapping")
        record["roles"] = projected_roles
    pagination = record.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, Mapping):
            raise TypeError("access pagination must be a mapping")
        record["pagination"] = project_fields(pagination, allowed_fields=ACCESS_PAGINATION_FIELDS).visible
    return project_fields(record, allowed_fields=ACCESS_ROLE_PAGE_FIELDS)


def project_access_role_change(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed role lifecycle mutation response."""

    record = dict(values)
    role = record.get("role")
    if role is not None:
        if not isinstance(role, Mapping):
            raise TypeError("access role change role must be a mapping")
        record["role"] = project_access_role(role).visible
    return project_fields(record, allowed_fields=ACCESS_ROLE_CHANGE_FIELDS)


def project_access_user_role_assignment(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed user-role assignment response."""

    return project_fields(values, allowed_fields=ACCESS_USER_ROLE_ASSIGNMENT_FIELDS)


def project_access_policy_analysis(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed, explainable policy-conflict analysis result."""

    record = dict(values)
    findings = record.get("findings")
    if findings is not None:
        if not isinstance(findings, (list, tuple)):
            raise TypeError("access policy findings collection must be a list or tuple")
        projected_findings = [
            project_fields(finding, allowed_fields=ACCESS_POLICY_ANALYSIS_FINDING_FIELDS).visible
            for finding in findings
            if isinstance(finding, Mapping)
        ]
        if len(projected_findings) != len(findings):
            raise TypeError("access policy finding must be a mapping")
        record["findings"] = projected_findings
    return project_fields(record, allowed_fields=ACCESS_POLICY_ANALYSIS_FIELDS)


def project_security_integration(values: Mapping[str, object]) -> FieldProjection:
    """Return reviewed integration metadata without credentials or secrets."""

    return project_fields(values, allowed_fields=SECURITY_INTEGRATION_FIELDS)


def project_security_integration_page(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed integration page with bounded pagination."""

    record = dict(values)
    integrations = record.get("integrations")
    if integrations is not None:
        if not isinstance(integrations, (list, tuple)):
            raise TypeError("security integrations collection must be a list or tuple")
        projected_integrations = [
            project_security_integration(item).visible
            for item in integrations
            if isinstance(item, Mapping)
        ]
        if len(projected_integrations) != len(integrations):
            raise TypeError("security integration record must be a mapping")
        record["integrations"] = projected_integrations
    pagination = record.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, Mapping):
            raise TypeError("security pagination must be a mapping")
        record["pagination"] = project_fields(pagination, allowed_fields=SECURITY_PAGINATION_FIELDS).visible
    return project_fields(record, allowed_fields=SECURITY_INTEGRATION_PAGE_FIELDS)


def project_security_integration_disable(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed integration-disable response."""

    record = dict(values)
    integration = record.get("integration")
    if integration is not None:
        if not isinstance(integration, Mapping):
            raise TypeError("security integration change must be a mapping")
        record["integration"] = project_security_integration(integration).visible
    return project_fields(record, allowed_fields=SECURITY_INTEGRATION_DISABLE_FIELDS)


def project_security_retention_policy(values: Mapping[str, object]) -> FieldProjection:
    """Return the reviewed evidence-retention policy fields."""

    return project_fields(values, allowed_fields=SECURITY_RETENTION_POLICY_FIELDS)


def project_security_retention_policy_page(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed retention-policy page with bounded pagination."""

    record = dict(values)
    policies = record.get("policies")
    if policies is not None:
        if not isinstance(policies, (list, tuple)):
            raise TypeError("security policies collection must be a list or tuple")
        projected_policies = [
            project_security_retention_policy(item).visible
            for item in policies
            if isinstance(item, Mapping)
        ]
        if len(projected_policies) != len(policies):
            raise TypeError("security retention policy record must be a mapping")
        record["policies"] = projected_policies
    pagination = record.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, Mapping):
            raise TypeError("security pagination must be a mapping")
        record["pagination"] = project_fields(pagination, allowed_fields=SECURITY_PAGINATION_FIELDS).visible
    return project_fields(record, allowed_fields=SECURITY_RETENTION_POLICY_PAGE_FIELDS)


def project_security_retention_policy_change(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed retention-policy lifecycle response."""

    record = dict(values)
    policy = record.get("policy")
    if policy is not None:
        if not isinstance(policy, Mapping):
            raise TypeError("security retention policy change must be a mapping")
        record["policy"] = project_security_retention_policy(policy).visible
    return project_fields(record, allowed_fields=SECURITY_RETENTION_POLICY_CHANGE_FIELDS)


def project_security_evidence_retention(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed evidence-retention application response."""

    return project_fields(values, allowed_fields=SECURITY_EVIDENCE_RETENTION_FIELDS)


def project_metric_dashboard(values: Mapping[str, object]) -> FieldProjection:
    """Return the bounded dashboard snapshot fields exposed by the API."""

    return project_fields(values, allowed_fields=METRIC_DASHBOARD_FIELDS)


def project_metric_lineage(values: Mapping[str, object]) -> FieldProjection:
    """Return the bounded metric definition and lineage fields exposed by the API."""

    return project_fields(values, allowed_fields=METRIC_LINEAGE_FIELDS)


def project_audit_event(values: Mapping[str, object]) -> FieldProjection:
    """Return the redacted, fail-closed projection for a legacy audit event."""

    return project_fields(
        values,
        allowed_fields=AUDIT_EVENT_FIELDS,
        masked_fields=AUDIT_EVENT_SENSITIVE_FIELDS,
    )


def project_audit_verification(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for legacy audit-chain verification."""

    record = dict(values)
    issues = record.get("issues")
    if issues is not None:
        if not isinstance(issues, list):
            raise TypeError("audit verification issues must be a list")
        projected_issues: list[dict[str, object]] = []
        for issue in issues:
            if not isinstance(issue, Mapping):
                raise TypeError("audit verification issue must be a mapping")
            projected_issues.append(
                project_fields(issue, allowed_fields=AUDIT_VERIFICATION_ISSUE_FIELDS).visible
            )
        record["issues"] = projected_issues
    return project_fields(record, allowed_fields=AUDIT_VERIFICATION_FIELDS)


def project_evidence_requirement(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a governed evidence requirement response."""

    return project_fields(values, allowed_fields=EVIDENCE_REQUIREMENT_FIELDS)


def project_evidence_verification(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a checksum verification response."""

    return project_fields(values, allowed_fields=EVIDENCE_VERIFICATION_FIELDS)


def project_evidence_coverage(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for evidence coverage."""

    record = dict(values)
    objects = record.get("objects")
    if objects is not None:
        if not isinstance(objects, (list, tuple)):
            raise TypeError("evidence coverage objects must be a list or tuple")
        projected_objects: list[dict[str, object]] = []
        for item in objects:
            if not isinstance(item, Mapping):
                raise TypeError("evidence coverage object must be a mapping")
            projected_objects.append(
                project_fields(item, allowed_fields=EVIDENCE_COVERAGE_OBJECT_FIELDS).visible
            )
        record["objects"] = projected_objects
    return project_fields(record, allowed_fields=EVIDENCE_COVERAGE_FIELDS)


def project_writeback_intent(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a connector write-back intent."""

    record = dict(values)
    for name, allowed_fields in (
        ("approval", WRITEBACK_APPROVAL_FIELDS),
        ("acknowledgement", WRITEBACK_ACKNOWLEDGEMENT_FIELDS),
    ):
        nested = record.get(name)
        if nested is None:
            continue
        if not isinstance(nested, Mapping):
            raise TypeError(f"write-back intent {name} must be a mapping")
        record[name] = project_fields(nested, allowed_fields=allowed_fields).visible
    return project_fields(record, allowed_fields=WRITEBACK_INTENT_FIELDS)


def project_writeback_recovery_observation(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a provider recovery observation."""

    record = dict(values)
    observation = record.get("observation")
    if observation is not None:
        if not isinstance(observation, Mapping):
            raise TypeError("write-back recovery observation detail must be a mapping")
        record["observation"] = project_fields(
            observation,
            allowed_fields=WRITEBACK_RECOVERY_OBSERVATION_DETAIL_FIELDS,
        ).visible
    return project_fields(record, allowed_fields=WRITEBACK_RECOVERY_OBSERVATION_FIELDS)


def project_workflow_object(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a workflow object response."""

    return project_fields(values, allowed_fields=WORKFLOW_OBJECT_FIELDS)


def project_workflow_transition(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for an allowed workflow transition."""

    return project_fields(values, allowed_fields=WORKFLOW_TRANSITION_FIELDS)


def project_workflow_event(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a workflow history event."""

    return project_fields(values, allowed_fields=WORKFLOW_EVENT_FIELDS)


def project_evidence_link_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for evidence-link mutation responses."""

    record = dict(values)
    link = record.get("link")
    if link is not None:
        if not isinstance(link, Mapping):
            raise TypeError("evidence link must be a mapping")
        record["link"] = project_fields(
            link, allowed_fields=EVIDENCE_DRILL_DOWN_LINK_FIELDS
        ).visible
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("evidence link source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=EVIDENCE_LINK_RESPONSE_FIELDS)


def project_close_period(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for local and server close-period records."""

    return project_fields(values, allowed_fields=CLOSE_PERIOD_FIELDS)


def project_close_task(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for local and server close-task records."""

    return project_fields(values, allowed_fields=CLOSE_TASK_FIELDS)


def project_close_readiness(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for close-readiness summaries."""

    return project_fields(values, allowed_fields=CLOSE_READINESS_FIELDS)


def project_exception(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for unified exception-queue records."""

    return project_fields(values, allowed_fields=EXCEPTION_FIELDS)


def project_exception_review(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed server-review projection with versioned audit history."""

    record = dict(values)
    history = record.get("history")
    if history is not None:
        if not isinstance(history, list):
            raise TypeError("exception review history must be a list")
        record["history"] = [
            project_fields(item, allowed_fields=EXCEPTION_REVIEW_HISTORY_FIELDS).visible
            for item in history
            if isinstance(item, Mapping)
        ]
    return project_fields(record, allowed_fields=EXCEPTION_REVIEW_FIELDS)


def project_account_reconciliation(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for account reconciliation responses."""

    record = dict(values)
    items = record.get("items")
    if isinstance(items, list):
        record["items"] = [
            project_fields(item, allowed_fields=ACCOUNT_RECONCILIATION_ITEM_FIELDS).visible
            for item in items
            if isinstance(item, Mapping)
        ]
    return project_fields(record, allowed_fields=ACCOUNT_RECONCILIATION_FIELDS)


def project_reconciliation_run(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for persisted matching-run responses."""

    record = dict(values)
    for name, allowed_fields in (
        ("inputs", RECONCILIATION_INPUT_FIELDS),
        ("results", RECONCILIATION_RESULT_FIELDS),
        ("exceptions", RECONCILIATION_EXCEPTION_FIELDS),
    ):
        children = record.get(name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"reconciliation {name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"reconciliation {name} record must be a mapping")
            projected_children.append(project_fields(child, allowed_fields=allowed_fields).visible)
        record[name] = projected_children
    return project_fields(record, allowed_fields=RECONCILIATION_RUN_FIELDS)


def project_reconciliation_input(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for canonical reconciliation inputs."""

    return project_fields(values, allowed_fields=RECONCILIATION_INPUT_FIELDS)


def project_reconciliation_result(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for deterministic reconciliation results."""

    return project_fields(values, allowed_fields=RECONCILIATION_RESULT_FIELDS)


def project_reconciliation_exception(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for reconciliation exceptions."""

    return project_fields(values, allowed_fields=RECONCILIATION_EXCEPTION_FIELDS)


def project_finance_entry(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for local and server ledger entries."""

    record = dict(values)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("finance entry lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("finance entry line record must be a mapping")
            projected_lines.append(project_fields(line, allowed_fields=FINANCE_ENTRY_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    return project_fields(record, allowed_fields=FINANCE_ENTRY_FIELDS)


def project_finance_summary(values: Mapping[str, object]) -> FieldProjection:
    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("finance summary source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=FINANCE_SUMMARY_SOURCE_FIELDS).visible
    return project_fields(record, allowed_fields=FINANCE_SUMMARY_FIELDS)


def project_finance_chart(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=FINANCE_CHART_FIELDS)


def project_finance_account(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=FINANCE_ACCOUNT_FIELDS)


def project_finance_dimension(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=FINANCE_DIMENSION_FIELDS)


def project_finance_dimension_value(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=FINANCE_DIMENSION_VALUE_FIELDS)


def project_finance_journal(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=FINANCE_JOURNAL_FIELDS)


def project_finance_snapshot(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for the complete finance-core snapshot."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("finance snapshot source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=FINANCE_SNAPSHOT_SOURCE_FIELDS).visible

    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("finance snapshot summary must be a mapping")
        record["summary"] = project_finance_summary(summary).visible

    projectors: tuple[tuple[str, Callable[[Mapping[str, object]], FieldProjection]], ...] = (
        ("charts", project_finance_chart),
        ("accounts", project_finance_account),
        ("dimensions", project_finance_dimension),
        ("dimension_values", project_finance_dimension_value),
        ("journals", project_finance_journal),
        ("entries", project_finance_entry),
    )
    for name, projector in projectors:
        children = record.get(name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"finance snapshot {name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"finance snapshot {name} record must be a mapping")
            projected_children.append(projector(child).visible)
        record[name] = projected_children
    return project_fields(record, allowed_fields=FINANCE_SNAPSHOT_FIELDS)


def project_inventory_valuation_document(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for local and server valuation documents."""

    record = dict(values)
    for name, allowed_fields in (
        ("input_costs", INVENTORY_VALUATION_INPUT_COST_FIELDS),
        ("lines", INVENTORY_VALUATION_LINE_FIELDS),
        ("layer_consumptions", INVENTORY_LAYER_CONSUMPTION_FIELDS),
    ):
        children = record.get(name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"inventory valuation {name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"inventory valuation {name} record must be a mapping")
            projected_children.append(project_fields(child, allowed_fields=allowed_fields).visible)
        record[name] = projected_children
    return project_fields(record, allowed_fields=INVENTORY_VALUATION_DOCUMENT_FIELDS)


def project_inventory_valuation_policy(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_VALUATION_POLICY_FIELDS)


def project_inventory_cost_layer(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_COST_LAYER_FIELDS)


def project_inventory_valuation_summary(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_VALUATION_SUMMARY_FIELDS)


def project_inventory_valuation_snapshot(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for the valuation snapshot."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory valuation snapshot source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_VALUATION_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory valuation snapshot summary must be a mapping")
        record["summary"] = project_inventory_valuation_summary(summary).visible
    for name, projector in (
        ("policies", project_inventory_valuation_policy),
        ("documents", project_inventory_valuation_document),
        ("open_cost_layers", project_inventory_cost_layer),
    ):
        children = record.get(name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"inventory valuation snapshot {name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"inventory valuation snapshot {name} record must be a mapping")
            projected_children.append(projector(child).visible)
        record[name] = projected_children
    return project_fields(record, allowed_fields=INVENTORY_VALUATION_SNAPSHOT_FIELDS)


def project_inventory_valuation_reversal(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for valuation-reversal responses."""

    record = dict(values)
    effects = record.get("effects")
    if effects is not None:
        if not isinstance(effects, list):
            raise TypeError("inventory valuation reversal effects collection must be a list")
        projected_effects: list[dict[str, object]] = []
        for effect in effects:
            if not isinstance(effect, Mapping):
                raise TypeError("inventory valuation reversal effect record must be a mapping")
            projected_effects.append(project_fields(effect, allowed_fields=INVENTORY_VALUATION_REVERSAL_EFFECT_FIELDS).visible)
        record["effects"] = projected_effects
    return project_fields(record, allowed_fields=INVENTORY_VALUATION_REVERSAL_FIELDS)


def project_inventory_valuation_reversal_summary(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_VALUATION_REVERSAL_SUMMARY_FIELDS)


def project_inventory_valuation_reversal_snapshot(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for the reversal snapshot."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory valuation reversal snapshot source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_VALUATION_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory valuation reversal snapshot summary must be a mapping")
        record["summary"] = project_inventory_valuation_reversal_summary(summary).visible
    reversals = record.get("reversals")
    if reversals is not None:
        if not isinstance(reversals, list):
            raise TypeError("inventory valuation reversal snapshot reversals collection must be a list")
        projected_reversals: list[dict[str, object]] = []
        for reversal in reversals:
            if not isinstance(reversal, Mapping):
                raise TypeError("inventory valuation reversal snapshot reversal must be a mapping")
            projected_reversals.append(project_inventory_valuation_reversal(reversal).visible)
        record["reversals"] = projected_reversals
    return project_fields(record, allowed_fields=INVENTORY_VALUATION_REVERSAL_SNAPSHOT_FIELDS)


def project_inventory_uom(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_UOM_FIELDS)


def project_inventory_item(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_ITEM_FIELDS)


def project_inventory_warehouse(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_WAREHOUSE_FIELDS)


def project_inventory_location(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_LOCATION_FIELDS)


def project_inventory_lot(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_LOT_FIELDS)


def project_inventory_movement(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for inventory movement responses."""

    record = dict(values)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("inventory movement lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("inventory movement line record must be a mapping")
            projected_lines.append(project_fields(line, allowed_fields=INVENTORY_MOVEMENT_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    return project_fields(record, allowed_fields=INVENTORY_MOVEMENT_FIELDS)


def project_inventory_on_hand(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for exact inventory balances."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory on-hand source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_ON_HAND_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory on-hand summary must be a mapping")
        record["summary"] = project_fields(summary, allowed_fields=INVENTORY_ON_HAND_SUMMARY_FIELDS).visible
    balances = record.get("balances")
    if balances is not None:
        if not isinstance(balances, list):
            raise TypeError("inventory on-hand balances collection must be a list")
        projected_balances: list[dict[str, object]] = []
        for balance in balances:
            if not isinstance(balance, Mapping):
                raise TypeError("inventory on-hand balance record must be a mapping")
            projected_balances.append(project_fields(balance, allowed_fields=INVENTORY_ON_HAND_BALANCE_FIELDS).visible)
        record["balances"] = projected_balances
    return project_fields(record, allowed_fields=INVENTORY_ON_HAND_FIELDS)


def project_inventory_control_exceptions(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for inventory control exceptions."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory control exception source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_CONTROL_EXCEPTION_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory control exception summary must be a mapping")
        record["summary"] = project_fields(summary, allowed_fields=INVENTORY_CONTROL_EXCEPTION_SUMMARY_FIELDS).visible
    exceptions = record.get("exceptions")
    if exceptions is not None:
        if not isinstance(exceptions, list):
            raise TypeError("inventory control exceptions collection must be a list")
        projected_exceptions: list[dict[str, object]] = []
        for exception in exceptions:
            if not isinstance(exception, Mapping):
                raise TypeError("inventory control exception record must be a mapping")
            projected_exceptions.append(project_fields(exception, allowed_fields=INVENTORY_CONTROL_EXCEPTION_ITEM_FIELDS).visible)
        record["exceptions"] = projected_exceptions
    return project_fields(record, allowed_fields=INVENTORY_CONTROL_EXCEPTION_FIELDS)


def project_inventory_core_summary(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_CORE_SUMMARY_FIELDS)


def project_inventory_core_snapshot(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for the bounded inventory snapshot."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory core snapshot source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_CORE_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory core snapshot summary must be a mapping")
        record["summary"] = project_inventory_core_summary(summary).visible
    for name, projector in (
        ("units_of_measure", project_inventory_uom),
        ("items", project_inventory_item),
        ("warehouses", project_inventory_warehouse),
        ("locations", project_inventory_location),
        ("lots_and_serials", project_inventory_lot),
        ("movements", project_inventory_movement),
    ):
        children = record.get(name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"inventory core snapshot {name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"inventory core snapshot {name} record must be a mapping")
            projected_children.append(projector(child).visible)
        record[name] = projected_children
    return project_fields(record, allowed_fields=INVENTORY_CORE_SNAPSHOT_FIELDS)


def project_inventory_planning_summary(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_PLANNING_SUMMARY_FIELDS)


def project_inventory_planning_session(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for physical-count sessions."""

    record = dict(values)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("inventory planning count-session lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("inventory planning count-session line must be a mapping")
            projected_lines.append(project_fields(line, allowed_fields=INVENTORY_PLANNING_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory planning count-session summary must be a mapping")
        record["summary"] = project_fields(summary, allowed_fields=INVENTORY_PLANNING_SESSION_SUMMARY_FIELDS).visible
    return project_fields(record, allowed_fields=INVENTORY_PLANNING_SESSION_FIELDS)


def project_inventory_reorder_rule(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=INVENTORY_REORDER_RULE_FIELDS)


def project_inventory_reorder_signals(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for deterministic reorder signals."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory reorder signals source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_REORDER_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory reorder signals summary must be a mapping")
        record["summary"] = project_fields(summary, allowed_fields=INVENTORY_REORDER_SUMMARY_FIELDS).visible
    pagination = record.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, Mapping):
            raise TypeError("inventory reorder signals pagination must be a mapping")
        record["pagination"] = project_fields(pagination, allowed_fields=INVENTORY_REORDER_PAGINATION_FIELDS).visible
    signals = record.get("signals")
    if signals is not None:
        if not isinstance(signals, list):
            raise TypeError("inventory reorder signals collection must be a list")
        projected_signals: list[dict[str, object]] = []
        for signal in signals:
            if not isinstance(signal, Mapping):
                raise TypeError("inventory reorder signal must be a mapping")
            projected_signals.append(project_fields(signal, allowed_fields=INVENTORY_REORDER_SIGNAL_FIELDS).visible)
        record["signals"] = projected_signals
    return project_fields(record, allowed_fields=INVENTORY_REORDER_SIGNALS_FIELDS)


def project_inventory_planning_snapshot(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for the inventory planning snapshot."""

    record = dict(values)
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("inventory planning snapshot source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=INVENTORY_REORDER_SOURCE_FIELDS).visible
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("inventory planning snapshot summary must be a mapping")
        record["summary"] = project_fields(summary, allowed_fields=INVENTORY_CORE_SUMMARY_FIELDS | INVENTORY_PLANNING_SUMMARY_FIELDS).visible
    for field_name, projector in (
        ("count_sessions", project_inventory_planning_session),
        ("reorder_rules", project_inventory_reorder_rule),
    ):
        children = record.get(field_name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"inventory planning snapshot {field_name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"inventory planning snapshot {field_name} record must be a mapping")
            projected_children.append(projector(child).visible)
        record[field_name] = projected_children
    return project_fields(record, allowed_fields=INVENTORY_PLANNING_SNAPSHOT_FIELDS)


def project_individual_cashflow(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for individual cashflow results."""

    record = dict(values)
    decisions = record.get("decisions")
    if decisions is not None:
        if not isinstance(decisions, list):
            raise TypeError("individual cashflow decisions collection must be a list")
        projected_decisions: list[dict[str, object]] = []
        for decision in decisions:
            if not isinstance(decision, Mapping):
                raise TypeError("individual cashflow decision must be a mapping")
            decision_record = dict(decision)
            for field_name in ("actual", "budget", "variance"):
                money = decision_record.get(field_name)
                if money is None:
                    continue
                if not isinstance(money, Mapping):
                    raise TypeError(f"individual cashflow decision {field_name} must be a mapping")
                decision_record[field_name] = project_fields(
                    money,
                    allowed_fields=INDIVIDUAL_CASHFLOW_MONEY_FIELDS,
                ).visible
            transaction_ids = decision_record.get("transaction_ids")
            if transaction_ids is not None:
                if not isinstance(transaction_ids, list):
                    raise TypeError("individual cashflow transaction IDs must be a list")
                decision_record["transaction_ids"] = list(transaction_ids)
            projected_decisions.append(
                project_fields(
                    decision_record,
                    allowed_fields=INDIVIDUAL_CASHFLOW_DECISION_FIELDS,
                ).visible
            )
        record["decisions"] = projected_decisions
    status_counts = record.get("status_counts")
    if status_counts is not None:
        if not isinstance(status_counts, Mapping):
            raise TypeError("individual cashflow status counts must be a mapping")
        record["status_counts"] = {
            str(key): value
            for key, value in status_counts.items()
            if str(key) in INDIVIDUAL_CASHFLOW_STATUS_FIELDS
        }
    input_digests = record.get("input_digests")
    if input_digests is not None:
        if not isinstance(input_digests, list):
            raise TypeError("individual cashflow input digests must be a list")
        record["input_digests"] = list(input_digests)
    return project_fields(record, allowed_fields=INDIVIDUAL_CASHFLOW_FIELDS)


def project_payables_supplier(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for Accounts Payable supplier responses."""

    return project_fields(values, allowed_fields=PAYABLES_SUPPLIER_FIELDS)


def project_payables_purchase_order(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for purchase-order responses."""

    record = dict(values)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("payables purchase-order lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("payables purchase-order line record must be a mapping")
            projected_lines.append(project_fields(line, allowed_fields=PAYABLES_PURCHASE_ORDER_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    return project_fields(record, allowed_fields=PAYABLES_PURCHASE_ORDER_FIELDS)


def project_payables_receipt(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for goods-receipt responses."""

    record = dict(values)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("payables receipt lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("payables receipt line record must be a mapping")
            projected_lines.append(project_fields(line, allowed_fields=PAYABLES_RECEIPT_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    return project_fields(record, allowed_fields=PAYABLES_RECEIPT_FIELDS)


def project_payables_three_way_match(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a deterministic three-way-match result."""

    return project_fields(values, allowed_fields=PAYABLES_THREE_WAY_MATCH_FIELDS)


def project_payables_supplier_invoice(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for supplier-invoice responses."""

    record = dict(values)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("payables supplier-invoice lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("payables supplier-invoice line record must be a mapping")
            projected_lines.append(project_fields(line, allowed_fields=PAYABLES_SUPPLIER_INVOICE_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    match = record.get("three_way_match")
    if match is not None:
        if not isinstance(match, Mapping):
            raise TypeError("payables supplier-invoice match must be a mapping")
        record["three_way_match"] = project_payables_three_way_match(match).visible
    return project_fields(record, allowed_fields=PAYABLES_SUPPLIER_INVOICE_FIELDS)


RECEIVABLES_MONETARY_POLICY_FIELDS = frozenset({
    "schema_version", "status", "currency_code", "precision", "rounding_policy",
    "registry_version", "registry_digest", "policy_digest", "source", "source_url", "published_at",
})


def _receivables_record(
    values: Mapping[str, object], minor_fields: tuple[str, ...], *, policy: bool = False,
) -> dict[str, object]:
    """Project retained authority; exact text is derived, never trusted from input."""
    record = dict(values)
    for field in minor_fields:
        record.pop(field + "_text", None)
        if field in record:
            amount = record[field]
            if type(amount) is not int:
                raise TypeError("receivables minor units must be exact integers")
            record[field + "_text"] = str(amount)
    if policy and "monetary_policy" in record:
        raw = record["monetary_policy"]
        if not isinstance(raw, Mapping) or not raw.keys() >= RECEIVABLES_MONETARY_POLICY_FIELDS:
            raise TypeError("receivables monetary policy must be a complete mapping")
        public = project_fields(raw, allowed_fields=RECEIVABLES_MONETARY_POLICY_FIELDS).visible
        currency = public["currency_code"]
        if (type(public["schema_version"]) is not int or public["schema_version"] != 1
                or not isinstance(currency, str) or len(currency) != 3
                or currency != record.get("currency_code")):
            raise TypeError("receivables monetary policy identity is invalid")
        interpretation = RECEIVABLES_MONETARY_POLICY_FIELDS - {"schema_version", "status", "currency_code"}
        if public["status"] == "unverified":
            if any(public[key] is not None for key in interpretation):
                raise TypeError("unverified receivables policy cannot assert an interpretation")
        elif public["status"] == "captured":
            precision = public["precision"]
            if (not re.fullmatch(r"[A-Z]{3}", currency) or type(precision) is not int
                    or not 0 <= precision <= 8 or public["rounding_policy"] != "ROUND_HALF_UP"):
                raise TypeError("captured receivables policy precision is invalid")
            version = public["registry_version"]
            if not isinstance(version, str) or not 1 <= len(version) <= 128:
                raise TypeError("captured receivables registry version is invalid")
            for key in ("registry_digest", "policy_digest"):
                digest = public[key]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise TypeError("captured receivables policy digest is invalid")
            for key in ("source", "source_url", "published_at"):
                provenance = public[key]
                if not isinstance(provenance, str) or len(provenance) > 4096:
                    raise TypeError("captured receivables policy provenance is invalid")
        else:
            raise TypeError("receivables monetary policy status is invalid")
        record["monetary_policy"] = public
    return record


def project_receivables_customer(values: Mapping[str, object]) -> FieldProjection:
    record = _receivables_record(values, ("credit_limit_minor",), policy=True)
    return project_fields(record, allowed_fields=RECEIVABLES_CUSTOMER_FIELDS)


def project_receivables_invoice(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for receivable-invoice responses."""

    record = _receivables_record(values, ("subtotal_minor", "tax_minor", "total_minor", "allocated_minor", "outstanding_minor"), policy=True)
    lines = record.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("receivables invoice lines collection must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("receivables invoice line record must be a mapping")
            exact = _receivables_record(line, ("unit_price_minor", "line_total_minor", "tax_minor"))
            projected_lines.append(project_fields(exact, allowed_fields=RECEIVABLES_INVOICE_LINE_FIELDS).visible)
        record["lines"] = projected_lines
    return project_fields(record, allowed_fields=RECEIVABLES_INVOICE_FIELDS)


def project_receivables_receipt(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for receivables receipt responses."""

    record = _receivables_record(values, ("amount_minor", "allocated_minor", "unallocated_minor"), policy=True)
    allocations = record.get("allocations")
    if allocations is not None:
        if not isinstance(allocations, list):
            raise TypeError("receivables receipt allocations collection must be a list")
        projected_allocations: list[dict[str, object]] = []
        for allocation in allocations:
            if not isinstance(allocation, Mapping):
                raise TypeError("receivables receipt allocation record must be a mapping")
            exact = _receivables_record(allocation, ("amount_minor",))
            projected_allocations.append(project_fields(exact, allowed_fields=RECEIVABLES_ALLOCATION_FIELDS).visible)
        record["allocations"] = projected_allocations
    return project_fields(record, allowed_fields=RECEIVABLES_RECEIPT_FIELDS)


def project_receivables_credit_exposure(values: Mapping[str, object]) -> FieldProjection:
    record = _receivables_record(values, ("credit_limit_minor", "exposure_minor", "available_credit_minor"))
    return project_fields(record, allowed_fields=RECEIVABLES_CREDIT_EXPOSURE_FIELDS)


def project_receivables_aging(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for scoped receivables aging results."""

    record = dict(values)
    items = record.get("items")
    if items is not None:
        if not isinstance(items, list):
            raise TypeError("receivables aging items collection must be a list")
        projected_items: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, Mapping):
                raise TypeError("receivables aging item record must be a mapping")
            projected_items.append(project_fields(item, allowed_fields=RECEIVABLES_AGING_ITEM_FIELDS).visible)
        record["items"] = projected_items
    return project_fields(record, allowed_fields=RECEIVABLES_AGING_FIELDS)


def project_receivables_aging_by_currency(values: Mapping[str, object]) -> FieldProjection:
    """Project currency groups recursively without exposing internal fields."""

    record = dict(values)
    groups = record.get("currency_groups")
    if not isinstance(groups, list):
        raise TypeError("receivables aging currency groups must be a list")
    projected_groups: list[dict[str, object]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            raise TypeError("receivables aging currency group must be a mapping")
        projected_groups.append(project_fields(
            project_receivables_aging(group).visible, allowed_fields=RECEIVABLES_AGING_GROUP_FIELDS,
        ).visible)
    record["currency_groups"] = projected_groups
    return project_fields(record, allowed_fields=RECEIVABLES_GROUPED_AGING_FIELDS)


def project_professional_invoice_payment(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for professional-control evidence."""

    record = dict(values)
    report = record.get("report")
    if report is not None:
        if not isinstance(report, Mapping):
            raise TypeError("professional invoice/payment report must be a mapping")
        report_record = dict(report)
        amount_tolerance = report_record.get("amount_tolerance")
        if amount_tolerance is not None:
            if not isinstance(amount_tolerance, Mapping):
                raise TypeError("professional invoice/payment tolerance must be a mapping")
            report_record["amount_tolerance"] = project_fields(
                amount_tolerance,
                allowed_fields=PROFESSIONAL_INVOICE_PAYMENT_MONEY_FIELDS,
            ).visible
        decisions = report_record.get("decisions")
        if decisions is not None:
            if not isinstance(decisions, list):
                raise TypeError("professional invoice/payment decisions collection must be a list")
            projected_decisions: list[dict[str, object]] = []
            for decision in decisions:
                if not isinstance(decision, Mapping):
                    raise TypeError("professional invoice/payment decision must be a mapping")
                decision_record = dict(decision)
                amount_variance = decision_record.get("amount_variance")
                if amount_variance is not None:
                    if not isinstance(amount_variance, Mapping):
                        raise TypeError("professional invoice/payment variance must be a mapping")
                    decision_record["amount_variance"] = project_fields(
                        amount_variance,
                        allowed_fields=PROFESSIONAL_INVOICE_PAYMENT_MONEY_FIELDS,
                    ).visible
                projected_decisions.append(
                    project_fields(
                        decision_record,
                        allowed_fields=PROFESSIONAL_INVOICE_PAYMENT_DECISION_FIELDS,
                    ).visible
                )
            report_record["decisions"] = projected_decisions
        status_counts = report_record.get("status_counts")
        if status_counts is not None:
            if not isinstance(status_counts, Mapping):
                raise TypeError("professional invoice/payment status counts must be a mapping")
            report_record["status_counts"] = {
                key: status_counts[key]
                for key in sorted(status_counts)
                if key in PROFESSIONAL_INVOICE_PAYMENT_STATUS_KEYS
            }
        record["report"] = project_fields(
            report_record,
            allowed_fields=PROFESSIONAL_INVOICE_PAYMENT_REPORT_FIELDS,
        ).visible
    return project_fields(record, allowed_fields=PROFESSIONAL_INVOICE_PAYMENT_FIELDS)


def project_retail_settlement(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for retail settlement evidence."""

    record = dict(values)
    report = record.get("report")
    if report is not None:
        if not isinstance(report, Mapping):
            raise TypeError("retail settlement report must be a mapping")
        report_record = dict(report)
        tolerance = report_record.get("tolerance")
        if tolerance is not None:
            if not isinstance(tolerance, Mapping):
                raise TypeError("retail settlement tolerance must be a mapping")
            report_record["tolerance"] = project_fields(
                tolerance,
                allowed_fields=RETAIL_SETTLEMENT_MONEY_FIELDS,
            ).visible
        decisions = report_record.get("decisions")
        if decisions is not None:
            if not isinstance(decisions, list):
                raise TypeError("retail settlement decisions collection must be a list")
            projected_decisions: list[dict[str, object]] = []
            for decision in decisions:
                if not isinstance(decision, Mapping):
                    raise TypeError("retail settlement decision must be a mapping")
                decision_record = dict(decision)
                for field_name in (
                    "card_gross_variance",
                    "expected_card_net",
                    "net_variance",
                    "pos_total_net_sales",
                    "refund_variance",
                    "settlement_net",
                ):
                    amount = decision_record.get(field_name)
                    if amount is None:
                        continue
                    if not isinstance(amount, Mapping):
                        raise TypeError(f"retail settlement {field_name} must be a mapping")
                    decision_record[field_name] = project_fields(
                        amount,
                        allowed_fields=RETAIL_SETTLEMENT_MONEY_FIELDS,
                    ).visible
                projected_decisions.append(
                    project_fields(
                        decision_record,
                        allowed_fields=RETAIL_SETTLEMENT_DECISION_FIELDS,
                    ).visible
                )
            report_record["decisions"] = projected_decisions
        status_counts = report_record.get("status_counts")
        if status_counts is not None:
            if not isinstance(status_counts, Mapping):
                raise TypeError("retail settlement status counts must be a mapping")
            report_record["status_counts"] = {
                key: status_counts[key]
                for key in sorted(status_counts)
                if key in RETAIL_SETTLEMENT_STATUS_KEYS
            }
        record["report"] = project_fields(
            report_record,
            allowed_fields=RETAIL_SETTLEMENT_REPORT_FIELDS,
        ).visible
    return project_fields(record, allowed_fields=RETAIL_SETTLEMENT_FIELDS)


def project_bank_statement(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for bank statement evidence."""

    record = dict(values)
    report = record.get("report")
    if report is not None:
        if not isinstance(report, Mapping):
            raise TypeError("bank statement report must be a mapping")
        report_record = dict(report)
        amount_tolerance = report_record.get("amount_tolerance")
        if amount_tolerance is not None:
            if not isinstance(amount_tolerance, Mapping):
                raise TypeError("bank statement amount tolerance must be a mapping")
            report_record["amount_tolerance"] = project_fields(
                amount_tolerance,
                allowed_fields=BANK_STATEMENT_MONEY_FIELDS,
            ).visible
        decisions = report_record.get("decisions")
        if decisions is not None:
            if not isinstance(decisions, list):
                raise TypeError("bank statement decisions collection must be a list")
            projected_decisions: list[dict[str, object]] = []
            for decision in decisions:
                if not isinstance(decision, Mapping):
                    raise TypeError("bank statement decision must be a mapping")
                decision_record = dict(decision)
                amount_variance = decision_record.get("amount_variance")
                if amount_variance is not None:
                    if not isinstance(amount_variance, Mapping):
                        raise TypeError("bank statement amount variance must be a mapping")
                    decision_record["amount_variance"] = project_fields(
                        amount_variance,
                        allowed_fields=BANK_STATEMENT_MONEY_FIELDS,
                    ).visible
                projected_decisions.append(
                    project_fields(
                        decision_record,
                        allowed_fields=BANK_STATEMENT_DECISION_FIELDS,
                    ).visible
                )
            report_record["decisions"] = projected_decisions
        status_counts = report_record.get("status_counts")
        if status_counts is not None:
            if not isinstance(status_counts, Mapping):
                raise TypeError("bank statement status counts must be a mapping")
            report_record["status_counts"] = {
                key: status_counts[key]
                for key in sorted(status_counts)
                if key in BANK_STATEMENT_STATUS_KEYS
            }
        record["report"] = project_fields(
            report_record,
            allowed_fields=BANK_STATEMENT_REPORT_FIELDS,
        ).visible
    return project_fields(record, allowed_fields=BANK_STATEMENT_FIELDS)


def project_manufacturing_cost_control(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed recursive projection for manufacturing cost evidence."""

    record = dict(values)
    report = record.get("report")
    if report is not None:
        if not isinstance(report, Mapping):
            raise TypeError("manufacturing cost-control report must be a mapping")
        report_record = dict(report)

        def project_quantity(value: object, field_name: str) -> dict[str, object]:
            if not isinstance(value, Mapping):
                raise TypeError(f"manufacturing cost-control {field_name} must be a mapping")
            return project_fields(value, allowed_fields=MANUFACTURING_COST_CONTROL_QUANTITY_FIELDS).visible

        def project_money(value: object, field_name: str) -> dict[str, object]:
            if not isinstance(value, Mapping):
                raise TypeError(f"manufacturing cost-control {field_name} must be a mapping")
            return project_fields(value, allowed_fields=MANUFACTURING_COST_CONTROL_MONEY_FIELDS).visible

        for field_name in ("amount_tolerance",):
            value = report_record.get(field_name)
            if value is not None:
                report_record[field_name] = project_money(value, field_name)
        max_scrap_quantity = report_record.get("max_scrap_quantity")
        if max_scrap_quantity is not None:
            report_record["max_scrap_quantity"] = project_quantity(max_scrap_quantity, "max_scrap_quantity")
        decisions = report_record.get("decisions")
        if decisions is not None:
            if not isinstance(decisions, list):
                raise TypeError("manufacturing cost-control decisions collection must be a list")
            projected_decisions: list[dict[str, object]] = []
            for decision in decisions:
                if not isinstance(decision, Mapping):
                    raise TypeError("manufacturing cost-control decision must be a mapping")
                decision_record = dict(decision)
                for field_name in ("completed_quantity", "issued_quantity", "planned_quantity", "scrap_quantity"):
                    value = decision_record.get(field_name)
                    if value is not None:
                        decision_record[field_name] = project_quantity(value, field_name)
                for field_name in (
                    "actual_material_cost",
                    "completion_cost",
                    "completion_cost_variance",
                    "expected_material_cost",
                    "material_cost_variance",
                ):
                    value = decision_record.get(field_name)
                    if value is not None:
                        decision_record[field_name] = project_money(value, field_name)
                projected_decisions.append(
                    project_fields(
                        decision_record,
                        allowed_fields=MANUFACTURING_COST_CONTROL_DECISION_FIELDS,
                    ).visible
                )
            report_record["decisions"] = projected_decisions
        status_counts = report_record.get("status_counts")
        if status_counts is not None:
            if not isinstance(status_counts, Mapping):
                raise TypeError("manufacturing cost-control status counts must be a mapping")
            report_record["status_counts"] = {
                key: status_counts[key]
                for key in sorted(status_counts)
                if key in MANUFACTURING_COST_CONTROL_STATUS_KEYS
            }
        record["report"] = project_fields(
            report_record,
            allowed_fields=MANUFACTURING_COST_CONTROL_REPORT_FIELDS,
        ).visible
    return project_fields(record, allowed_fields=MANUFACTURING_COST_CONTROL_FIELDS)


def project_master_currency(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=MASTER_CURRENCY_FIELDS)


def project_master_organization(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=MASTER_ORGANIZATION_FIELDS)


def project_master_entity(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=MASTER_ENTITY_FIELDS)


def project_master_branch(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=MASTER_BRANCH_FIELDS)


def project_master_period(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=MASTER_PERIOD_FIELDS)


def project_master_summary(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=MASTER_SUMMARY_FIELDS)


def project_master_registry(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for currency-registry reconciliation."""

    record = dict(values)
    registry = record.get("registry")
    if isinstance(registry, Mapping):
        record["registry"] = project_fields(registry, allowed_fields=MASTER_REGISTRY_DETAILS_FIELDS).visible
    issues = record.get("issues")
    if isinstance(issues, list):
        projected_issues: list[dict[str, object]] = []
        for issue in issues:
            if not isinstance(issue, Mapping):
                raise TypeError("master-data registry issue must be a mapping")
            projected_issues.append(project_fields(issue, allowed_fields=MASTER_REGISTRY_ISSUE_FIELDS).visible)
        record["issues"] = projected_issues
    binding = record.get("binding")
    if isinstance(binding, Mapping):
        record["binding"] = project_fields(binding, allowed_fields=MASTER_REGISTRY_BINDING_FIELDS).visible
    return project_fields(record, allowed_fields=MASTER_REGISTRY_FIELDS)


def project_master_registry_binding(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a currency-registry binding response."""

    record = dict(values)
    binding = record.get("binding")
    if binding is not None:
        if not isinstance(binding, Mapping):
            raise TypeError("master-data registry binding must be a mapping")
        record["binding"] = project_fields(
            binding, allowed_fields=MASTER_REGISTRY_BINDING_FIELDS
        ).visible
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("master-data registry binding source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=MASTER_REGISTRY_BINDING_RESPONSE_FIELDS)


def project_master_snapshot(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for the versioned master-data snapshot."""

    record = dict(values)
    summary = record.get("summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("master-data snapshot summary must be a mapping")
        summary_record = dict(summary)
        source = summary_record.get("source")
        if isinstance(source, Mapping):
            summary_record["source"] = project_fields(
                source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
            ).visible
        record["summary"] = project_fields(
            summary_record, allowed_fields=MASTER_SNAPSHOT_SUMMARY_FIELDS
        ).visible
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("master-data snapshot source must be a mapping")
        record["source"] = project_fields(source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS).visible
    registry = record.get("currency_registry")
    if isinstance(registry, Mapping):
        registry_record = dict(registry)
        details = registry_record.get("registry")
        if isinstance(details, Mapping):
            registry_record["registry"] = project_fields(
                details, allowed_fields=MASTER_REGISTRY_DETAILS_FIELDS
            ).visible
        issues = registry_record.get("issues")
        if isinstance(issues, list):
            projected_issues: list[dict[str, object]] = []
            for issue in issues:
                if not isinstance(issue, Mapping):
                    raise TypeError("master-data registry issue must be a mapping")
                projected_issues.append(project_fields(issue, allowed_fields=MASTER_REGISTRY_ISSUE_FIELDS).visible)
            registry_record["issues"] = projected_issues
        binding = registry_record.get("binding")
        if isinstance(binding, Mapping):
            registry_record["binding"] = project_fields(
                binding, allowed_fields=MASTER_REGISTRY_BINDING_FIELDS
            ).visible
        record["currency_registry"] = project_fields(registry_record, allowed_fields=MASTER_REGISTRY_FIELDS).visible
    for name, projector in (
        ("currencies", project_master_currency),
        ("organizations", project_master_organization),
        ("legal_entities", project_master_entity),
        ("branches", project_master_branch),
        ("periods", project_master_period),
    ):
        children = record.get(name)
        if children is None:
            continue
        if not isinstance(children, list):
            raise TypeError(f"master-data snapshot {name} collection must be a list")
        projected_children: list[dict[str, object]] = []
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError(f"master-data snapshot {name} record must be a mapping")
            projected_children.append(projector(child).visible)
        record[name] = projected_children
    return project_fields(record, allowed_fields=MASTER_SNAPSHOT_FIELDS)


def project_consolidation_period(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for consolidation-close period records."""

    return project_fields(values, allowed_fields=CONSOLIDATION_PERIOD_FIELDS)


def project_consolidation_summary(values: Mapping[str, object]) -> FieldProjection:
    return project_fields(values, allowed_fields=CONSOLIDATION_SUMMARY_FIELDS)


def _project_consolidation_journal_line(value: Mapping[str, object]) -> dict[str, object]:
    return project_fields(value, allowed_fields=CONSOLIDATION_JOURNAL_LINE_FIELDS).visible


def _project_consolidation_effect(value: Mapping[str, object]) -> dict[str, object]:
    projection = project_fields(value, allowed_fields=CONSOLIDATION_EFFECT_FIELDS)
    visible = dict(projection.visible)
    lines = value.get("lines")
    if isinstance(lines, list):
        visible["lines"] = [
            project_fields(line, allowed_fields=CONSOLIDATION_EFFECT_LINE_FIELDS).visible
            for line in lines
            if isinstance(line, Mapping)
        ]
    return visible


def project_consolidation_run(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for consolidation-close run responses."""

    projection = project_fields(values, allowed_fields=CONSOLIDATION_RUN_FIELDS)
    visible = dict(projection.visible)
    journal_lines = values.get("journal_lines")
    if isinstance(journal_lines, list):
        visible["journal_lines"] = [
            _project_consolidation_journal_line(line) for line in journal_lines if isinstance(line, Mapping)
        ]
    effects = values.get("effects")
    if isinstance(effects, list):
        visible["effects"] = [_project_consolidation_effect(effect) for effect in effects if isinstance(effect, Mapping)]
    return FieldProjection(visible, projection.masked_fields, projection.denied_fields, projection.projection_digest)


def project_consolidation_certification_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for close-certification responses."""

    record = dict(values)
    certification = record.get("certification")
    if certification is not None:
        if not isinstance(certification, Mapping):
            raise TypeError("consolidation certification must be a mapping")
        record["certification"] = project_fields(
            certification, allowed_fields=CONSOLIDATION_CERTIFICATION_FIELDS
        ).visible
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("consolidation certification source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=CONSOLIDATION_CERTIFICATION_RESPONSE_FIELDS)


def project_consolidation_evidence_link_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for consolidation evidence-link responses."""

    record = dict(values)
    link = record.get("link")
    if link is not None:
        if not isinstance(link, Mapping):
            raise TypeError("consolidation evidence link must be a mapping")
        record["link"] = project_fields(
            link, allowed_fields=CONSOLIDATION_EVIDENCE_LINK_FIELDS
        ).visible
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("consolidation evidence link source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=CONSOLIDATION_EVIDENCE_LINK_RESPONSE_FIELDS)


def _project_consolidation_ownership_interest(value: Mapping[str, object]) -> dict[str, object]:
    return project_fields(value, allowed_fields=CONSOLIDATION_OWNERSHIP_INTEREST_FIELDS).visible


def _project_consolidation_ownership_source(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation ownership source must be a mapping")
    return project_fields(value, allowed_fields=CONSOLIDATION_OWNERSHIP_SOURCE_FIELDS).visible


def project_consolidation_ownership_interest_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for one ownership-interest response."""

    record = dict(values)
    interest = record.get("interest")
    if interest is not None:
        if not isinstance(interest, Mapping):
            raise TypeError("consolidation ownership interest must be a mapping")
        record["interest"] = _project_consolidation_ownership_interest(interest)
    source = record.get("source")
    if source is not None:
        record["source"] = _project_consolidation_ownership_source(source)
    return project_fields(record, allowed_fields=CONSOLIDATION_OWNERSHIP_INTEREST_RESPONSE_FIELDS)


def project_consolidation_ownership_effective_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for an effective ownership-set response."""

    record = dict(values)
    interests = record.get("interests")
    if interests is not None:
        if not isinstance(interests, list):
            raise TypeError("consolidation effective ownership interests must be a list")
        record["interests"] = [
            _project_consolidation_ownership_interest(interest)
            for interest in interests
            if isinstance(interest, Mapping)
        ]
    source = record.get("source")
    if source is not None:
        record["source"] = _project_consolidation_ownership_source(source)
    return project_fields(record, allowed_fields=CONSOLIDATION_OWNERSHIP_EFFECTIVE_RESPONSE_FIELDS)


def _project_consolidation_ppa_money(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation PPA money must be a mapping")
    return project_fields(value, allowed_fields=CONSOLIDATION_PPA_PAYLOAD_MONEY_FIELDS).visible


def _project_consolidation_ppa_item(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation PPA item must be a mapping")
    item = project_fields(value, allowed_fields=CONSOLIDATION_PPA_ITEM_FIELDS).visible
    for field in ("book_value", "fair_value", "fair_value_adjustment"):
        if field in item:
            item[field] = _project_consolidation_ppa_money(item[field])
    return item


def _project_consolidation_ppa_bridge(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation PPA bridge must be a mapping")
    bridge = project_fields(value, allowed_fields=CONSOLIDATION_PPA_BRIDGE_FIELDS).visible
    for field in ("bargain_purchase", "goodwill"):
        if field in bridge:
            bridge[field] = _project_consolidation_ppa_money(bridge[field])
    lines = bridge.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("consolidation PPA bridge lines must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("consolidation PPA bridge line must be a mapping")
            projected_line = project_fields(
                line, allowed_fields=CONSOLIDATION_PPA_BRIDGE_LINE_FIELDS
            ).visible
            if "amount" in projected_line:
                projected_line["amount"] = _project_consolidation_ppa_money(projected_line["amount"])
            projected_lines.append(projected_line)
        bridge["lines"] = projected_lines
    return bridge


def _project_consolidation_ppa_payload(
    value: object,
    *,
    allowed_fields: frozenset[str],
    result: bool,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation PPA payload must be a mapping")
    payload = project_fields(value, allowed_fields=allowed_fields).visible
    money_fields = (
        ("consideration", "nci_fair_value")
        if not result
        else ("book_net_assets", "fair_value_adjustment", "fair_value_net_assets")
    )
    for field in money_fields:
        if field in payload:
            payload[field] = _project_consolidation_ppa_money(payload[field])
    items = payload.get("items")
    if items is not None:
        if not isinstance(items, list):
            raise TypeError("consolidation PPA items must be a list")
        payload["items"] = [_project_consolidation_ppa_item(item) for item in items]
    if result and "bridge" in payload:
        payload["bridge"] = _project_consolidation_ppa_bridge(payload["bridge"])
    return payload


def project_consolidation_ppa_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a persisted PPA artifact response."""

    record = dict(values)
    artifact = record.get("artifact")
    if artifact is not None:
        if not isinstance(artifact, Mapping):
            raise TypeError("consolidation PPA artifact must be a mapping")
        projected_artifact = project_fields(
            artifact, allowed_fields=CONSOLIDATION_PPA_ARTIFACT_FIELDS
        ).visible
        if "request_payload" in projected_artifact:
            projected_artifact["request_payload"] = _project_consolidation_ppa_payload(
                projected_artifact["request_payload"],
                allowed_fields=CONSOLIDATION_PPA_REQUEST_PAYLOAD_FIELDS,
                result=False,
            )
        if "result_payload" in projected_artifact:
            projected_artifact["result_payload"] = _project_consolidation_ppa_payload(
                projected_artifact["result_payload"],
                allowed_fields=CONSOLIDATION_PPA_RESULT_PAYLOAD_FIELDS,
                result=True,
            )
        record["artifact"] = projected_artifact
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("consolidation PPA source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=CONSOLIDATION_PPA_RESPONSE_FIELDS)


def _project_consolidation_ownership_change_money(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation ownership-change money must be a mapping")
    return project_fields(value, allowed_fields=CONSOLIDATION_PPA_PAYLOAD_MONEY_FIELDS).visible


def _project_consolidation_ownership_change_payload(
    value: object,
    *,
    result: bool,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("consolidation ownership-change payload must be a mapping")
    allowed_fields = (
        CONSOLIDATION_OWNERSHIP_CHANGE_RESULT_FIELDS
        if result
        else CONSOLIDATION_OWNERSHIP_CHANGE_REQUEST_FIELDS
    )
    payload = project_fields(value, allowed_fields=allowed_fields).visible
    money_fields = (
        ("net_assets", "consideration_effect")
        if not result
        else ()
    )
    for field in money_fields:
        if field in payload:
            payload[field] = _project_consolidation_ownership_change_money(payload[field])
    lines = payload.get("lines")
    if lines is not None:
        if not isinstance(lines, list):
            raise TypeError("consolidation ownership-change lines must be a list")
        projected_lines: list[dict[str, object]] = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise TypeError("consolidation ownership-change line must be a mapping")
            projected_line = project_fields(
                line, allowed_fields=CONSOLIDATION_OWNERSHIP_CHANGE_LINE_FIELDS
            ).visible
            if "amount" in projected_line:
                projected_line["amount"] = _project_consolidation_ownership_change_money(
                    projected_line["amount"]
                )
            projected_lines.append(projected_line)
        payload["lines"] = projected_lines
    return payload


def project_consolidation_ownership_change_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a persisted ownership-change artifact."""

    record = dict(values)
    artifact = record.get("artifact")
    if artifact is not None:
        if not isinstance(artifact, Mapping):
            raise TypeError("consolidation ownership-change artifact must be a mapping")
        projected_artifact = project_fields(
            artifact, allowed_fields=CONSOLIDATION_OWNERSHIP_CHANGE_ARTIFACT_FIELDS
        ).visible
        if "request_payload" in projected_artifact:
            projected_artifact["request_payload"] = _project_consolidation_ownership_change_payload(
                projected_artifact["request_payload"], result=False
            )
        if "result_payload" in projected_artifact:
            projected_artifact["result_payload"] = _project_consolidation_ownership_change_payload(
                projected_artifact["result_payload"], result=True
            )
        record["artifact"] = projected_artifact
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("consolidation ownership-change source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=CONSOLIDATION_OWNERSHIP_CHANGE_RESPONSE_FIELDS)


def _project_consolidation_collection(
    value: object,
    *,
    item_fields: frozenset[str],
    money_fields: frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise TypeError("consolidation artifact collection must be a list")
    projected_items: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("consolidation artifact collection item must be a mapping")
        projected = project_fields(item, allowed_fields=item_fields).visible
        for field in money_fields:
            if field in projected:
                projected[field] = _project_consolidation_ppa_money(projected[field])
        projected_items.append(projected)
    return projected_items


def _project_consolidation_intercompany_payload(
    value: object, *, result: bool
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("intercompany payload must be a mapping")
    payload = project_fields(
        value,
        allowed_fields=(
            CONSOLIDATION_INTERCOMPANY_RESULT_FIELDS
            if result
            else CONSOLIDATION_INTERCOMPANY_REQUEST_FIELDS
        ),
    ).visible
    if not result:
        if "lines" in payload:
            payload["lines"] = _project_consolidation_collection(
                payload["lines"],
                item_fields=CONSOLIDATION_INTERCOMPANY_LINE_FIELDS,
                money_fields=frozenset({"amount"}),
            )
        return payload
    resolutions = payload.get("resolutions")
    if resolutions is not None:
        if not isinstance(resolutions, list):
            raise TypeError("intercompany resolutions must be a list")
        projected_resolutions: list[dict[str, object]] = []
        for resolution in resolutions:
            if not isinstance(resolution, Mapping):
                raise TypeError("intercompany resolution must be a mapping")
            projected = project_fields(
                resolution, allowed_fields=CONSOLIDATION_INTERCOMPANY_RESOLUTION_FIELDS
            ).visible
            proposal = projected.get("proposal")
            if proposal is not None:
                if not isinstance(proposal, Mapping):
                    raise TypeError("intercompany proposal must be a mapping")
                projected_proposal = project_fields(
                    proposal, allowed_fields=CONSOLIDATION_INTERCOMPANY_PROPOSAL_FIELDS
                ).visible
                if "lines" in projected_proposal:
                    projected_proposal["lines"] = _project_consolidation_collection(
                        projected_proposal["lines"],
                        item_fields=CONSOLIDATION_INTERCOMPANY_PROPOSAL_LINE_FIELDS,
                        money_fields=frozenset({"amount"}),
                    )
                projected["proposal"] = projected_proposal
            projected_resolutions.append(projected)
        payload["resolutions"] = projected_resolutions
    return payload


def _project_consolidation_impairment_payload(
    value: object, *, result: bool
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("impairment payload must be a mapping")
    payload = project_fields(
        value,
        allowed_fields=(
            CONSOLIDATION_IMPAIRMENT_RESULT_FIELDS
            if result
            else CONSOLIDATION_IMPAIRMENT_REQUEST_FIELDS
        ),
    ).visible
    money_fields = (
        frozenset({"total_carrying_amount", "total_impairment_loss", "total_recoverable_amount"})
        if result
        else frozenset()
    )
    for field in money_fields:
        if field in payload:
            payload[field] = _project_consolidation_ppa_money(payload[field])
    if "units" in payload:
        payload["units"] = _project_consolidation_collection(
            payload["units"],
            item_fields=(
                CONSOLIDATION_IMPAIRMENT_RESULT_UNIT_FIELDS
                if result
                else CONSOLIDATION_IMPAIRMENT_UNIT_FIELDS
            ),
            money_fields=(
                frozenset({"carrying_amount", "recoverable_amount", "impairment_loss", "recoverable_headroom"})
                if result
                else frozenset({"carrying_amount", "recoverable_amount"})
            ),
        )
    return payload


def _project_consolidation_deferred_tax_payload(
    value: object, *, result: bool
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("deferred-tax payload must be a mapping")
    payload = project_fields(
        value,
        allowed_fields=(
            CONSOLIDATION_DEFERRED_TAX_RESULT_FIELDS
            if result
            else CONSOLIDATION_DEFERRED_TAX_REQUEST_FIELDS
        ),
    ).visible
    money_fields = (
        frozenset({"deferred_tax_asset", "deferred_tax_liability", "net_deferred_tax"})
        if result
        else frozenset()
    )
    for field in money_fields:
        if field in payload:
            payload[field] = _project_consolidation_ppa_money(payload[field])
    if "items" in payload:
        payload["items"] = _project_consolidation_collection(
            payload["items"],
            item_fields=(
                CONSOLIDATION_DEFERRED_TAX_RESULT_ITEM_FIELDS
                if result
                else CONSOLIDATION_DEFERRED_TAX_ITEM_FIELDS
            ),
            money_fields=(
                frozenset({"fair_value", "tax_basis", "tax_amount", "temporary_difference"})
                if result
                else frozenset({"fair_value", "tax_basis"})
            ),
        )
    return payload


def _project_consolidation_artifact_response(
    values: Mapping[str, object],
    *,
    artifact_fields: frozenset[str],
    request_projector: Callable[[object], dict[str, object]],
    result_projector: Callable[[object], dict[str, object]],
    response_fields: frozenset[str],
) -> FieldProjection:
    record = dict(values)
    artifact = record.get("artifact")
    if artifact is not None:
        if not isinstance(artifact, Mapping):
            raise TypeError("consolidation artifact must be a mapping")
        projected_artifact = project_fields(artifact, allowed_fields=artifact_fields).visible
        if "request_payload" in projected_artifact:
            projected_artifact["request_payload"] = request_projector(
                projected_artifact["request_payload"]
            )
        if "result_payload" in projected_artifact:
            projected_artifact["result_payload"] = result_projector(
                projected_artifact["result_payload"]
            )
        record["artifact"] = projected_artifact
    source = record.get("source")
    if source is not None:
        if not isinstance(source, Mapping):
            raise TypeError("consolidation artifact source must be a mapping")
        record["source"] = project_fields(
            source, allowed_fields=MASTER_SNAPSHOT_SOURCE_FIELDS
        ).visible
    return project_fields(record, allowed_fields=response_fields)


def project_consolidation_intercompany_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for an intercompany artifact response."""

    return _project_consolidation_artifact_response(
        values,
        artifact_fields=CONSOLIDATION_INTERCOMPANY_ARTIFACT_FIELDS,
        request_projector=lambda value: _project_consolidation_intercompany_payload(value, result=False),
        result_projector=lambda value: _project_consolidation_intercompany_payload(value, result=True),
        response_fields=CONSOLIDATION_INTERCOMPANY_RESPONSE_FIELDS,
    )


def project_consolidation_impairment_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for an impairment artifact response."""

    return _project_consolidation_artifact_response(
        values,
        artifact_fields=CONSOLIDATION_IMPAIRMENT_ARTIFACT_FIELDS,
        request_projector=lambda value: _project_consolidation_impairment_payload(value, result=False),
        result_projector=lambda value: _project_consolidation_impairment_payload(value, result=True),
        response_fields=CONSOLIDATION_IMPAIRMENT_RESPONSE_FIELDS,
    )


def project_consolidation_deferred_tax_response(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a deferred-tax artifact response."""

    return _project_consolidation_artifact_response(
        values,
        artifact_fields=CONSOLIDATION_DEFERRED_TAX_ARTIFACT_FIELDS,
        request_projector=lambda value: _project_consolidation_deferred_tax_payload(value, result=False),
        result_projector=lambda value: _project_consolidation_deferred_tax_payload(value, result=True),
        response_fields=CONSOLIDATION_DEFERRED_TAX_RESPONSE_FIELDS,
    )
