"""SQLite 50: reserved reviewed Inventory sources and atomic effect-table upgrade.

Historical migration 48 remains unchanged. This extension rebuilds its two closed
source checks in one transaction and keeps all existing Manual/Reversal guards.
The new source's future references are deferred; its content checks are immediate.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator

from reconforge.infrastructure.sqlite_finance_posting_schema import SQLITE_FINANCE_POSTING_MIGRATION_SQL


def _statements(script: str) -> Iterator[str]:
    pending = ""
    for character in script:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            yield pending.strip()
            pending = ""
    if pending.strip():
        raise ValueError("Incomplete reviewed Inventory schema statement.")


_HISTORICAL_STATEMENTS = tuple(_statements(SQLITE_FINANCE_POSTING_MIGRATION_SQL))
_EFFECT_TABLE = next(sql for sql in _HISTORICAL_STATEMENTS if sql.startswith("CREATE TABLE finance_posting_effects"))
_EXTENDED_EFFECT_TABLE = (
    _EFFECT_TABLE.replace(
        "CREATE TABLE finance_posting_effects (", "CREATE TABLE inventory_receipt_effects_upgrade (", 1
    )
    .replace(
        "CHECK(source_kind IN ('Manual','Reversal'))",
        "CHECK(source_kind IN ('Manual','Reversal','InventoryReceipt','InventoryReceiptReversal'))",
        1,
    )
    .replace(
        "CHECK((source_kind='Manual' AND reverses_effect_id IS NULL) OR\n"
        "       (source_kind='Reversal' AND reverses_effect_id IS NOT NULL))",
        "CHECK((source_kind IN ('Manual','InventoryReceipt') AND reverses_effect_id IS NULL) OR\n"
        "       (source_kind IN ('Reversal','InventoryReceiptReversal') AND reverses_effect_id IS NOT NULL))",
        1,
    )
    .replace(
        "REFERENCES finance_posting_effects(id)",
        "REFERENCES inventory_receipt_effects_upgrade(id)",
        1,
    )
)

SCOPE_COLUMNS = ("workspace_id", "organization_id", "legal_entity_id")
ARTIFACT_COLUMNS = (
    "movement_id",
    "movement_line_id",
    "valuation_document_id",
    "input_cost_id",
    "valuation_line_id",
    "cost_layer_id",
    "valuation_reversal_id",
    "reversal_effect_id",
    "finance_entry_id",
    "finance_line_1_id",
    "finance_line_2_id",
    "posting_effect_id",
)
NUMBER_COLUMNS = ("movement_number", "valuation_number", "finance_entry_number")
NULLABLE_ARTIFACTS = frozenset(
    {
        "valuation_document_id",
        "input_cost_id",
        "valuation_line_id",
        "valuation_reversal_id",
        "reversal_effect_id",
    }
)
POLICY_COLUMNS = (
    "currency_code",
    "currency_precision",
    "currency_rounding_policy",
    "currency_registry_version",
    "currency_registry_digest",
)
RECEIPT_TABLES = (
    "inventory_receipt_plans",
    "inventory_receipt_reviews",
    "inventory_receipt_links",
    "inventory_receipt_commands",
)
RECEIPT_BACKUP_COLUMNS = {
    "inventory_receipt_plans": (
        "id",
        *SCOPE_COLUMNS,
        "source_number",
        "operation",
        "plan_version",
        "period_id",
        "posting_date",
        "preparer_actor_id",
        "preparer_username",
        "prepared_at",
        "reason",
        "item_id",
        "uom_id",
        "location_id",
        "quantity_scaled",
        "quantity_precision",
        "total_value_minor",
        *POLICY_COLUMNS,
        "policy_id",
        "mapping_digest",
        "journal_id",
        "inventory_account_id",
        "receipt_clearing_account_id",
        "original_plan_id",
        "original_posting_effect_id",
        *ARTIFACT_COLUMNS,
        *NUMBER_COLUMNS,
        "finance_validation_digest",
        "plan_digest",
        "plan_json",
        "preparation_audit_event_id",
        "preparation_outbox_event_id",
    ),
    "inventory_receipt_reviews": (
        "id",
        *SCOPE_COLUMNS,
        "plan_id",
        "plan_version",
        "plan_digest",
        "finance_validation_digest",
        "reviewer_actor_id",
        "reviewer_username",
        "reviewed_at",
        "reason",
        "review_digest",
        "review_json",
        "audit_event_id",
        "outbox_event_id",
    ),
    "inventory_receipt_links": (
        "id",
        *SCOPE_COLUMNS,
        "plan_id",
        "review_id",
        "plan_digest",
        "review_digest",
        *ARTIFACT_COLUMNS,
        "original_plan_id",
        "original_posting_effect_id",
        "posted_actor_id",
        "posted_at",
        "reason",
        "audit_event_id",
        "outbox_event_id",
    ),
    "inventory_receipt_commands": (
        *SCOPE_COLUMNS,
        "command_id",
        "operation",
        "request_digest",
        "plan_id",
        "actor_user_id",
        "created_at",
        "result_json",
    ),
}

_SCOPE_SQL = """
 workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 organization_id TEXT NOT NULL REFERENCES organizations(id),
 legal_entity_id TEXT NOT NULL REFERENCES legal_entities(id),
"""
_ARTIFACT_SQL = "\n".join(
    f" {name} TEXT{' NOT NULL' if name not in NULLABLE_ARTIFACTS else ''}," for name in ARTIFACT_COLUMNS
)
_NUMBER_SQL = "\n".join(f" {name} TEXT NOT NULL," for name in NUMBER_COLUMNS)
_SHAPE_CHECK = """
 CHECK((valuation_document_id IS NOT NULL AND input_cost_id IS NOT NULL AND valuation_line_id IS NOT NULL
        AND valuation_reversal_id IS NULL AND reversal_effect_id IS NULL AND original_plan_id IS NULL
        AND original_posting_effect_id IS NULL)
    OR (valuation_document_id IS NULL AND input_cost_id IS NULL AND valuation_line_id IS NULL
        AND valuation_reversal_id IS NOT NULL AND reversal_effect_id IS NOT NULL AND original_plan_id IS NOT NULL
        AND original_posting_effect_id IS NOT NULL))
"""

RECEIPT_TABLE_SQL = f"""
CREATE TABLE inventory_receipt_plans (
 id TEXT PRIMARY KEY,
{_SCOPE_SQL}
 source_number TEXT NOT NULL CHECK(length(source_number) BETWEEN 1 AND 80),
 operation TEXT NOT NULL CHECK(operation IN ('Receipt','FullReceiptReversal')),
 plan_version INTEGER NOT NULL CHECK(plan_version=1),
 period_id TEXT NOT NULL REFERENCES periods(id), posting_date TEXT NOT NULL,
 preparer_actor_id TEXT NOT NULL REFERENCES users(id), preparer_username TEXT NOT NULL,
 prepared_at TEXT NOT NULL, reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
 item_id TEXT NOT NULL REFERENCES inventory_items(id), uom_id TEXT NOT NULL REFERENCES units_of_measure(id),
 location_id TEXT NOT NULL REFERENCES inventory_locations(id),
 quantity_scaled INTEGER NOT NULL CHECK(typeof(quantity_scaled)='integer' AND quantity_scaled BETWEEN 1 AND 9000000000000000000),
 quantity_precision INTEGER NOT NULL CHECK(typeof(quantity_precision)='integer' AND quantity_precision BETWEEN 0 AND 6),
 total_value_minor INTEGER NOT NULL CHECK(typeof(total_value_minor)='integer' AND total_value_minor BETWEEN 1 AND 9000000000000000000),
 currency_code TEXT NOT NULL REFERENCES currencies(code),
 currency_precision INTEGER NOT NULL CHECK(typeof(currency_precision)='integer' AND currency_precision BETWEEN 0 AND 8),
 currency_rounding_policy TEXT NOT NULL CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 currency_registry_version TEXT NOT NULL,
 currency_registry_digest TEXT NOT NULL REFERENCES currency_registry_snapshots(registry_digest),
 policy_id TEXT NOT NULL REFERENCES inventory_valuation_policies(id),
 mapping_digest TEXT NOT NULL CHECK(length(mapping_digest)=64 AND mapping_digest NOT GLOB '*[^0-9a-f]*'),
 journal_id TEXT NOT NULL REFERENCES finance_journals(id),
 inventory_account_id TEXT NOT NULL REFERENCES accounts(id),
 receipt_clearing_account_id TEXT NOT NULL REFERENCES accounts(id),
 original_plan_id TEXT REFERENCES inventory_receipt_plans(id),
 original_posting_effect_id TEXT REFERENCES finance_posting_effects(id),
{_ARTIFACT_SQL}
{_NUMBER_SQL}
 finance_validation_digest TEXT NOT NULL CHECK(length(finance_validation_digest)=64 AND finance_validation_digest NOT GLOB '*[^0-9a-f]*'),
 plan_digest TEXT NOT NULL CHECK(length(plan_digest)=64 AND plan_digest NOT GLOB '*[^0-9a-f]*'),
 plan_json TEXT NOT NULL CHECK(json_valid(plan_json) AND length(CAST(plan_json AS BLOB))<=65536),
 preparation_audit_event_id TEXT NOT NULL REFERENCES audit_events(id) DEFERRABLE INITIALLY DEFERRED,
 preparation_outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(id,workspace_id,organization_id,legal_entity_id),
 UNIQUE(workspace_id,organization_id,legal_entity_id,source_number),
 CHECK((operation='Receipt')=(original_plan_id IS NULL)),
{_SHAPE_CHECK}
);
CREATE TABLE inventory_receipt_reviews (
 id TEXT PRIMARY KEY,
{_SCOPE_SQL}
 plan_id TEXT NOT NULL UNIQUE, plan_version INTEGER NOT NULL CHECK(plan_version=1),
 plan_digest TEXT NOT NULL, finance_validation_digest TEXT NOT NULL,
 reviewer_actor_id TEXT NOT NULL REFERENCES users(id), reviewer_username TEXT NOT NULL,
 reviewed_at TEXT NOT NULL, reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
 review_digest TEXT NOT NULL CHECK(length(review_digest)=64 AND review_digest NOT GLOB '*[^0-9a-f]*'),
 review_json TEXT NOT NULL CHECK(json_valid(review_json) AND length(CAST(review_json AS BLOB))<=65536),
 audit_event_id TEXT NOT NULL REFERENCES audit_events(id) DEFERRABLE INITIALLY DEFERRED,
 outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id) DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(id,plan_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_receipt_plans(id,workspace_id,organization_id,legal_entity_id)
);
CREATE TABLE inventory_receipt_links (
 id TEXT PRIMARY KEY CHECK(id=plan_id),
{_SCOPE_SQL}
 plan_id TEXT NOT NULL UNIQUE, review_id TEXT NOT NULL UNIQUE,
 plan_digest TEXT NOT NULL, review_digest TEXT NOT NULL,
{_ARTIFACT_SQL}
 original_plan_id TEXT REFERENCES inventory_receipt_plans(id),
 original_posting_effect_id TEXT REFERENCES finance_posting_effects(id),
 posted_actor_id TEXT NOT NULL REFERENCES users(id), posted_at TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
 audit_event_id TEXT NOT NULL REFERENCES audit_events(id) DEFERRABLE INITIALLY DEFERRED,
 outbox_event_id TEXT NOT NULL REFERENCES outbox_events(id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_receipt_plans(id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(review_id,plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_receipt_reviews(id,plan_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(movement_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_movements(id,workspace_id,organization_id,legal_entity_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(movement_line_id,movement_id)
  REFERENCES inventory_movement_lines(id,movement_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(valuation_document_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_valuation_documents(id,workspace_id,organization_id,legal_entity_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(input_cost_id,valuation_document_id)
  REFERENCES inventory_valuation_input_costs(id,valuation_document_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(valuation_line_id,valuation_document_id)
  REFERENCES inventory_valuation_lines(id,valuation_document_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(cost_layer_id) REFERENCES inventory_cost_layers(id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(valuation_reversal_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_valuation_reversals(id,workspace_id,organization_id,legal_entity_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(reversal_effect_id,valuation_reversal_id)
  REFERENCES inventory_valuation_reversal_effects(id,reversal_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(finance_entry_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES ledger_entries(id,workspace_id,organization_id,legal_entity_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(finance_line_1_id,finance_entry_id) REFERENCES ledger_lines(id,entry_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(finance_line_2_id,finance_entry_id) REFERENCES ledger_lines(id,entry_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(posting_effect_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES finance_posting_effects(id,workspace_id,organization_id,legal_entity_id) DEFERRABLE INITIALLY DEFERRED,
{_SHAPE_CHECK}
);
CREATE TABLE inventory_receipt_commands (
{_SCOPE_SQL}
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
 operation TEXT NOT NULL CHECK(operation IN ('prepare_receipt','prepare_reversal','review','commit')),
 request_digest TEXT NOT NULL CHECK(length(request_digest)=64 AND request_digest NOT GLOB '*[^0-9a-f]*'),
 plan_id TEXT NOT NULL, actor_user_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 result_json TEXT NOT NULL CHECK(json_valid(result_json) AND length(CAST(result_json AS BLOB))<=65536),
 PRIMARY KEY(workspace_id,operation,command_id),
 FOREIGN KEY(plan_id,workspace_id,organization_id,legal_entity_id)
  REFERENCES inventory_receipt_plans(id,workspace_id,organization_id,legal_entity_id)
);
CREATE UNIQUE INDEX inventory_receipt_one_inverse ON inventory_receipt_links(original_plan_id) WHERE original_plan_id IS NOT NULL;
CREATE INDEX inventory_receipt_plan_scope ON inventory_receipt_plans(workspace_id,organization_id,legal_entity_id,prepared_at,id);
"""


_COMPOSITE_KEYS = {
    "inventory_movements": "id,workspace_id,organization_id,legal_entity_id",
    "inventory_movement_lines": "id,movement_id",
    "inventory_valuation_documents": "id,workspace_id,organization_id,legal_entity_id",
    "inventory_valuation_input_costs": "id,valuation_document_id",
    "inventory_valuation_lines": "id,valuation_document_id",
    "inventory_valuation_reversals": "id,workspace_id,organization_id,legal_entity_id",
    "inventory_valuation_reversal_effects": "id,reversal_id",
    "ledger_lines": "id,entry_id",
    "finance_posting_effects": "id,workspace_id,organization_id,legal_entity_id",
}
RECEIPT_INDEX_SQL = (
    "\n".join(
        f"CREATE UNIQUE INDEX {table}_receipt_scope ON {table}({columns});"
        for table, columns in _COMPOSITE_KEYS.items()
    )
    + "\n"
    + "\n".join(
        f"CREATE UNIQUE INDEX {table}_{column} ON {table}({column}) WHERE {column} IS NOT NULL"
        + (" AND operation='Receipt'" if table == "inventory_receipt_plans" and column == "cost_layer_id" else "")
        + ";"
        for table in ("inventory_receipt_plans", "inventory_receipt_links")
        for column in ARTIFACT_COLUMNS
        if column != "cost_layer_id" or table == "inventory_receipt_plans"
    )
)


def _immutable(table: str) -> str:
    return "\n".join(
        f"CREATE TRIGGER {table}_{operation.lower()}_immutable BEFORE {operation} ON {table} "
        "BEGIN SELECT RAISE(ABORT,'reviewed Inventory receipt evidence is immutable'); END;"  # nosec B608
        for operation in ("UPDATE", "DELETE")
    )


RECEIPT_IMMUTABILITY_SQL = "\n".join(_immutable(table) for table in RECEIPT_TABLES)


def _json_equal(left: str, right: str) -> str:
    return (
        f"NOT EXISTS(SELECT fullkey,type,atom FROM json_tree({left}) EXCEPT SELECT fullkey,type,atom FROM json_tree({right})) "
        f"AND NOT EXISTS(SELECT fullkey,type,atom FROM json_tree({right}) EXCEPT SELECT fullkey,type,atom FROM json_tree({left}))"  # nosec B608
    )


def _guard(name: str, table: str, invalid: str, *, event: str = "INSERT") -> str:
    return (
        f"CREATE TRIGGER {name} BEFORE {event} ON {table}\nWHEN {invalid}\n"
        "BEGIN SELECT RAISE(ABORT,'reviewed Inventory receipt backing mismatch'); END;\n"  # nosec B608
    )


def _prefix(value: str) -> str:
    # SQLite upper is ASCII-only; this is exactly the reserved ASCII namespace.
    return f"upper(substr({value},1,5))='IRP1-'"


def _evidence(
    *,
    audit: str,
    outbox: str,
    actor: str,
    object_id: str,
    action: str,
    metadata: str,
    object_type: str = "inventory_receipt_posting",
) -> str:
    payload = f"json_patch({metadata},json_object('audit_event_id',{audit}))"
    return f"""EXISTS(SELECT 1 FROM audit_events a JOIN outbox_events o ON o.id={outbox}
     WHERE a.id={audit} AND a.actor_user_id IS {actor}
      AND a.object_type='{object_type}' AND a.object_id IS {object_id} AND a.action='{action}'
      AND o.aggregate_type='{object_type}' AND o.aggregate_id IS {object_id} AND o.event_type='{action}'
      AND {_json_equal("a.metadata_json", metadata)} AND {_json_equal("o.payload_json", payload)})"""  # nosec B608


_PLAN_BINDINGS = {
    "id": "plan_id",
    "source_number": "source.number",
    "operation": "operation",
    "plan_version": "plan_version",
    "period_id": "source.period_id",
    "posting_date": "source.posting_date",
    "preparer_actor_id": "preparer.user_id",
    "preparer_username": "preparer.username",
    "prepared_at": "prepared_at",
    "reason": "reason",
    **{key: f"scope.{key}" for key in SCOPE_COLUMNS},
    **{
        key: f"source.{key}"
        for key in ("item_id", "uom_id", "location_id", "quantity_scaled", "quantity_precision", "total_value_minor")
    },
    **{key: f"currency_policy.{key}" for key in POLICY_COLUMNS},
    **{
        key: f"mapping.{key}"
        for key in ("policy_id", "journal_id", "inventory_account_id", "receipt_clearing_account_id")
    },
    **{key: f"artifacts.{key}" for key in (*ARTIFACT_COLUMNS, *NUMBER_COLUMNS)},
    **{
        key: key
        for key in (
            "mapping_digest",
            "plan_digest",
            "finance_validation_digest",
            "preparation_audit_event_id",
            "preparation_outbox_event_id",
        )
    },
    "original_plan_id": "original.plan_id",
    "original_posting_effect_id": "original.posting_effect_id",
}
_PLAN_MATCH = " AND ".join(
    f"NEW.{column} IS json_extract(NEW.plan_json,'$.{path}')" for column, path in _PLAN_BINDINGS.items()
)
_PREPARE_METADATA = (
    "json_object('plan_digest',NEW.plan_digest,'finance_validation_digest',NEW.finance_validation_digest)"
)
_REVIEW_METADATA = "json_object('plan_digest',NEW.plan_digest,'review_digest',NEW.review_digest,'finance_validation_digest',NEW.finance_validation_digest)"

RECEIPT_SOURCE_GUARD_SQL = _guard(
    "inventory_receipt_plan_backing",
    "inventory_receipt_plans",
    f"""NOT ({_PLAN_MATCH}) OR json_extract(NEW.plan_json,'$.contract_version') IS NOT 'inventory-receipt-plan-v1'
     OR (SELECT count(*) FROM json_each(NEW.plan_json))<>19
     OR NOT EXISTS(SELECT 1 FROM users u JOIN organizations o ON o.id=NEW.organization_id
       JOIN legal_entities e ON e.id=NEW.legal_entity_id JOIN inventory_items i ON i.id=NEW.item_id
       JOIN inventory_locations l ON l.id=NEW.location_id JOIN warehouses w ON w.id=l.warehouse_id
       WHERE u.id=NEW.preparer_actor_id AND u.username=NEW.preparer_username AND u.disabled=0
        AND o.workspace_id=NEW.workspace_id AND e.organization_id=o.id AND i.workspace_id=o.workspace_id
        AND i.organization_id=o.id AND i.uom_id=NEW.uom_id AND w.workspace_id=o.workspace_id
        AND w.organization_id=o.id AND w.legal_entity_id=e.id
        AND o.organization_code IS json_extract(NEW.plan_json,'$.scope.organization_code')
        AND e.entity_code IS json_extract(NEW.plan_json,'$.scope.entity_code'))
     OR NOT {_evidence(audit="NEW.preparation_audit_event_id", outbox="NEW.preparation_outbox_event_id", actor="NEW.preparer_actor_id", object_id="NEW.id", action="inventory_receipt_prepared", metadata=_PREPARE_METADATA)}""",  # nosec B608
)
_REVIEW_BINDINGS = {
    "id": "review_id",
    "reviewer_actor_id": "reviewer.user_id",
    "reviewer_username": "reviewer.username",
    **{
        key: key
        for key in (
            "plan_id",
            "plan_version",
            "plan_digest",
            "finance_validation_digest",
            "reviewed_at",
            "reason",
            "review_digest",
            "audit_event_id",
            "outbox_event_id",
        )
    },
}
_REVIEW_MATCH = " AND ".join(
    f"NEW.{column} IS json_extract(NEW.review_json,'$.{path}')" for column, path in _REVIEW_BINDINGS.items()
)
RECEIPT_SOURCE_GUARD_SQL += _guard(
    "inventory_receipt_review_backing",
    "inventory_receipt_reviews",
    f"""NOT ({_REVIEW_MATCH}) OR json_extract(NEW.review_json,'$.contract_version') IS NOT 'inventory-receipt-review-v1'
     OR (SELECT count(*) FROM json_each(NEW.review_json))<>12
     OR NOT EXISTS(SELECT 1 FROM inventory_receipt_plans p JOIN users u ON u.id=NEW.reviewer_actor_id
       WHERE p.id=NEW.plan_id AND p.plan_digest=NEW.plan_digest AND p.plan_version=NEW.plan_version
        AND p.finance_validation_digest=NEW.finance_validation_digest AND p.preparer_actor_id<>NEW.reviewer_actor_id
        AND u.username=NEW.reviewer_username AND u.disabled=0)
     OR NOT {_evidence(audit="NEW.audit_event_id", outbox="NEW.outbox_event_id", actor="NEW.reviewer_actor_id", object_id="NEW.plan_id", action="inventory_receipt_reviewed", metadata=_REVIEW_METADATA)}""",  # nosec B608
)
_LINK_MATCH = " AND ".join(
    f"NEW.{key} IS p.{key}"
    for key in (*SCOPE_COLUMNS, *ARTIFACT_COLUMNS, "plan_digest", "original_plan_id", "original_posting_effect_id")
)
RECEIPT_SOURCE_GUARD_SQL += _guard(
    "inventory_receipt_link_backing",
    "inventory_receipt_links",
    f"""NOT EXISTS(SELECT 1 FROM inventory_receipt_plans p JOIN inventory_receipt_reviews r ON r.plan_id=p.id
     JOIN users u ON u.id=NEW.posted_actor_id WHERE p.id=NEW.plan_id AND r.id=NEW.review_id
      AND r.review_digest=NEW.review_digest AND u.disabled=0 AND p.preparer_actor_id<>u.id AND {_LINK_MATCH})""",  # nosec B608
)


def _artifact_guards(table: str, identity: str, fields: dict[str, str], *, parent_columns: tuple[str, ...] = ()) -> str:
    """Lexical reservation applies before any plan exists, including parent IDs."""
    columns = (*RESERVED_COLUMNS[table], *parent_columns)
    selected = " OR ".join(_prefix(f"NEW.{key}") for key in columns)
    previous = " OR ".join(_prefix(f"OLD.{key}") for key in columns)
    predicate = " AND ".join(f"NEW.{key} IS {expression}" for key, expression in fields.items())
    backing = f"""EXISTS(SELECT 1 FROM inventory_receipt_plans p JOIN inventory_receipt_links k ON k.plan_id=p.id
      JOIN inventory_receipt_reviews r ON r.id=k.review_id JOIN users poster ON poster.id=k.posted_actor_id
      WHERE NEW.id=p.{identity} AND {predicate})"""  # nosec B608
    sql = _guard(f"{table}_receipt_insert", table, f"({selected}) AND NOT {backing}")
    sql += _guard(
        f"{table}_receipt_update",
        table,
        f"(({selected}) OR ({previous})) AND (NEW.id IS NOT OLD.id OR NOT {backing})",
        event="UPDATE",
    )
    sql += _guard(f"{table}_receipt_delete", table, f"({previous})", event="DELETE")
    return sql


RESERVED_COLUMNS = {
    "inventory_movements": ("id", "movement_number"),
    "inventory_movement_lines": ("id",),
    "inventory_valuation_documents": ("id", "valuation_number"),
    "inventory_valuation_input_costs": ("id",),
    "inventory_valuation_lines": ("id",),
    "inventory_cost_layers": ("id",),
    "inventory_valuation_reversals": ("id", "reversal_number"),
    "inventory_valuation_reversal_effects": ("id",),
    "ledger_entries": ("id", "entry_number"),
    "ledger_lines": ("id",),
    "finance_posting_effects": ("id",),
}

_SCOPE_FIELDS = {key: f"p.{key}" for key in SCOPE_COLUMNS}
_COMMON_HEADER = {
    **_SCOPE_FIELDS,
    "period_id": "p.period_id",
    "created_by": "p.preparer_username",
    "created_at": "k.posted_at",
    "updated_at": "k.posted_at",
}
_MOVEMENT_FIELDS = {
    **_COMMON_HEADER,
    "movement_number": "p.movement_number",
    "movement_type": "CASE p.operation WHEN 'Receipt' THEN 'Receipt' ELSE 'Delivery' END",
    "movement_date": "p.posting_date",
    "source_reference": "p.id",
    "description": "p.reason",
    "source_type": "'Generated'",
    "status": "CASE WHEN NEW.status='Draft' THEN 'Draft' ELSE 'Posted' END",
    "posted_by": "CASE WHEN NEW.status='Draft' THEN '' ELSE poster.username END",
    "posted_at": "CASE WHEN NEW.status='Draft' THEN NULL ELSE k.posted_at END",
    "post_reason": "CASE WHEN NEW.status='Draft' THEN '' ELSE k.reason END",
    "voided_by": "''",
    "voided_at": "NULL",
    "void_reason": "''",
}
RECEIPT_ARTIFACT_GUARD_SQL = _artifact_guards("inventory_movements", "movement_id", _MOVEMENT_FIELDS)
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_movement_lines",
    "movement_line_id",
    {
        "movement_id": "p.movement_id",
        "line_number": "1",
        "item_id": "p.item_id",
        "uom_id": "p.uom_id",
        "inventory_lot_id": "NULL",
        "from_location_id": "CASE p.operation WHEN 'Receipt' THEN NULL ELSE p.location_id END",
        "to_location_id": "CASE p.operation WHEN 'Receipt' THEN p.location_id ELSE NULL END",
        "quantity_scaled": "p.quantity_scaled",
        "quantity_precision": "p.quantity_precision",
        "description": "p.reason",
        "created_at": "k.posted_at",
    },
    parent_columns=("movement_id",),
)
_APPROVAL_FIELDS = {
    "status": "CASE WHEN NEW.status='Draft' THEN 'Draft' ELSE 'Approved' END",
    "total_value_minor": "CASE WHEN NEW.status='Draft' THEN 0 ELSE p.total_value_minor END",
    "finance_entry_id": "CASE WHEN NEW.status='Draft' THEN NULL ELSE p.finance_entry_id END",
    "approved_by": "CASE WHEN NEW.status='Draft' THEN '' ELSE poster.username END",
    "approved_at": "CASE WHEN NEW.status='Draft' THEN NULL ELSE k.posted_at END",
    "approval_reason": "CASE WHEN NEW.status='Draft' THEN '' ELSE k.reason END",
    "cancelled_by": "''",
    "cancelled_at": "NULL",
    "cancel_reason": "''",
}
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_valuation_documents",
    "valuation_document_id",
    {
        **_COMMON_HEADER,
        **_APPROVAL_FIELDS,
        **{key: f"p.{key}" for key in POLICY_COLUMNS},
        "movement_id": "p.movement_id",
        "policy_id": "p.policy_id",
        "valuation_number": "p.valuation_number",
        "valuation_date": "p.posting_date",
    },
    parent_columns=("movement_id",),
)
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_valuation_input_costs",
    "input_cost_id",
    {
        "valuation_document_id": "p.valuation_document_id",
        "movement_line_id": "p.movement_line_id",
        "total_cost_minor": "p.total_value_minor",
        "created_at": "k.posted_at",
    },
    parent_columns=("valuation_document_id", "movement_line_id"),
)
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_valuation_lines",
    "valuation_line_id",
    {
        "valuation_document_id": "p.valuation_document_id",
        "movement_line_id": "p.movement_line_id",
        "line_number": "1",
        "flow_direction": "'Inbound'",
        "item_id": "p.item_id",
        "uom_id": "p.uom_id",
        "inventory_lot_id": "NULL",
        "quantity_scaled": "p.quantity_scaled",
        "quantity_precision": "p.quantity_precision",
        "value_minor": "p.total_value_minor",
        "inventory_account_id": "p.inventory_account_id",
        "offset_account_id": "p.receipt_clearing_account_id",
        "created_at": "k.posted_at",
    },
    parent_columns=("valuation_document_id", "movement_line_id"),
)
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_cost_layers",
    "cost_layer_id",
    {
        "source_valuation_line_id": "p.valuation_line_id",
        "legal_entity_id": "p.legal_entity_id",
        "item_id": "p.item_id",
        "uom_id": "p.uom_id",
        "inventory_lot_id": "NULL",
        "quantity_precision": "p.quantity_precision",
        "original_quantity_scaled": "p.quantity_scaled",
        "original_value_minor": "p.total_value_minor",
        "currency_code": "p.currency_code",
        "created_at": "k.posted_at",
    },
    parent_columns=("source_valuation_line_id",),
)
RECEIPT_ARTIFACT_GUARD_SQL += _guard(
    "inventory_receipt_layer_initial",
    "inventory_cost_layers",
    f"({_prefix('NEW.id')}) AND (NEW.remaining_quantity_scaled IS NOT NEW.original_quantity_scaled OR NEW.remaining_value_minor IS NOT NEW.original_value_minor)",
)
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_valuation_reversals",
    "valuation_reversal_id",
    {
        **_COMMON_HEADER,
        **_APPROVAL_FIELDS,
        "currency_code": "p.currency_code",
        "original_valuation_document_id": "json_extract(p.plan_json,'$.original.valuation_document_id')",
        "reversal_movement_id": "p.movement_id",
        "reversal_number": "p.valuation_number",
        "reversal_date": "p.posting_date",
    },
    parent_columns=("reversal_movement_id", "original_valuation_document_id"),
)
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards(
    "inventory_valuation_reversal_effects",
    "reversal_effect_id",
    {
        "reversal_id": "p.valuation_reversal_id",
        "original_valuation_line_id": "json_extract(p.plan_json,'$.original.valuation_line_id')",
        "original_consumption_id": "NULL",
        "cost_layer_id": "p.cost_layer_id",
        "effect_type": "'Remove'",
        "quantity_scaled": "p.quantity_scaled",
        "value_minor": "p.total_value_minor",
        "created_at": "k.posted_at",
    },
    parent_columns=("reversal_id",),
)
RECEIPT_ARTIFACT_GUARD_SQL += _guard(
    "inventory_receipt_legacy_remove",
    "inventory_valuation_reversal_effects",
    f"NEW.effect_type='Remove' AND {_prefix('NEW.original_valuation_line_id')} AND NOT EXISTS(SELECT 1 FROM inventory_receipt_links k WHERE k.reversal_effect_id=NEW.id AND k.valuation_reversal_id=NEW.reversal_id)",  # nosec B608
)
_ENTRY_FIELDS = {
    **_COMMON_HEADER,
    **{key: f"p.{key}" for key in POLICY_COLUMNS},
    "chart_id": "(SELECT chart_id FROM finance_journals WHERE id=p.journal_id)",
    "finance_journal_id": "p.journal_id",
    "entry_number": "p.finance_entry_number",
    "posting_date": "p.posting_date",
    "description": "p.reason",
    "external_reference": "p.id",
    "source_type": "'Generated'",
    "preparer_actor_id": "p.preparer_actor_id",
    "reverses_posting_id": "p.original_posting_effect_id",
    "status": "CASE WHEN NEW.status='Draft' THEN 'Draft' ELSE 'Validated' END",
    "validated_by": "CASE WHEN NEW.status='Draft' THEN '' ELSE r.reviewer_username END",
    "validated_at": "CASE WHEN NEW.status='Draft' THEN NULL ELSE r.reviewed_at END",
    "validation_reason": "CASE WHEN NEW.status='Draft' THEN '' ELSE r.reason END",
    "validator_actor_id": "CASE WHEN NEW.status='Draft' THEN NULL ELSE r.reviewer_actor_id END",
    "validation_digest": "CASE WHEN NEW.status='Draft' THEN NULL ELSE p.finance_validation_digest END",
    "validation_contract_version": "CASE WHEN NEW.status='Draft' THEN NULL ELSE 'finance-entry-review-v1' END",
    "voided_by": "''",
    "voided_at": "NULL",
    "void_reason": "''",
}
RECEIPT_ARTIFACT_GUARD_SQL += _artifact_guards("ledger_entries", "finance_entry_id", _ENTRY_FIELDS)
# Both line IDs are independently reserved and checked against the sealed line order.
_LINE_FIELDS = {
    "entry_id": "p.finance_entry_id",
    "description": "p.reason",
    "created_at": "k.posted_at",
    "line_number": "CASE WHEN NEW.id=p.finance_line_1_id THEN 1 ELSE 2 END",
    "account_id": "CASE WHEN NEW.id=p.finance_line_1_id THEN p.inventory_account_id ELSE p.receipt_clearing_account_id END",
    "debit_minor": "CASE WHEN (NEW.id=p.finance_line_1_id)=(p.operation='Receipt') THEN p.total_value_minor ELSE 0 END",
    "credit_minor": "CASE WHEN (NEW.id=p.finance_line_1_id)=(p.operation='Receipt') THEN 0 ELSE p.total_value_minor END",
}
_LINE_SQL = _artifact_guards("ledger_lines", "finance_line_1_id", _LINE_FIELDS, parent_columns=("entry_id",))
RECEIPT_ARTIFACT_GUARD_SQL += _LINE_SQL.replace(
    "NEW.id=p.finance_line_1_id AND", "NEW.id IN (p.finance_line_1_id,p.finance_line_2_id) AND"
)
RECEIPT_ARTIFACT_GUARD_SQL += _guard(
    "inventory_receipt_dimensions_insert",
    "ledger_line_dimensions",
    f"{_prefix('NEW.line_id')}",
)
RECEIPT_ARTIFACT_GUARD_SQL += _guard(
    "inventory_receipt_dimensions_update",
    "ledger_line_dimensions",
    f"{_prefix('NEW.line_id')} OR {_prefix('OLD.line_id')}",
    event="UPDATE",
)
RECEIPT_ARTIFACT_GUARD_SQL += _guard(
    "inventory_receipt_protected_stock",
    "inventory_movements",
    """OLD.status<>NEW.status AND (OLD.status='Posted' OR NEW.status='Posted') AND EXISTS(
     SELECT 1 FROM (
      SELECT item_id,inventory_lot_id,from_location_id AS location_id,-quantity_scaled AS delta
       FROM inventory_movement_lines WHERE movement_id=NEW.id AND from_location_id IS NOT NULL
      UNION ALL
      SELECT item_id,inventory_lot_id,to_location_id AS location_id,quantity_scaled AS delta
       FROM inventory_movement_lines WHERE movement_id=NEW.id AND to_location_id IS NOT NULL
     ) proposed
     WHERE EXISTS(SELECT 1 FROM inventory_receipt_plans p JOIN inventory_receipt_links k ON k.plan_id=p.id
       WHERE p.workspace_id=NEW.workspace_id AND p.organization_id=NEW.organization_id
        AND p.legal_entity_id=NEW.legal_entity_id AND p.item_id=proposed.item_id AND p.location_id=proposed.location_id)
     GROUP BY proposed.item_id,proposed.inventory_lot_id,proposed.location_id
     HAVING COALESCE((SELECT SUM(CASE WHEN l.to_location_id=proposed.location_id THEN l.quantity_scaled ELSE 0 END
                                      -CASE WHEN l.from_location_id=proposed.location_id THEN l.quantity_scaled ELSE 0 END)
        FROM inventory_movement_lines l JOIN inventory_movements m ON m.id=l.movement_id
        WHERE m.id<>NEW.id AND m.status='Posted' AND m.workspace_id=NEW.workspace_id
         AND m.organization_id=NEW.organization_id AND m.legal_entity_id=NEW.legal_entity_id
         AND l.item_id=proposed.item_id AND l.inventory_lot_id IS proposed.inventory_lot_id
         AND (l.from_location_id=proposed.location_id OR l.to_location_id=proposed.location_id)),0)
        +CASE WHEN NEW.status='Posted' THEN SUM(proposed.delta) ELSE 0 END < 0)""",
    event="UPDATE OF status",
)

# Legacy line UPDATE admission checks its old parent. A line moving from a
# Draft into an ordinary Posted header must not bypass the source stock gate.
RECEIPT_ARTIFACT_GUARD_SQL += _guard(
    "inventory_receipt_protected_line_parent",
    "inventory_movement_lines",
    """EXISTS(SELECT 1 FROM inventory_movements m
      JOIN inventory_receipt_plans p ON p.workspace_id=m.workspace_id
       AND p.organization_id=m.organization_id AND p.legal_entity_id=m.legal_entity_id
      JOIN inventory_receipt_links k ON k.plan_id=p.id
      WHERE m.id=NEW.movement_id AND m.status<>'Draft' AND p.item_id=NEW.item_id
       AND (p.location_id=NEW.from_location_id OR p.location_id=NEW.to_location_id))""",
    event="UPDATE",
)

_ENTRY_GUARD = next(
    sql for sql in _HISTORICAL_STATEMENTS if sql.startswith("CREATE TRIGGER finance_posting_effect_entry_guard ")
)
_ENTRY_GUARD = _ENTRY_GUARD.replace(
    "AND ((NEW.source_kind='Manual'",
    "AND ((NEW.source_kind IN ('InventoryReceipt','InventoryReceiptReversal') AND e.source_type='Generated' "
    "AND e.reverses_posting_id IS NEW.reverses_effect_id) OR (NEW.source_kind='Manual'",
    1,
)
_BUNDLE_METADATA = "json_object('plan_digest',p.plan_digest,'review_digest',r.review_digest,'finance_validation_digest',p.finance_validation_digest,'effect_id',p.posting_effect_id)"
_FINANCE_METADATA = "json_object('entry_id',NEW.entry_id,'content_digest',NEW.validation_digest)"
_EFFECT_MATCH = " AND ".join(f"NEW.{key} IS p.{key}" for key in (*SCOPE_COLUMNS, *POLICY_COLUMNS))
_FINAL_SOURCES = """EXISTS(SELECT 1 FROM inventory_movements m WHERE m.id=p.movement_id AND m.status='Posted')
 AND ((p.operation='Receipt' AND EXISTS(SELECT 1 FROM inventory_valuation_documents v
  JOIN inventory_valuation_lines l ON l.valuation_document_id=v.id JOIN inventory_cost_layers c ON c.source_valuation_line_id=l.id
  JOIN inventory_valuation_input_costs input ON input.valuation_document_id=v.id
  WHERE v.id=p.valuation_document_id AND v.status='Approved' AND v.finance_entry_id=p.finance_entry_id
   AND v.total_value_minor=p.total_value_minor AND l.id=p.valuation_line_id AND c.id=p.cost_layer_id
   AND input.id=p.input_cost_id AND c.remaining_quantity_scaled=p.quantity_scaled AND c.remaining_value_minor=p.total_value_minor))
 OR (p.operation='FullReceiptReversal' AND EXISTS(SELECT 1 FROM inventory_valuation_reversals v
  JOIN inventory_valuation_reversal_effects inverse ON inverse.reversal_id=v.id
  JOIN inventory_cost_layers c ON c.id=inverse.cost_layer_id
  WHERE v.id=p.valuation_reversal_id AND v.status='Approved' AND v.finance_entry_id=p.finance_entry_id
   AND v.total_value_minor=p.total_value_minor AND inverse.id=p.reversal_effect_id
   AND c.id=p.cost_layer_id AND c.remaining_quantity_scaled=0 AND c.remaining_value_minor=0)))"""
_EFFECT_BACKING = f"""EXISTS(SELECT 1 FROM inventory_receipt_plans p
 JOIN inventory_receipt_reviews r ON r.plan_id=p.id JOIN inventory_receipt_links k ON k.plan_id=p.id AND k.review_id=r.id
 JOIN ledger_entries e ON e.id=p.finance_entry_id
 WHERE NEW.id=p.posting_effect_id AND NEW.source_id=p.id AND NEW.entry_id=p.finance_entry_id
  AND NEW.source_kind=CASE p.operation WHEN 'Receipt' THEN 'InventoryReceipt' ELSE 'InventoryReceiptReversal' END
  AND NEW.reverses_effect_id IS p.original_posting_effect_id AND NEW.posted_actor_id=k.posted_actor_id
  AND NEW.posted_at=k.posted_at AND NEW.reason=k.reason AND NEW.validation_digest=p.finance_validation_digest
  AND e.validator_actor_id=r.reviewer_actor_id AND e.validation_digest=r.finance_validation_digest
  AND {_EFFECT_MATCH} AND {_json_equal("NEW.snapshot_json", "json_extract(p.plan_json,'$.finance_snapshot')")}
  AND {_FINAL_SOURCES}
  AND {_evidence(audit="k.audit_event_id", outbox="k.outbox_event_id", actor="k.posted_actor_id", object_id="p.id", action="inventory_receipt_committed", metadata=_BUNDLE_METADATA)}
  AND {_evidence(audit="NEW.audit_event_id", outbox="NEW.outbox_event_id", actor="NEW.posted_actor_id", object_id="NEW.id", action="finance_entry_posted", metadata=_FINANCE_METADATA, object_type="finance_posting")})"""  # nosec B608
RECEIPT_EFFECT_GUARD_SQL = "DROP TRIGGER finance_posting_effect_entry_guard;\n" + _ENTRY_GUARD + "\n"
RECEIPT_EFFECT_GUARD_SQL += _guard(
    "inventory_receipt_finance_effect_backing",
    "finance_posting_effects",
    f"(NEW.source_kind IN ('InventoryReceipt','InventoryReceiptReversal') OR {_prefix('NEW.id')} OR {_prefix('NEW.entry_id')}) AND NOT {_EFFECT_BACKING}",
)
RECEIPT_EFFECT_GUARD_SQL += _guard(
    "inventory_receipt_generic_reversal_deny",
    "finance_posting_effects",
    "NEW.source_kind='Reversal' AND EXISTS(SELECT 1 FROM finance_posting_effects original "
    "WHERE original.id=NEW.reverses_effect_id AND original.source_kind IN ('InventoryReceipt','InventoryReceiptReversal'))",
)
RECEIPT_EFFECT_GUARD_SQL += _guard(
    "inventory_receipt_generic_command_deny",
    "finance_posting_commands",
    "EXISTS(SELECT 1 FROM inventory_receipt_links k WHERE k.posting_effect_id=json_extract(NEW.result_json,'$.id') "
    "OR k.posting_effect_id=json_extract(NEW.result_json,'$.reverses_posting_id') "
    "OR k.finance_entry_id=json_extract(NEW.result_json,'$.entry_id'))",
)

_COMMAND_PREPARE = _json_equal("NEW.result_json", "p.plan_json")
_COMMAND_REVIEW = _json_equal("NEW.result_json", "r.review_json")
# Commit envelopes are independently verified by the adapter before insertion;
# SQL also binds every public reference and the complete nested Finance receipt.
_COMMAND_COMMIT = " AND ".join(
    f"json_extract(NEW.result_json,'$.{key}') IS {value}"
    for key, value in {
        "plan_id": "p.id",
        "plan_digest": "p.plan_digest",
        "review_id": "r.id",
        "review_digest": "r.review_digest",
        "effect_id": "k.posting_effect_id",
        "entry_id": "k.finance_entry_id",
        "posted_actor_id": "k.posted_actor_id",
        "posted_at": "k.posted_at",
        "audit_event_id": "k.audit_event_id",
        "outbox_event_id": "k.outbox_event_id",
        "movement_id": "p.movement_id",
        "valuation_document_id": "p.valuation_document_id",
        "valuation_reversal_id": "p.valuation_reversal_id",
        "cost_layer_id": "p.cost_layer_id",
        "reverses_effect_id": "p.original_posting_effect_id",
        "source_id": "p.id",
        "operation": "p.operation",
        "purpose": "'operational_posting'",
        "contract_version": "'inventory-receipt-effect-v1'",
        "source_kind": "CASE p.operation WHEN 'Receipt' THEN 'InventoryReceipt' ELSE 'InventoryReceiptReversal' END",
    }.items()
)
RECEIPT_COMMAND_GUARD_SQL = _guard(
    "inventory_receipt_command_backing",
    "inventory_receipt_commands",
    f"""NOT EXISTS(SELECT 1 FROM inventory_receipt_plans p
      LEFT JOIN inventory_receipt_reviews r ON r.plan_id=p.id LEFT JOIN inventory_receipt_links k ON k.plan_id=p.id
      LEFT JOIN finance_posting_effect_receipts f ON f.id=k.posting_effect_id
      WHERE p.id=NEW.plan_id AND ((NEW.operation='prepare_receipt' AND p.operation='Receipt' AND NEW.actor_user_id=p.preparer_actor_id AND {_COMMAND_PREPARE})
       OR (NEW.operation='prepare_reversal' AND p.operation='FullReceiptReversal' AND NEW.actor_user_id=p.preparer_actor_id AND {_COMMAND_PREPARE})
       OR (NEW.operation='review' AND NEW.actor_user_id=r.reviewer_actor_id AND {_COMMAND_REVIEW})
       OR (NEW.operation='commit' AND NEW.actor_user_id=k.posted_actor_id AND {_COMMAND_COMMIT}
        AND (SELECT count(*) FROM json_each(NEW.result_json))=22
        AND {_json_equal("json_extract(NEW.result_json,'$.finance_effect')", "f.result_json")})))""",  # nosec B608
)

SQLITE_INVENTORY_RECEIPT_MIGRATION_SQL = (
    RECEIPT_TABLE_SQL
    + RECEIPT_INDEX_SQL
    + RECEIPT_IMMUTABILITY_SQL
    + RECEIPT_SOURCE_GUARD_SQL
    + RECEIPT_ARTIFACT_GUARD_SQL
    + RECEIPT_EFFECT_GUARD_SQL
    + RECEIPT_COMMAND_GUARD_SQL
)

RECEIPT_RESTORE_ADMISSION_TRIGGERS = tuple(
    re.match(r"CREATE TRIGGER (\w+)", statement)[1]  # type: ignore[index]
    for statement in _statements(
        RECEIPT_SOURCE_GUARD_SQL + RECEIPT_ARTIFACT_GUARD_SQL + RECEIPT_EFFECT_GUARD_SQL + RECEIPT_COMMAND_GUARD_SQL
    )
    if statement.startswith("CREATE TRIGGER ")
)


def preflight_receipt_namespace(connection: sqlite3.Connection) -> None:
    """Refuse preexisting reserved identities; never silently adopt old output."""
    for table, columns in RESERVED_COLUMNS.items():
        predicate = " OR ".join(_prefix(column) for column in columns)
        if connection.execute(f"SELECT 1 FROM {table} WHERE {predicate} LIMIT 1").fetchone() is not None:  # nosec B608
            raise sqlite3.IntegrityError("Existing IRP1 namespace collision prevents the atomic Inventory migration.")


def _schema_name(statement: str) -> str:
    match = re.match(r"CREATE (?:UNIQUE )?(?:TRIGGER|VIEW|INDEX) (\w+)", statement)
    if match is None:
        raise ValueError("Unsupported historical dependent schema statement.")
    return match[1]


_DEPENDENTS = {
    _schema_name(sql): sql
    for sql in _HISTORICAL_STATEMENTS
    if re.match(r"CREATE (?:UNIQUE )?(?:TRIGGER|VIEW|INDEX) ", sql) and "finance_posting_effects" in sql
}


def atomic_receipt_upgrade(
    connection: sqlite3.Connection,
    *,
    schema_sql: str,
    version: int,
    name: str,
    applied_at: str,
    checkpoint: Callable[[str], None] | None = None,
) -> None:
    """Rebuild without implicit commits; every DDL/data/version change rolls back."""
    if connection.in_transaction:
        raise sqlite3.IntegrityError("Inventory migration requires a clean connection.")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise sqlite3.IntegrityError("Inventory migration requires foreign_keys=ON.")
    from reconforge.infrastructure.sqlite_finance_posting import verify_posting_storage

    verify_posting_storage(connection)
    preflight_receipt_namespace(connection)
    dependent_rows = connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE type IN ('trigger','view','index') "
        "AND sql LIKE '%finance_posting_effects%'"
    ).fetchall()
    actual = {row["name"]: row for row in dependent_rows}
    if set(actual) != set(_DEPENDENTS) or any(
        " ".join(actual[key]["sql"].split()).rstrip(";") != " ".join(value.split()).rstrip(";")
        for key, value in _DEPENDENTS.items()
    ):
        raise sqlite3.IntegrityError("Unexpected Finance posting schema; migration refused without alteration.")
    existing = connection.execute("SELECT * FROM finance_posting_effects ORDER BY id").fetchall()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Repeat absence checks after acquiring the actual SQLite writer lock.
        # An old writer may have committed between initial preflight and BEGIN.
        preflight_receipt_namespace(connection)
        locked_dependents = connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('trigger','view','index') "
            "AND sql LIKE '%finance_posting_effects%'"
        ).fetchall()
        if {tuple(row) for row in locked_dependents} != {tuple(row) for row in dependent_rows}:
            raise sqlite3.IntegrityError("Finance schema changed before Inventory migration acquired its lock.")
        # Execute complete individual statements, never executescript after BEGIN.
        for row in dependent_rows:
            connection.execute(f"DROP {row['type'].upper()} {row['name']}")  # nosec B608
        connection.execute(_EXTENDED_EFFECT_TABLE)
        connection.execute("INSERT INTO inventory_receipt_effects_upgrade SELECT * FROM finance_posting_effects")
        if checkpoint is not None:
            checkpoint("copied")
        connection.execute("DROP TABLE finance_posting_effects")
        if checkpoint is not None:
            checkpoint("dropped")
        connection.execute("ALTER TABLE inventory_receipt_effects_upgrade RENAME TO finance_posting_effects")
        if checkpoint is not None:
            checkpoint("renamed")
        for statement in _DEPENDENTS.values():
            connection.execute(statement)
        for statement in _statements(schema_sql):
            connection.execute(statement)
        if checkpoint is not None:
            checkpoint("guards")
        if [tuple(row) for row in connection.execute("SELECT * FROM finance_posting_effects ORDER BY id")] != [
            tuple(row) for row in existing
        ]:
            raise sqlite3.IntegrityError("Historical Finance posting data changed during rebuild.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("Inventory migration would leave invalid foreign keys.")
        verify_posting_storage(connection)
        if checkpoint is not None:
            checkpoint("verified")
        connection.execute(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
            (version, name, applied_at),
        )
        connection.execute(f"PRAGMA user_version={int(version)}")
        if checkpoint is not None:
            checkpoint("marked")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise sqlite3.IntegrityError("Inventory migration could not restore foreign key enforcement.")
