"""Narrow typed row projection for the existing deferred Intercompany guard.

Only extraction of its consumed text fields changes. The complete original
decision body, parent queries, inverse checks, source closure, INVOKER context
and OLD-before-NEW event order remain unchanged. This is an unaccepted
performance candidate until current-source profiling and native database gates.

Revision 0137 replaces one function with the same signature. Rollback restores
the published 0134 function; neither direction changes retained business rows,
table policies, trigger attachments, permissions or source history.
"""

from __future__ import annotations

import re

from reconforge.infrastructure.postgres_intercompany_operations_schema import UPGRADE_SQL as ORIGINAL_SCHEMA_SQL

# Every consumed key that exists in each installed table is retained, including
# keys unused by that table's current branch. Do not classify an effect by ID.
TABLE_FIELD_PROJECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("intercompany_operation_sources", ("tenant_id", "id")),
    ("intercompany_operation_plans", ("tenant_id", "id")),
    ("intercompany_operation_reviews", ("tenant_id", "plan_id")),
    ("intercompany_operation_links", ("tenant_id", "plan_id", "entry_id")),
    ("intercompany_operation_post_evidence", ("tenant_id", "plan_id")),
    ("intercompany_operation_commands", ("tenant_id", "plan_id")),
    ("finance_entries", ("tenant_id", "id", "entry_number", "reverses_posting_id", "entity_code")),
    ("finance_entry_lines", ("tenant_id", "id", "entry_id")),
    ("finance_entry_line_dimensions", ("tenant_id", "entry_line_id")),
    ("finance_posting_effects", ("tenant_id", "id", "entry_id", "reverses_effect_id")),
    ("domain_audit_events", ("tenant_id", "id", "object_id")),
    ("outbox_events", ("tenant_id", "aggregate_id")),
    ("finance_accounts", ("tenant_id", "id")),
    ("finance_journals", ("tenant_id", "id")),
    ("fiscal_periods", ("tenant_id", "id")),
    ("legal_entities", ("tenant_id", "id", "entity_code")),
)

_FUNCTION_START = "CREATE FUNCTION reconforge.ic_operation_reverse_close()"
_FUNCTION_END = "END $ic$;"
_ORIGINAL_ITERATION = (
    " FOR changed IN SELECT value FROM jsonb_array_elements(CASE TG_OP WHEN 'INSERT' "
    "THEN jsonb_build_array(to_jsonb(NEW)) WHEN 'DELETE' THEN jsonb_build_array(to_jsonb(OLD)) "
    "ELSE jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) END) LOOP"
)


def _original_function() -> str:
    if ORIGINAL_SCHEMA_SQL.count(_FUNCTION_START) != 1:
        raise ValueError("The published Intercompany guard function must be unique.")
    suffix = ORIGINAL_SCHEMA_SQL.split(_FUNCTION_START, 1)[1]
    body, separator, _ = suffix.partition(_FUNCTION_END)
    if not separator or body.count(_ORIGINAL_ITERATION) != 1:
        raise ValueError("The published Intercompany row-extraction contract changed.")
    return _FUNCTION_START + body + separator


def _object(fields: tuple[str, ...], row: str) -> str:
    return "jsonb_build_object(" + ",".join(f"'{field}',{row}.{field}" for field in fields) + ")"


def _projection_sql() -> str:
    groups: dict[tuple[str, ...], list[str]] = {}
    seen: set[str] = set()
    for table, fields in TABLE_FIELD_PROJECTIONS:
        if (table in seen or not re.fullmatch(r"[a-z_]+", table) or not fields
                or len(fields) != len(set(fields))
                or any(not re.fullmatch(r"[a-z_]+", field) for field in fields)):
            raise ValueError("The fixed Intercompany projection population is invalid.")
        seen.add(table)
        groups.setdefault(fields, []).append(table)
    lines = [
        " IF TG_OP IS NULL OR TG_OP NOT IN('INSERT','UPDATE','DELETE') THEN",
        "  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='intercompany_operation_owner',",
        "   MESSAGE='Unsupported Intercompany deferred guard operation';",
        " END IF;",
    ]
    for index, (fields, tables) in enumerate(groups.items()):
        names = ",".join(f"'{table}'" for table in tables)
        new, old = _object(fields, "NEW"), _object(fields, "OLD")
        lines.extend((
            f" {'IF' if index == 0 else 'ELSIF'} TG_TABLE_NAME IN({names}) THEN",
            "  changes:=CASE TG_OP",
            f"   WHEN 'INSERT' THEN jsonb_build_array({new})",
            f"   WHEN 'DELETE' THEN jsonb_build_array({old})",
            f"   WHEN 'UPDATE' THEN jsonb_build_array({old},{new}) END;",
        ))
    lines.extend((
        " ELSE",
        "  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='intercompany_operation_owner',",
        "   MESSAGE='Unsupported Intercompany deferred guard table';",
        " END IF;",
        " FOR changed IN SELECT value FROM jsonb_array_elements(changes) LOOP",
    ))
    return "\n".join(lines)


ORIGINAL_FUNCTION_SQL = _original_function()
DOWNGRADE_SQL = ORIGINAL_FUNCTION_SQL.replace("CREATE FUNCTION ", "CREATE OR REPLACE FUNCTION ", 1)
UPGRADE_SQL = DOWNGRADE_SQL.replace("DECLARE changed JSONB;", "DECLARE changes JSONB;changed JSONB;", 1).replace(
    _ORIGINAL_ITERATION, _projection_sql(), 1,
)
