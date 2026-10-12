"""Source-derived coverage and OLD/NEW parity without claiming native SQL execution."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from reconforge.infrastructure import postgres_intercompany_guard_projection as candidate
from reconforge.infrastructure.postgres_intercompany_operations_schema import UPGRADE_SQL as ORIGINAL_SCHEMA_SQL

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SOURCES = (
    "postgres_intercompany_operations_schema.py", "postgres_finance_core.py", "postgres_finance_posting_schema.py",
    "postgres_domain.py", "postgres_ledger.py", "postgres_master_data.py", "postgres_master_data_application.py",
    "postgres_outbox.py", "outbox_fencing_schema.py",
)
_CONSUMED = set(re.findall(r"changed->>'([a-z_]+)'", candidate.ORIGINAL_FUNCTION_SQL))


def _balanced(source: str, start: int) -> str:
    """Read a CREATE TABLE body, respecting nested checks and quoted literals."""
    depth, quoted, index = 1, False, start
    while index < len(source):
        char = source[index]
        if char == "'":
            if quoted and index + 1 < len(source) and source[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            depth += (char == "(") - (char == ")")
            if depth == 0:
                return source[start:index]
        index += 1
    raise AssertionError("Unterminated native table definition")


def _columns(table: str) -> set[str]:
    columns: set[str] = set()
    definitions = 0
    for filename in SCHEMA_SOURCES:
        source = (ROOT / "reconforge/infrastructure" / filename).read_text(encoding="utf-8")
        pattern = rf"CREATE TABLE(?: IF NOT EXISTS)? reconforge\.{table}\s*\("
        for match in re.finditer(pattern, source):
            definitions += 1
            body = _balanced(source, match.end())
            columns.update(re.findall(
                r"(?:^|,)\s*([a-z_][a-z_0-9]*)\s+(?:TEXT|BIGINT|INTEGER|SMALLINT|JSONB|BOOLEAN|DATE|TIMESTAMPTZ)\b",
                body,
            ))
        columns.update(re.findall(
            rf"ALTER TABLE reconforge\.{table} ADD COLUMN(?: IF NOT EXISTS)? ([a-z_][a-z_0-9]*)\b", source,
        ))
    assert definitions == 1, f"Native CREATE TABLE population changed for {table}"
    return columns


def _installed_tables() -> set[str]:
    statement = ORIGINAL_SCHEMA_SQL.split(
        "EXECUTE format('CREATE CONSTRAINT TRIGGER intercompany_operation_owner_closure", 1,
    )[0]
    names = statement.rsplit("FOREACH n IN ARRAY ARRAY[", 1)[1].split("] LOOP", 1)[0]
    return set(re.findall(r"'([a-z_]+)'", names))


def _emitted_cases(sql: str) -> dict[str, dict[str, list[tuple[str, list[tuple[str, str]]]]]]:
    """Inspect actual generated selectors, independently of its Python registry."""
    cases = {}
    pattern = r"(?:IF|ELSIF) TG_TABLE_NAME IN\(([^)]+)\) THEN\s+changes:=CASE TG_OP(.*?) END;"
    for names, body in re.findall(pattern, sql, flags=re.DOTALL):
        events = {}
        for operation, content in re.findall(r"WHEN '(INSERT|DELETE|UPDATE)' THEN(.*?)(?=\n|$)", body):
            rows = []
            for arguments in re.findall(r"jsonb_build_object\(([^()]*)\)", content):
                pairs = re.findall(r"'([a-z_]+)',(OLD|NEW)\.([a-z_]+)", arguments)
                assert pairs and all(key == column for key, _, column in pairs)
                assert len({row for _, row, _ in pairs}) == 1
                assert ",".join(f"'{key}',{row}.{column}" for key, row, column in pairs) == arguments
                rows.append((pairs[0][1], [(key, column) for key, _, column in pairs]))
            events[operation] = rows
        assert set(events) == {"INSERT", "DELETE", "UPDATE"}
        for table in re.findall(r"'([a-z_]+)'", names):
            assert table not in cases
            cases[table] = events
    return cases


def _project(table: str, operation: str, old: dict, new: dict) -> list[dict]:
    rows = {"OLD": old, "NEW": new}
    return [
        {key: rows[selector][column] for key, column in fields}
        for selector, fields in _emitted_cases(candidate.UPGRADE_SQL)[table][operation]
    ]


def test_projection_is_total_over_exact_original_installed_tables_and_consumed_columns() -> None:
    tables = _installed_tables()
    assert len(tables) == 16
    actual = _emitted_cases(candidate.UPGRADE_SQL)
    assert set(actual) == tables == {table for table, _ in candidate.TABLE_FIELD_PROJECTIONS}
    assert {
        "tenant_id", "id", "entry_id", "entry_line_id", "reverses_posting_id", "reverses_effect_id",
        "entry_number", "entity_code", "plan_id", "object_id", "aggregate_id",
    } == _CONSUMED
    for table, fields in candidate.TABLE_FIELD_PROJECTIONS:
        assert set(fields) == _columns(table) & _CONSUMED
        for rows in actual[table].values():
            for _, selectors in rows:
                assert [column for _, column in selectors] == list(fields)


@pytest.mark.parametrize("table", sorted(_installed_tables()))
@pytest.mark.parametrize("operation,selectors", [("INSERT", ["NEW"]), ("DELETE", ["OLD"]), ("UPDATE", ["OLD", "NEW"])])
def test_actual_generated_projection_preserves_every_consumed_field_and_event_order(table, operation, selectors) -> None:
    columns = _columns(table)
    old = {field: "old:" + field for field in columns}
    new = {field: "new:" + field for field in columns}
    projected = _project(table, operation, old, new)
    assert len(projected) == len(selectors)
    for result, selector in zip(projected, selectors, strict=True):
        full = old if selector == "OLD" else new
        assert {key: result.get(key) for key in _CONSUMED} == {key: full.get(key) for key in _CONSUMED}
        assert "payload" not in result and "snapshot_json" not in result and "metadata_json" not in result


@pytest.mark.parametrize("value", [None, "", "IC1-CASE", "BENCH-CASE", "ME1-CASE", "IRP1-GLE-CASE", "عكس أصل"])
@pytest.mark.parametrize("operation", ["INSERT", "DELETE", "UPDATE"])
def test_null_empty_foreign_namespace_and_original_inverse_values_are_not_classified_away(value, operation) -> None:
    for table in _installed_tables():
        full = dict.fromkeys(_columns(table), value)
        for result in _project(table, operation, full, full):
            # PostgreSQL ->> returns NULL for an absent key and a JSON NULL;
            # an empty string remains distinct. No namespace skips are added.
            assert {key: result.get(key) for key in _CONSUMED} == {key: full.get(key) for key in _CONSUMED}


def test_full_large_payloads_are_not_serialized_or_accessed_by_generated_projection() -> None:
    class OpaquePayload:
        def __str__(self):
            raise AssertionError("A financial payload must not be serialized by dispatch")

    for table in _installed_tables():
        row = {field: "synthetic:" + field for field in _columns(table)}
        row.update(payload=OpaquePayload(), snapshot_json=OpaquePayload(), metadata_json=OpaquePayload())
        with pytest.raises(TypeError):
            json.dumps(row)
        for projected in _project(table, "UPDATE", row, row):
            assert all(value is not row["payload"] for value in projected.values())
            assert set(projected) <= _CONSUMED
    assert "to_jsonb(NEW)" not in candidate.UPGRADE_SQL and "to_jsonb(OLD)" not in candidate.UPGRADE_SQL


def test_complete_original_decision_body_parent_inverse_old_and_closure_obligations_are_exact() -> None:
    marker = "  selected:=changed->>'tenant_id';entry:=NULL;original:=NULL;"
    assert candidate.UPGRADE_SQL.split(marker, 1)[1] == candidate.ORIGINAL_FUNCTION_SQL.split(marker, 1)[1]
    assert candidate.UPGRADE_SQL.count(marker) == 1
    assert "SELECT entry_number INTO number FROM reconforge.finance_entries" in candidate.UPGRADE_SQL
    assert "upper(left(coalesce(changed->>'entry_number',''),4))='IC1-'" in candidate.UPGRADE_SQL
    assert "f.id=original AND upper(left(e.entry_number,4))='IC1-'" in candidate.UPGRADE_SQL
    assert "IF entry IS NULL THEN CONTINUE;END IF;" in candidate.UPGRADE_SQL


def test_same_function_signature_invoker_search_path_and_exact_original_rollback() -> None:
    expected = candidate.ORIGINAL_FUNCTION_SQL.replace("CREATE FUNCTION ", "CREATE OR REPLACE FUNCTION ", 1)
    assert expected == candidate.DOWNGRADE_SQL
    header = "CREATE OR REPLACE FUNCTION reconforge.ic_operation_reverse_close() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $ic$"
    assert candidate.UPGRADE_SQL.startswith(header) and candidate.DOWNGRADE_SQL.startswith(header)
    for sql in (candidate.UPGRADE_SQL, candidate.DOWNGRADE_SQL):
        assert "DROP FUNCTION" not in sql and "CREATE TRIGGER" not in sql and "DROP TRIGGER" not in sql
        assert "GRANT " not in sql and "REVOKE " not in sql and "ALTER TABLE" not in sql
        assert "SECURITY DEFINER" not in sql and "row_security=off" not in sql
        assert "INSERT INTO" not in sql and "UPDATE reconforge" not in sql and "DELETE FROM" not in sql


def test_unknown_table_and_operation_are_fail_closed_before_projection() -> None:
    start = candidate.UPGRADE_SQL.index(" IF TG_OP IS NULL OR TG_OP NOT IN('INSERT','UPDATE','DELETE') THEN")
    projection = candidate.UPGRADE_SQL.index(" changes:=CASE TG_OP")
    loop = candidate.UPGRADE_SQL.index(" FOR changed IN SELECT value FROM jsonb_array_elements(changes) LOOP")
    assert start < projection < loop
    assert "MESSAGE='Unsupported Intercompany deferred guard operation'" in candidate.UPGRADE_SQL[start:projection]
    assert "MESSAGE='Unsupported Intercompany deferred guard table'" in candidate.UPGRADE_SQL[projection:loop]
    assert "ERRCODE='23514',CONSTRAINT='intercompany_operation_owner'" in candidate.UPGRADE_SQL[start:loop]


@pytest.mark.parametrize("mutation", ["missing_table", "duplicate_table", "unsafe_table", "duplicate_field", "unsafe_field"])
def test_fixed_projection_population_mutations_are_refused_or_fail_totality(mutation, monkeypatch) -> None:
    rows = list(candidate.TABLE_FIELD_PROJECTIONS)
    if mutation == "missing_table":
        rows.pop()
    elif mutation == "duplicate_table":
        rows.append(rows[0])
    elif mutation == "unsafe_table":
        rows[0] = ("foreign');DROP TABLE unrelated;--", rows[0][1])
    elif mutation == "duplicate_field":
        rows[0] = (rows[0][0], (*rows[0][1], "tenant_id"))
    else:
        rows[0] = (rows[0][0], (*rows[0][1], "tenant_id;SELECT"))
    monkeypatch.setattr(candidate, "TABLE_FIELD_PROJECTIONS", tuple(rows))
    if mutation == "missing_table":
        assert set(_emitted_cases(candidate._projection_sql())) != _installed_tables()
    else:
        with pytest.raises(ValueError, match="population is invalid"):
            candidate._projection_sql()


def test_migration_is_additive_exact_parent_and_executes_only_the_replacement_function() -> None:
    path = ROOT / "alembic/versions/0137_postgres_intercompany_guard_projection.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
    assert assignments == {"revision": "0137_pg_intercompany_projection", "down_revision": "0136_pg_inventory_scope",
                           "branch_labels": None, "depends_on": None}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == ["upgrade", "downgrade"]
    for function, sql_name in zip(functions, ("UPGRADE_SQL", "DOWNGRADE_SQL"), strict=True):
        assert len(function.body) == 1
        assert ast.unparse(function.body[0]) == f"op.execute(sa.text({sql_name}))"
