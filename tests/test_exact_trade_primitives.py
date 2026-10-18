"""Financial regressions for quantity ingress and conserved FIFO minor units."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from importlib import import_module
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.application.receivables import ReceivableInvoiceLineInput
from reconforge.domain.inventory_costing import allocate_fifo_value
from reconforge.domain.quantities import parse_quantity, quantity_product_minor
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_values import (
    amount_to_minor,
    minor_to_text,
    quantity_to_scaled,
    scaled_to_text,
)

sqlite_ar = import_module("reconforge.infrastructure.sqlite_receivables")
postgres_ar = import_module("reconforge.infrastructure.postgres_receivables")
sqlite_fifo = import_module("reconforge.infrastructure.sqlite_inventory_valuation")
postgres_fifo = import_module("reconforge.infrastructure.postgres_inventory_valuation")


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
@pytest.mark.parametrize("trap_all", [False, True])
def test_quantities_and_invoice_product_ignore_decimal_context(rounding: str, trap_all: bool) -> None:
    raw = "123456789012345678.123456789012345"
    line = ReceivableInvoiceLineInput("Exact", raw, 1, 123456789012345678)
    with localcontext() as context:
        context.prec = 2
        context.rounding = rounding
        context.Emax = 2
        context.Emin = -2
        for signal in context.traps:
            context.traps[signal] = trap_all
        context.flags[Inexact] = True
        context.flags[Rounded] = True
        flags = dict(context.flags)
        assert sqlite_ar._quantity(raw, field="quantity") == raw
        assert postgres_ar._quantity(raw, "quantity") == (Decimal(raw), raw)
        assert sqlite_ar._normalize_lines([line])[0].quantity == raw
        assert postgres_ar._normalize_lines([line])[0][2] == raw
        half = ReceivableInvoiceLineInput("Half up", "0.5", 5, 3)
        assert sqlite_ar._normalize_lines([half])[0].line_total_minor == 3
        assert postgres_ar._normalize_lines([half])[0][-1] == 3
        assert dict(context.flags) == flags


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_stock_quantity_cost_and_serialization_ignore_decimal_context(rounding: str) -> None:
    with localcontext() as context:
        context.prec = 2
        context.rounding = rounding
        context.Emax = 2
        context.Emin = -2
        for signal in context.traps:
            context.traps[signal] = True
        assert quantity_to_scaled("12345.678", 3) == 12345678
        assert amount_to_minor("12345.67", 2) == 1234567
        assert scaled_to_text(12345678, 3) == "12345.678"
        assert scaled_to_text(-12345678, 3) == "-12345.678"
        assert minor_to_text(1234567, 2) == "12345.67"
        assert quantity_to_scaled("1.23000", 2) == 123
        with pytest.raises(PlatformError, match="precision"):
            quantity_to_scaled("1.234", 2)
        with pytest.raises(PlatformError, match="precision"):
            amount_to_minor("1.234", 2)


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_fifo_half_even_and_final_residual_ignore_decimal_context(rounding: str) -> None:
    with localcontext() as context:
        context.prec = 2
        context.rounding = rounding
        context.Emax = 2
        context.Emin = -2
        for signal in context.traps:
            context.traps[signal] = True
        for value, quantity, consumed, expected in ((199, 3, 1, 66), (5, 2, 1, 2), (7, 2, 1, 4), (67, 1, 1, 67)):
            assert sqlite_fifo.SQLiteInventoryValuationRepositoryAdapter._allocate_layer_value(
                remaining_value=value, remaining_quantity=quantity, consumed_quantity=consumed
            ) == expected
            assert postgres_fifo.PostgresInventoryValuationRepository._allocated_value(value, quantity, consumed) == expected


class _CoercibleQuantity:
    def __str__(self) -> str:
        return "1"


@pytest.mark.parametrize(
    "value", [None, True, False, 1.0, 0.1, [], b"1", _CoercibleQuantity(), "-1", "1e2",
              "1E-13", "NaN", "Infinity", "-0", Decimal("-0"), "(1)", "(-12345)",
              Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")],
)
def test_ar_quantities_refuse_unsupported_ingress(value: object) -> None:
    with pytest.raises(PlatformError, match="quantity"):
        sqlite_ar._quantity(value, field="quantity")
    with pytest.raises(PlatformError, match="quantity"):
        postgres_ar._quantity(value, "quantity")


@pytest.mark.parametrize("value,expected", [("+1", "1"), (".5", "0.5"), ("1.", "1"), ("1_000", "1000"), ("١", "1"), (Decimal("1e2"), "100")])
def test_ar_preserves_existing_exact_decimal_spellings(value: object, expected: str) -> None:
    with localcontext() as context:
        context.prec = 2
        for signal in context.traps:
            context.traps[signal] = True
        assert sqlite_ar._quantity(value, field="quantity") == expected
        assert postgres_ar._quantity(value, "quantity")[1] == expected


def test_ar_preserves_sqlite_grouping_and_long_text_but_postgres_raw_limit() -> None:
    assert sqlite_ar._quantity("1,000", field="quantity") == "1000"
    with pytest.raises(PlatformError):
        postgres_ar._quantity("1,000", "quantity")
    with localcontext() as context:
        context.prec = 2
        for signal in context.traps:
            context.traps[signal] = True
        for length in (81, 5000):
            raw = "1" * length
            assert sqlite_ar._quantity(raw, field="quantity") == raw
            assert quantity_product_minor(Decimal(raw), 0) == 0
            with pytest.raises(PlatformError):
                postgres_ar._quantity(raw, "quantity")


@pytest.mark.parametrize("value", [Decimal("1E+1000000"), Decimal("1E-1000000")])
def test_ar_refuses_oversized_fixed_point_expansion_before_financial_effect(value: Decimal) -> None:
    from reconforge.domain.quantities import quantity_decimal_text

    with pytest.raises(ValueError, match="expansion"):
        quantity_decimal_text(value)
    with pytest.raises(ValueError, match="expansion"):
        quantity_product_minor(value, 1)
    with pytest.raises(PlatformError, match="quantity"):
        sqlite_ar._quantity(value, field="quantity")
    with pytest.raises(PlatformError, match="quantity"):
        postgres_ar._quantity(value, "quantity")


def test_quantity_expansion_limit_matches_existing_structured_scalar_policy() -> None:
    from reconforge.domain.quantities import MAX_QUANTITY_FIXED_CHARACTERS
    from reconforge.io.structured import DEFAULT_STRUCTURED_DOCUMENT_POLICY

    assert DEFAULT_STRUCTURED_DOCUMENT_POLICY.max_scalar_characters == MAX_QUANTITY_FIXED_CHARACTERS


@pytest.mark.parametrize("value", ["+1", ".5", "1.", "1,000", "1_000", "-0", Decimal("-0"), Decimal("1e2"), "١"])
def test_inventory_preserves_its_original_plain_decimal_grammar(value: object) -> None:
    for convert in (quantity_to_scaled, amount_to_minor):
        with pytest.raises(PlatformError):
            convert(value, 3)


@pytest.mark.parametrize("value", [True, 1.0, None, "NaN", "Infinity", "-1", "1e2", "9" * 65, _CoercibleQuantity()])
def test_stock_quantity_and_cost_refuse_unsupported_ingress(value: object) -> None:
    for convert in (quantity_to_scaled, amount_to_minor):
        with pytest.raises(PlatformError):
            convert(value, 2)


def test_exact_ingress_scale_text_and_storage_boundaries() -> None:
    assert parse_quantity("000123.4500").text == "123.45"
    assert parse_quantity(Decimal("1e-13")).text == "0.0000000000001"
    assert parse_quantity("1" * 80).text == "1" * 80
    assert quantity_to_scaled("9000000000000.000000", 6) == 9_000_000_000_000_000_000
    assert amount_to_minor("90000000000.00000000", 8) == 9_000_000_000_000_000_000
    assert amount_to_minor("0", 0) == 0
    assert quantity_to_scaled("0", 0, allow_zero=True) == 0
    for convert, value, scale in (
        (quantity_to_scaled, "9000000000000.000001", 6),
        (amount_to_minor, "90000000000.00000001", 8),
        (quantity_to_scaled, "1", 7), (amount_to_minor, "1", 9),
        (quantity_to_scaled, "1", -1), (amount_to_minor, "1", True),
    ):
        with pytest.raises(PlatformError):
            convert(value, scale)
    with pytest.raises(PlatformError):
        quantity_to_scaled("0", 0)


@pytest.mark.parametrize("arguments", [(0, 3, 1), (1, 0, 1), (1, 3, 0), (5, 3, 4), (True, 2, 1), (5, 2.0, 1), (1, 3, 1), (1, 3, 2)])
def test_fifo_refuses_invalid_or_unrepresentable_partial_allocations(arguments: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        allocate_fifo_value(*arguments)


@given(
    pieces=st.lists(st.integers(min_value=1, max_value=1_000_000), min_size=1, max_size=20),
    unit_cost=st.integers(min_value=1, max_value=1_000_000_000),
    residual=st.integers(min_value=0, max_value=999),
)
@settings(max_examples=150, deadline=None)
def test_fifo_conserves_every_minor_unit_across_arbitrary_issue_sequences(
    pieces: list[int], unit_cost: int, residual: int
) -> None:
    remaining_quantity = sum(pieces)
    original_value = remaining_value = remaining_quantity * unit_cost + residual
    consumed_value = 0
    with localcontext() as context:
        context.prec = 2
        for signal in context.traps:
            context.traps[signal] = True
        for piece in pieces:
            expected = round(Fraction(remaining_value * piece, remaining_quantity))
            allocated = allocate_fifo_value(remaining_value, remaining_quantity, piece)
            assert allocated == expected
            remaining_quantity -= piece
            remaining_value -= allocated
            consumed_value += allocated
            assert consumed_value + remaining_value == original_value
        assert remaining_quantity == remaining_value == 0
        assert consumed_value == original_value


def test_sqlite_ar_persists_full_quantity_and_half_up_product(tmp_path: Path) -> None:
    from tests.test_receivables import _service

    connection, service = _service(tmp_path)
    try:
        service.upsert_customer(customer_code="EXACT", name="Exact", currency_code="USD", credit_limit_minor=0, actor_label="prep")
        raw = "123456789012345678.123456789012345"
        with localcontext() as context:
            context.prec = 2
            for signal in context.traps:
                context.traps[signal] = True
            invoice = service.create_invoice(
                invoice_number="EXACT-1", customer_code="EXACT", invoice_date="2026-07-01", currency_code="USD", tax_minor=0,
                lines=[
                    ReceivableInvoiceLineInput("Exact", raw, 1, 123456789012345678),
                    ReceivableInvoiceLineInput("Half", "0.5", 5, 3),
                    ReceivableInvoiceLineInput("Existing local long quantity", "1" * 5000, 0, 0),
                ],
                actor_label="prep",
            )
        persisted = service.get_invoice(str(invoice["id"]))
        assert persisted["lines"][0]["quantity"] == raw
        assert persisted["lines"][2]["quantity"] == "1" * 5000
        assert persisted["total_minor"] == 123456789012345681
        # Authorization decisions are retained even on refused input; business
        # rows and their outbox effects must be unchanged.
        def financial_state() -> list[list[tuple[object, ...]]]:
            return [
                [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
                for table in ("ar_invoices", "ar_invoice_lines", "outbox_events")
            ]

        before = financial_state()
        for invalid in ("1e2", Decimal("1E+1000000"), Decimal("1E-1000000")):
            with pytest.raises(PlatformError):
                service.create_invoice(
                    invoice_number="INVALID-1", customer_code="EXACT", invoice_date="2026-07-01", currency_code="USD", tax_minor=0,
                    lines=[ReceivableInvoiceLineInput("Invalid", invalid, 1, 100)], actor_label="prep",
                )
            assert financial_state() == before
    finally:
        connection.close()


def test_sqlite_fifo_two_layers_residual_and_physical_quantity_under_tiny_context(tmp_path: Path) -> None:
    from reconforge.db import connect
    from tests.test_inventory_valuation import _database, _movement, _seed, _valuation_document

    connection = connect(_database(tmp_path), require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            context.Emin = -2
            for signal in context.traps:
                context.traps[signal] = True
            for number, quantity, cost in (("1", "3.000", "1.99"), ("2", "2.000", "1.01")):
                receipt = _movement(inventory, period, number=f"RCV-{number}", movement_type="Receipt", movement_date="2026-07-01", quantity=quantity)
                document = _valuation_document(valuation, receipt, number=f"VAL-R-{number}", total_cost=cost)
                valuation.approve_document(str(document["id"]), reason="Reviewed cost evidence")
            totals = []
            consumptions = []
            for number, quantity in (("1", "1.000"), ("2", "3.000"), ("3", "1.000")):
                movement = _movement(inventory, period, number=f"OUT-{number}", movement_type="Delivery", movement_date="2026-07-02", quantity=quantity)
                document = _valuation_document(valuation, movement, number=f"VAL-O-{number}")
                approved = valuation.approve_document(str(document["id"]), reason="Reviewed FIFO evidence")
                totals.append(approved["total_value"])
                consumptions.append([line["value"] for line in approved["layer_consumptions"]])
            assert totals == ["0.66", "1.83", "0.51"]
            assert consumptions == [["0.66"], ["1.33", "0.50"], ["0.51"]]
            layers = valuation.list_cost_layers(open_only=False)
            assert len(layers) == 2
            assert all(layer["remaining_quantity"] == "0.000" and layer["remaining_value"] == "0.00" for layer in layers)
            assert connection.execute("SELECT SUM(value_minor) FROM inventory_layer_consumptions").fetchone()[0] == 300
    finally:
        connection.close()
