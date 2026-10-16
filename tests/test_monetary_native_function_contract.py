"""Emitted PL/pgSQL binding checks for native monetary owner callbacks.

PostgreSQL compiles table queries lazily. Installing a trigger therefore does
not exercise the binding of qualified local variables in its first callback.
"""

import re

import pytest

from reconforge.infrastructure.postgres_monetary_customer_returns_schema import NATIVE_FUNCTION_SQL
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import ORIGINAL_FUNCTIONS, UPGRADED_FUNCTIONS
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import _body


def invalid_local_qualifiers(sql: str) -> list[str]:
    definitions = re.finditer(
        r"CREATE FUNCTION reconforge\.([a-z_]+)\([^)]*\).*?AS (\$[a-zA-Z_0-9]*\$)(.*?)\2;",
        sql, re.DOTALL,
    )
    invalid = []
    for definition in definitions:
        name, _, body = definition.groups()
        if "DECLARE" not in body:
            continue
        declarations = body[body.index("DECLARE") + len("DECLARE"):body.index("BEGIN")]
        local_names = re.findall(
            r"(?:^|;)\s*([a-z_]+)\s+(?:RECORD|TEXT|JSONB|INTEGER|BIGINT|NUMERIC|BOOLEAN)\b",
            declarations, re.IGNORECASE,
        )
        for local in local_names:
            if re.search(r"\b" + name + r"\." + local + r"\b", body) and not re.search(
                r"<<\s*" + name + r"\s*>>\s*DECLARE\b", body,
            ):
                invalid.append(name + "." + local)
    return sorted(invalid)


def test_every_emitted_function_qualified_local_binds_an_explicit_declare_block() -> None:
    assert invalid_local_qualifiers(NATIVE_FUNCTION_SQL) == []


@pytest.mark.parametrize("name,expected", [
    ("monetary_stock_close", ["monetary_stock_close.version"]),
    ("monetary_return_native_close", [
        "monetary_return_native_close.entry_id", "monetary_return_native_close.invoice_id",
        "monetary_return_native_close.movement_id",
    ]),
])
def test_missing_explicit_block_is_refused_even_when_implicit_function_label_exists(
    name: str, expected: list[str],
) -> None:
    assert invalid_local_qualifiers(NATIVE_FUNCTION_SQL.replace("<<" + name + ">>", "")) == expected


def _dispatch_aliases(name: str, upgraded: str) -> tuple[set[str], set[str]]:
    """Inspect only the new prefix; the complete historical tail stays exact."""
    _, original_body = _body(ORIGINAL_FUNCTIONS[name])
    _, upgraded_body = _body(upgraded)
    declarations, retained = original_body.split("BEGIN\n", 1)
    upgraded_declarations, extended = upgraded_body.split("BEGIN\n", 1)
    assert upgraded_declarations == declarations and extended.endswith(retained)
    prefix = extended[:-len(retained)]
    locals_ = set(re.findall(r"\b([a-z_][a-z_0-9]*)\s+(?:RECORD|TEXT|JSONB|INTEGER|BIGINT|NUMERIC|BOOLEAN)\b", declarations, re.I))
    aliases = set(re.findall(r"\b(?:FROM|JOIN)\s+reconforge\.[a-z_0-9]+\s+(?:AS\s+)?([a-z_][a-z_0-9]*)\b", prefix, re.I))
    return aliases, aliases & locals_


@pytest.mark.parametrize("name", [
    "customer_partial_return_zero_layer_guard", "customer_partial_return_zero_stock_active", "customer_partial_return_zero_stock_plan",
    "it1_cost_snapshot", "it1_cost_originals", "it1_stock_origins",
])
def test_physical_dispatch_aliases_cannot_shadow_retained_plpgsql_variables(name: str) -> None:
    aliases, conflicts = _dispatch_aliases(name, UPGRADED_FUNCTIONS[name])
    assert conflicts == set()
    assert all(alias.startswith("dispatch_") for alias in aliases)


@pytest.mark.parametrize("retained_record", ["document", "layer"])
def test_retained_record_alias_collision_is_detected_before_native_execution(retained_record: str) -> None:
    poisoned = UPGRADED_FUNCTIONS["it1_cost_snapshot"].replace("dispatch_document", retained_record)
    assert _dispatch_aliases("it1_cost_snapshot", poisoned)[1] == {retained_record}
