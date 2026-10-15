"""Raw-contract controls only; synthetic empty tables are not posting proof."""
from __future__ import annotations

import ast
import hashlib
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_monetary_posted_oracle as reader


def packet() -> dict[str, Any]:
    capture = {"capture": 0, "tables": {name: [] for name in reader.TABLES}}
    second = deepcopy(capture)
    second["capture"] = 1
    return {"schema_version": reader.SCHEMA, "tenant_id": "tenant", "source_order_id": "STSALE-original",
            "captures": [capture, second]}


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def row(identifier: str = "row", *, tenant: str = "tenant") -> str:
    return json.dumps({"tenant_id": tenant, "id": identifier}, sort_keys=True)


def storage_row(table: str) -> dict[str, Any]:
    value: dict[str, Any] = dict.fromkeys(reader.MONETARY_COLUMNS[table], "reference")
    value["tenant_id"] = "tenant"
    for field in value:
        if field.endswith("_digest"):
            value[field] = "a" * 64
        elif field in {"payload", "snapshot", "ar_balance", "request_json", "response_json"}:
            value[field] = {}
    for field in {"original_id", "original_effect_id", "posting_effect_id", "stock_fx_plan_id", "partial_plan_id",
                  "original_sequence", "correction_effect_id", "original_restoration_plan_id"} & value.keys():
        value[field] = None
    if table.endswith("_plans"):
        value.update(id="CR3-" + "1" * 32, operation="Return", phase=0, expected_history_version=0)
    elif table.endswith("_entries"):
        value["purpose"] = "CostRestoration"
    elif table.endswith("_events") or table.endswith("_commands"):
        value["operation"] = "prepare"
    elif table.endswith("_history"):
        value.update(sequence=1, kind="Return", partial_plan_id="CR3-" + "1" * 32)
    elif table.endswith("_restorations"):
        value.update(position=1, before_quantity_scaled=2, before_value_minor=1, quantity_scaled=1,
                     value_minor=0, direction=1, consumption_count_at_restore=1)
    return value


def with_storage(table: str, record: dict[str, Any]) -> bytes:
    value = packet()
    value["captures"][1]["tables"][table] = [json.dumps(record, sort_keys=True)]
    return encoded(value)


def test_inventory_is_exact_old79_plus_five_fx_and_seven_monetary_tables() -> None:
    tree = ast.parse(Path(__file__).with_name("customer_partial_return_posted_cycle_oracle.py").read_text(encoding="utf-8"))
    original = next(ast.literal_eval(item.value) for item in tree.body if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "TABLES" for target in item.targets))
    expected = set(original) | {"customer_partial_return_allocation_witnesses", "stock_sales_monetary_origins"}
    expected |= {"operational_fx_" + name for name in ("sources", "plans", "reviews", "links", "commands")}
    expected |= {"customer_partial_return_monetary_" + name for name in
                 ("plans", "entries", "events", "history", "restorations", "commands")}
    assert len(original) == 78 and len(expected) == 91
    assert tuple(sorted(expected)) == reader.TABLES


def test_exact_opaque_row_bytes_and_parent_packet_digest_are_retained() -> None:
    value = packet()
    raw = '{"tenant_id": "tenant", "id": "native", "quantity": 0.1, "value_minor": 1001}'
    value["captures"][1]["tables"]["inventory_layer_consumptions"] = [raw]
    original = encoded(value)
    result = reader.decode_packet(original)
    assert result.sha256 == hashlib.sha256(original).hexdigest() and result.byte_size == len(original)
    assert result.tenant_id == "tenant" and result.source_order_id == "STSALE-original"
    assert dict(result.captures[1].raw_tables)["inventory_layer_consumptions"] == (raw,)
    assert result.captures[1].rows("inventory_layer_consumptions")[0]["quantity"] == Fraction(1, 10)
    assert type(result.captures[1].rows("inventory_layer_consumptions")[0]["value_minor"]) is int
    assert not hasattr(result, "financially_verified") and not hasattr(result, "native_acceptance")


@pytest.mark.parametrize("table", reader.MONETARY_COLUMNS)
def test_seven_storage_shapes_are_closed_without_claiming_deferred_closure(table: str) -> None:
    value = storage_row(table)
    result = reader.decode_packet(with_storage(table, value))
    assert result.captures[1].rows(table) == (value,)
    for field in value:
        incomplete = dict(value)
        incomplete.pop(field)
        with pytest.raises(reader.MonetaryRawRefusal):
            reader.decode_packet(with_storage(table, incomplete))
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, {**value, "unknown_future_column": None}))


@pytest.mark.parametrize("table,field,invalid", [
    ("customer_partial_return_monetary_plans", "phase", True),
    ("customer_partial_return_monetary_plans", "phase", 4),
    ("customer_partial_return_monetary_plans", "expected_history_version", 256),
    ("customer_partial_return_monetary_plans", "id", "CR2-" + "1" * 32),
    ("customer_partial_return_monetary_entries", "entry_id", None),
    ("customer_partial_return_monetary_entries", "original_effect_id", "foreign-inverse"),
    ("customer_partial_return_monetary_events", "operation", "repost"),
    ("customer_partial_return_monetary_history", "sequence", True),
    ("customer_partial_return_monetary_history", "sequence", 257),
    ("customer_partial_return_monetary_history", "stock_fx_plan_id", "FX1-extra"),
    ("customer_partial_return_monetary_restorations", "before_value_minor", -1),
    ("customer_partial_return_monetary_restorations", "quantity_scaled", 3),
    ("customer_partial_return_monetary_restorations", "consumption_count_at_restore", 0),
    ("customer_partial_return_monetary_commands", "request_digest", "A" * 64),
])
def test_new_native_shape_type_and_nullable_effect_invariants(table: str, field: str, invalid: Any) -> None:
    value = storage_row(table)
    value[field] = invalid
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, value))


@pytest.mark.parametrize("original", [None, False, 0, 2])
def test_reversal_history_cannot_use_sql_check_null_or_nonpreceding_original(original: Any) -> None:
    table = "customer_partial_return_monetary_history"
    value = storage_row(table)
    value.update(kind="ReverseReturn", sequence=2, original_sequence=original)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, value))


def test_zero_portion_can_share_positive_plan_effect_but_positive_portion_requires_one() -> None:
    table = "customer_partial_return_monetary_restorations"
    value = storage_row(table)
    assert reader.decode_packet(with_storage(table, value))
    value["correction_effect_id"] = "real-plan-total-effect"
    assert reader.decode_packet(with_storage(table, value))
    value.update(value_minor=1, correction_effect_id=None)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, value))


def test_different_raw_texts_cannot_forge_duplicate_new_primary_keys() -> None:
    table = "customer_partial_return_monetary_events"
    first = storage_row(table)
    second = {**first, "reason": "Different reason for the same primary key"}
    value = packet()
    value["captures"][1]["tables"][table] = sorted([json.dumps(first), json.dumps(second)])
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("name", reader.TABLES)
def test_every_missing_table_refuses_including_empty_financial_owners(name: str) -> None:
    value = packet()
    value["captures"][1]["tables"].pop(name)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("mutation", ["schema", "extra", "missing", "unknown-table", "bool-index", "gap", "duplicate-index",
                                     "one-capture", "too-many", "tenant", "order", "capture-extra"])
def test_closed_envelopes_and_ordered_capture_membership(mutation: str) -> None:
    value = packet()
    if mutation == "schema":
        value["schema_version"] = "customer-partial-return-remainder-posted-cycle-input-v1"
    elif mutation == "extra":
        value["trusted"] = True
    elif mutation == "missing":
        value.pop("tenant_id")
    elif mutation == "unknown-table":
        value["captures"][0]["tables"]["unknown_future_owner"] = []
    elif mutation == "bool-index":
        value["captures"][1]["capture"] = True
    elif mutation == "gap":
        value["captures"][1]["capture"] = 2
    elif mutation == "duplicate-index":
        value["captures"][1]["capture"] = 0
    elif mutation == "one-capture":
        value["captures"].pop()
    elif mutation == "too-many":
        value["captures"] *= 129
    elif mutation == "tenant":
        value["tenant_id"] = " tenant "
    elif mutation == "order":
        value["source_order_id"] = "../outside"
    else:
        value["captures"][0]["case"] = "synthetic"
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("rows", [[row(tenant="other")], [row("same"), row("same")], [row("z"), row("a")],
                                  [1], [False], [None], [{}], ["[]"], ["null"], ["{}"]])
def test_foreign_duplicate_unsorted_or_non_pg_record_rows_refuse(rows: Any) -> None:
    value = packet()
    value["captures"][1]["tables"]["operational_fx_commands"] = rows
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("bad", ["1e100000000", "NaN", "Infinity", "-Infinity", "9000000000000000001", "1" * 97])
def test_numeric_lexemes_are_bounded_before_integer_or_fraction_expansion(bad: str) -> None:
    value = packet()
    value["captures"][0]["tables"]["operational_fx_sources"] = ['{"tenant_id":"tenant","amount":' + bad + '}']
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("where", ["outer", "row"])
def test_duplicate_json_keys_never_last_win(where: str) -> None:
    value = packet()
    if where == "row":
        value["captures"][0]["tables"]["stock_sales_monetary_origins"] = ['{"tenant_id":"other","tenant_id":"tenant"}']
        original = encoded(value)
    else:
        original = encoded(value).replace(b'"tenant_id":"tenant"', b'"tenant_id":"other","tenant_id":"tenant"', 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(original)


def test_invalid_utf8_and_escaped_unpaired_surrogate_rows_refuse() -> None:
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(b"\xff")
    value = packet()
    value["captures"][0]["tables"]["operational_fx_commands"] = ['{"tenant_id":"tenant","id":"\ud800"}']
    original = json.dumps(value, ensure_ascii=True).encode()
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(original)


def test_packet_capture_row_and_rowcount_budgets_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    original = encoded(packet())
    monkeypatch.setattr(reader, "MAX_PACKET_BYTES", len(original) - 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(original)
    monkeypatch.setattr(reader, "MAX_PACKET_BYTES", len(original) + 10000)
    value = packet()
    value["captures"][0]["tables"]["stock_sales_monetary_origins"] = [row()]
    monkeypatch.setattr(reader, "MAX_ROW_BYTES", 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))
    monkeypatch.setattr(reader, "MAX_ROW_BYTES", 1000)
    monkeypatch.setattr(reader, "MAX_CAPTURE_ROWS", 0)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))
    monkeypatch.setattr(reader, "MAX_CAPTURE_ROWS", 20_000)
    monkeypatch.setattr(reader, "MAX_CAPTURE_BYTES", 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


def test_bounded_original_file_and_second_byte_comparison(tmp_path: Path) -> None:
    path = tmp_path / "original.json"
    original = encoded(packet())
    path.write_bytes(original)
    assert reader.read_original(path) == original
    reader.require_original_unchanged(path, original)
    path.write_bytes(original.replace(b"STSALE-original", b"STSALE-modified"))
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.require_original_unchanged(path, original)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(tmp_path)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(Path("relative.json"))
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(tmp_path / ".." / tmp_path.name / "original.json")


def test_reparse_ancestor_refuses_using_real_lstat_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    path = tmp_path / "original.json"
    path.write_bytes(encoded(packet()))
    real = Path.lstat

    def fake(selected: Path) -> Any:
        result = real(selected)
        if selected != tmp_path:
            return result
        fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
        fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0) | 0x400
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "lstat", fake)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(path)
