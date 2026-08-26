"""Deterministic field authorization and masking primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

REDACTED_VALUE = "[REDACTED]"

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
CLOSE_PERIOD_FIELDS = frozenset(
    {
        "tenant_id",
        "id",
        "workspace_id",
        "fiscal_period_id",
        "period_name",
        "organization_id",
        "organization_code",
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


def project_audit_event(values: Mapping[str, object]) -> FieldProjection:
    """Return the redacted, fail-closed projection for a legacy audit event."""

    return project_fields(
        values,
        allowed_fields=AUDIT_EVENT_FIELDS,
        masked_fields=AUDIT_EVENT_SENSITIVE_FIELDS,
    )


def project_evidence_requirement(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a governed evidence requirement response."""

    return project_fields(values, allowed_fields=EVIDENCE_REQUIREMENT_FIELDS)


def project_evidence_verification(values: Mapping[str, object]) -> FieldProjection:
    """Return a closed projection for a checksum verification response."""

    return project_fields(values, allowed_fields=EVIDENCE_VERIFICATION_FIELDS)


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
