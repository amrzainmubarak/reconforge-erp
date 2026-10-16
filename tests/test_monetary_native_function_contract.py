"""Emitted PL/pgSQL binding checks for native monetary owner callbacks.

PostgreSQL compiles table queries lazily. Installing a trigger therefore does
not exercise the binding of qualified local variables in its first callback.
"""

import hashlib
import re

import pytest

from reconforge.infrastructure.postgres_monetary_customer_returns_schema import NATIVE_FUNCTION_SQL
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import (
    _ZERO_FIFO_QUANTITY,
    DOWNGRADE_SQL,
    ORIGINAL_FUNCTIONS,
    UPGRADED_FUNCTIONS,
    preflight,
)
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


def test_zero_fifo_extension_preserves_the_complete_original_units_positive_sum_and_claim_law() -> None:
    original = ORIGINAL_FUNCTIONS["inventory_quantity_free_fifo"]
    assert hashlib.sha256(_body(original)[1].encode()).hexdigest() == "815bcf89c963b301a198b496504621bbac3b113fa4e60a653727897796e8691f"
    upgraded = UPGRADED_FUNCTIONS["inventory_quantity_free_fifo"]
    declarations, extended = _body(upgraded)[1].split("BEGIN\n", 1)
    assert declarations.startswith("\nDECLARE remaining NUMERIC;claimed NUMERIC;native RECORD;")
    restored = declarations[:declarations.index("zero_candidate RECORD;")] + "\nBEGIN\n" + extended.replace(_ZERO_FIFO_QUANTITY, "", 1)
    assert restored == _body(original)[1]
    assert "remaining_quantity_scaled')::numeric<=restitution_quantity" not in upgraded


def test_zero_fifo_source_proof_is_conditional_and_precedes_the_unchanged_global_claim_deduction() -> None:
    body = _body(UPGRADED_FUNCTIONS["inventory_quantity_free_fifo"])[1]
    loop = body.index(" FOR zero_candidate IN")
    new_tables = body.index("FROM reconforge.customer_partial_return_monetary_restorations")
    ordinary_exclusion = body.index("IF restitution_quantity<=0 THEN CONTINUE;END IF;")
    snapshot = body.index("quantity_cost:=reconforge.it1_cost_snapshot(")
    originals = body.index("PERFORM reconforge.it1_cost_originals(t,quantity_cost)")
    current_layer = body.index("quantity_members=1 AND quantity_source->'layer'=zero_candidate.layer_json")
    signed = body.index("PERFORM reconforge.it1_assert(restitution_quantity>0,")
    add = body.index("remaining:=remaining+(zero_candidate.layer_json->>'remaining_quantity_scaled')::numeric;")
    claimed = body.index(" SELECT COALESCE(sum(g.quantity_scaled),0) INTO claimed")
    assert loop < new_tables < ordinary_exclusion < snapshot < originals < current_layer < signed < add < claimed
    assert "dispatch_layer.remaining_quantity_scaled>0 AND dispatch_layer.remaining_value_minor=0" in body[loop:new_tables]
    assert body.count("quantity_cost:=reconforge.it1_cost_snapshot(") == 1
    assert body.count("remaining:=remaining+") == 1
    assert body.count("RETURN remaining-claimed;") == 1
    # The original positive-only prefix performs no private restitution reads.
    assert "customer_partial_return_" not in body[:loop]
    assert "set_config" not in body and "EXCEPTION WHEN" not in body and "has_table_privilege" not in body


def test_quantity_function_is_the_only_additional_retained_profile_and_restores_exact_body() -> None:
    assert len(ORIGINAL_FUNCTIONS) == len(UPGRADED_FUNCTIONS) == 10
    original = ORIGINAL_FUNCTIONS["inventory_quantity_free_fifo"]
    upgraded = UPGRADED_FUNCTIONS["inventory_quantity_free_fifo"]
    header = original.split("AS $quantity$", 1)[0]
    assert upgraded.split("AS $quantity$", 1)[0] == header.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    assert "LANGUAGE plpgsql STABLE SET search_path=pg_catalog" in header
    assert original.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) in DOWNGRADE_SQL
    for definition, is_upgraded in ((original, False), (upgraded, True)):
        assertion = preflight(upgraded=is_upgraded)
        assert assertion.count("Retained physical execution contract drift") == 10
        assert "inventory_quantity_free_fifo(text,text,text,text)" in assertion
        assert hashlib.sha256(_body(definition)[1].encode()).hexdigest() in assertion
