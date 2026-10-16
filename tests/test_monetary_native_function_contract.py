"""Emitted PL/pgSQL binding checks for native monetary owner callbacks.

PostgreSQL compiles table queries lazily. Installing a trigger therefore does
not exercise the binding of qualified local variables in its first callback.
"""

import re

import pytest

from reconforge.infrastructure.postgres_monetary_customer_returns_schema import NATIVE_FUNCTION_SQL


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
