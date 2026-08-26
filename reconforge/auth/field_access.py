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
