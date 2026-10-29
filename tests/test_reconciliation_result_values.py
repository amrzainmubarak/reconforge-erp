"""Reject invalid result values without changing the historical omitted-value default."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from typing import Any

import numpy as np
import pytest

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)
from tests.test_reconciliation_exception_collision import (
    TENANT,
    owned_collision_database,  # noqa: F401 -- pytest fixture
    run_repository,  # noqa: F401 -- pytest fixture
)


def _item(**overrides: object) -> dict[str, Any]:
    return {
        "left_id": "Left", "right_id": "Right", "match_type": "deterministic", "confidence": "0.9",
        "explanation": "Synthetic result", "amount_difference": "0", "date_difference_days": None,
        "status": "Matched", "reason_code": "MATCH", "lineage": {},
        **overrides,
    }


def _rows(boundary: PostgresTenantBoundary, run_id: str) -> list[dict[str, Any]]:
    with boundary.transaction(TENANT) as connection:
        return PostgresReconciliationRepository(connection).list_results(tenant_id=TENANT, run_id=run_id)


def _append(repo: PostgresReconciliationRepository, run_id: str, item: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "single":
        return repo.append_result(tenant_id=TENANT, run_id=run_id, **item)
    return repo.append_results_batch(tenant_id=TENANT, run_id=run_id, items=[item])[0]


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", 0.0, True, "1e-18", Decimal("1E-18"), "-1", "9" * 21])
def test_explicit_missing_or_invalid_amount_difference_is_rejected(
    run_repository, mode: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
        _append(PostgresReconciliationRepository(connection), run_id, _item(amount_difference=value), mode)
    assert _rows(boundary, run_id) == []


class _FloatSubclass(float):
    pass


class _NumpyFloatSubclass(np.float32):
    pass


class _ExactTextSubclass(str):
    def __str__(self) -> str:
        raise AssertionError("custom string conversion must not be called")

    def strip(self, *_: object) -> str:
        raise AssertionError("custom strip must not be called")


class _ExactDecimalSubclass(Decimal):
    def __str__(self) -> str:
        raise AssertionError("custom decimal conversion must not be called")


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("field", ["amount_difference", "confidence"])
@pytest.mark.parametrize("value", [
    np.float16("0.5"), np.float32("0.5"), np.float64("0.5"), np.longdouble("0.5"),
    _FloatSubclass(0.5), _NumpyFloatSubclass("0.5"),
])
def test_binary_float_scalars_are_rejected_in_result_financial_fields(
    run_repository, mode: str, field: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
        _append(PostgresReconciliationRepository(connection), run_id, _item(**{field: value}), mode)
    assert _rows(boundary, run_id) == []


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("field", ["amount_difference", "confidence"])
@pytest.mark.parametrize("value", [np.array(0.5), np.ma.array(0.5), np.array(np.float32("0.5")), np.array(1)])
def test_wrapped_numpy_scalars_are_rejected_as_financial_values(
    run_repository, mode: str, field: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
        _append(PostgresReconciliationRepository(connection), run_id, _item(**{field: value}), mode)
    assert _rows(boundary, run_id) == []


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("field", ["amount_difference", "confidence"])
@pytest.mark.parametrize("value", [np.int8(1), np.int64(1), np.uint64(1)])
def test_exact_numpy_integral_values_remain_accepted(
    run_repository, mode: str, field: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        result = _append(PostgresReconciliationRepository(connection), run_id, _item(**{field: value}), mode)
    assert Decimal(result[field]) == Decimal("1")


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("field", ["amount_difference", "confidence"])
@pytest.mark.parametrize("value", [_ExactTextSubclass("0.5"), _ExactDecimalSubclass("0.5")])
def test_exact_scalar_subclasses_do_not_require_custom_string_conversion(
    run_repository, mode: str, field: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        result = _append(PostgresReconciliationRepository(connection), run_id, _item(**{field: value}), mode)
    assert Decimal(result[field]) == Decimal("0.5")


@pytest.mark.parametrize("mode", ["single", "batch", "source"])
def test_arbitrary_string_conversion_cannot_supply_a_financial_value(run_repository, mode: str) -> None:  # noqa: F811
    class NumericLookingObject:
        rendered = False

        def __str__(self) -> str:
            self.rendered = True
            return "0.5"

    boundary, run_id = run_repository
    value = NumericLookingObject()
    with boundary.transaction(TENANT) as connection:
        repo = PostgresReconciliationRepository(connection)
        with pytest.raises(PostgresReconciliationValidationError):
            if mode == "source":
                repo.register_input(tenant_id=TENANT, run_id=run_id, side="Left", source_id="unexpected",
                                    record_hash="synthetic", amount=value, currency_code="USD")
            else:
                _append(repo, run_id, _item(amount_difference=value), mode)
    assert not value.rendered
    assert _rows(boundary, run_id) == []


@pytest.mark.parametrize("field", ["amount_difference", "confidence"])
@pytest.mark.parametrize("value", [np.float16("0.5"), np.float32("0.5"), np.longdouble("0.5"), _FloatSubclass(0.5)])
def test_single_result_rejects_binary_float_before_database_access(field: str, value: object) -> None:
    class NoDatabaseAccess:
        def execute(self, *_: object) -> object:
            raise AssertionError("invalid financial value must not access the database")

    repo = PostgresReconciliationRepository(NoDatabaseAccess())
    with pytest.raises(PostgresReconciliationValidationError):
        repo.append_result(tenant_id="tenant", run_id="run", **_item(**{field: value}))


@pytest.mark.parametrize("field", ["amount_difference", "confidence"])
def test_extreme_integer_is_bounded_without_string_conversion(field: str) -> None:
    class NoDatabaseAccess:
        def execute(self, *_: object) -> object:
            raise AssertionError("oversized financial value must not access the database")

    class HugeInteger(int):
        def __str__(self) -> str:
            raise AssertionError("oversized integer must not be rendered")

    value = HugeInteger(10 ** 5000)
    with pytest.raises(PostgresReconciliationValidationError):
        PostgresReconciliationRepository(NoDatabaseAccess()).append_result(
            tenant_id="tenant", run_id="run", **_item(**{field: value}),
        )


@pytest.mark.parametrize("value", [np.float16("0.5"), np.float32("0.5"), np.longdouble("0.5")])
def test_binary_float_scalars_are_rejected_as_source_amounts(run_repository, value: object) -> None:  # noqa: F811
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        repo = PostgresReconciliationRepository(connection)
        before = repo.list_inputs(tenant_id=TENANT, run_id=run_id)
        with pytest.raises(PostgresReconciliationValidationError):
            repo.register_input(
                tenant_id=TENANT, run_id=run_id, side="Left", source_id="untrusted",
                record_hash="synthetic", amount=value, currency_code="USD",
            )
        assert repo.list_inputs(tenant_id=TENANT, run_id=run_id) == before


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("value", [np.float16("0.5"), np.float32("0.5"), np.longdouble("0.5")])
def test_binary_float_scalars_are_rejected_as_exception_risk(
    run_repository, mode: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    item = {"exception_type": "quality", "source_side": "Left", "source_id": "synthetic",
            "title": "Synthetic", "explanation": "Synthetic", "severity": "Low", "risk_score": value,
            "reason_code": "SYNTHETIC", "evidence": {}}
    with boundary.transaction(TENANT) as connection:
        repo = PostgresReconciliationRepository(connection)
        with pytest.raises(PostgresReconciliationValidationError):
            if mode == "single":
                repo.append_exception(tenant_id=TENANT, run_id=run_id, **item)
            else:
                repo.append_exceptions_batch(tenant_id=TENANT, run_id=run_id, items=[item])
        assert repo.list_exceptions(tenant_id=TENANT, run_id=run_id) == []


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_historical_omitted_difference_default_is_preserved_but_not_financial_qualification(
    run_repository, mode: str,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    item = _item()
    del item["amount_difference"]
    with boundary.transaction(TENANT) as connection:
        stored = _append(PostgresReconciliationRepository(connection), run_id, item, mode)
    assert Decimal(stored["amount_difference"]) == Decimal("0")


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("value", ["0", "0.00", "0.000000000000000001", "99999999999999999999.999999999999999999"])
def test_valid_exact_difference_boundaries_are_preserved(run_repository, mode: str, value: str) -> None:  # noqa: F811
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        stored = _append(PostgresReconciliationRepository(connection), run_id, _item(amount_difference=value), mode)
    assert Decimal(stored["amount_difference"]) == Decimal(value)


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("value", [
    True, False, 0.0, 1.0, 1.5, float("nan"), float("inf"), Decimal("1.1"), Decimal("-0.1"),
    Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("1E+999999999"), Decimal("1E-999999999"),
    "1.0", "1_0", "1e0", "-1", 10_000_001, "9999999999999999999999999999999999999",
])
def test_date_difference_rejects_float_fraction_malformed_and_out_of_range(
    run_repository, mode: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
        _append(PostgresReconciliationRepository(connection), run_id, _item(date_difference_days=value), mode)
    assert _rows(boundary, run_id) == []


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize(("value", "expected"), [
    (None, None), (0, 0), (1, 1), (10_000_000, 10_000_000),
    ("0", 0), ("+1", 1), (" 42 ", 42), (Decimal("1.0"), 1), (Decimal("0.00"), 0),
])
def test_nullable_and_exact_integer_date_differences_are_preserved(
    run_repository, mode: str, value: object, expected: int | None,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        stored = _append(PostgresReconciliationRepository(connection), run_id, _item(date_difference_days=value), mode)
    assert stored["date_difference_days"] == expected


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("value", [Decimal("0.9999999999"), Decimal("10000000.0000000001")])
def test_fractional_days_are_not_rounded_away_by_ambient_decimal_context(
    run_repository, mode: str, value: Decimal,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with localcontext() as ambient:
        ambient.prec = 1
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
            _append(PostgresReconciliationRepository(connection), run_id, _item(date_difference_days=value), mode)
    assert _rows(boundary, run_id) == []


@pytest.mark.parametrize(("field", "value"), [("amount_difference", None), ("date_difference_days", 1.5)])
def test_invalid_second_batch_item_caught_by_caller_leaves_no_partial_rows(
    run_repository, field: str, value: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    first = _item(right_id="", match_type="unmatched", status="Unmatched", reason_code="MISSING_RIGHT")
    second = _item(**{field: value})
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
        PostgresReconciliationRepository(connection).append_results_batch(
            tenant_id=TENANT, run_id=run_id, items=[first, second], chunk_size=1,
        )
    assert _rows(boundary, run_id) == []

class _LyingInteger(int):
    def __int__(self) -> int:
        return 1


class _LyingNumpyInteger(np.int64):
    def __int__(self) -> int:
        return 1


class _LyingDateDecimal(Decimal):
    def __int__(self) -> int:
        return 1


class _LyingDateText(str):
    def strip(self, *_: object) -> str:
        return "1"


@pytest.mark.parametrize("value", [_LyingInteger(100), _LyingNumpyInteger(100)])
def test_integral_subclasses_cannot_change_financial_value(value: object) -> None:
    try:
        result = PostgresReconciliationRepository._decimal(value, "amount_difference")
    except PostgresReconciliationValidationError:
        return
    assert result == "100"


@pytest.mark.parametrize("value", [_LyingDateDecimal("100"), _LyingDateText("100")])
def test_date_subclasses_cannot_change_value(value: object) -> None:
    try:
        result = PostgresReconciliationRepository._result_date_difference(value)
    except PostgresReconciliationValidationError:
        return
    assert result == 100


@pytest.mark.parametrize("field", ["amount_difference", "confidence", "amount", "risk_score"])
def test_unbounded_decimal_text_is_rejected_before_parsing(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.infrastructure.postgres_reconciliation as module
    original = module.Decimal

    class GuardedDecimal(original):
        def __new__(cls, value: object = "0") -> Decimal:
            if isinstance(value, str) and len(value) > 256:
                raise AssertionError("unbounded text reached Decimal")
            return original.__new__(cls, value)

    monkeypatch.setattr(module, "Decimal", GuardedDecimal)
    with pytest.raises(PostgresReconciliationValidationError):
        PostgresReconciliationRepository._decimal("0" * 1000000, field)


def test_unbounded_day_text_is_rejected_before_integer_conversion() -> None:
    with pytest.raises(PostgresReconciliationValidationError):
        PostgresReconciliationRepository._result_date_difference("0" * 1000000)


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize(("field", "value", "expected"), [
    ("amount_difference", _LyingInteger(100), "100"),
    ("date_difference_days", _LyingDateDecimal("100"), 100),
    ("date_difference_days", _LyingDateText("100"), 100),
])
def test_subclass_cannot_change_value_when_persisted(
    run_repository, mode: str, field: str, value: object, expected: object,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        row = _append(PostgresReconciliationRepository(connection), run_id, _item(**{field: value}), mode)
    if field == "amount_difference":
        assert Decimal(row[field]) == Decimal(str(expected))
    else:
        assert row[field] == expected


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_numpy_integer_subclass_rejected_without_result(
    run_repository, mode: str,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationValidationError):
        _append(PostgresReconciliationRepository(connection), run_id,
                _item(amount_difference=_LyingNumpyInteger(100)), mode)
    assert _rows(boundary, run_id) == []


def test_numeric_text_length_bound_preserves_ordinary_values() -> None:
    repo = PostgresReconciliationRepository
    assert repo._decimal("0" * 256, "amount") == "0"
    assert repo._result_date_difference("0" * 256) == 0
    with pytest.raises(PostgresReconciliationValidationError):
        repo._decimal("0" * 257, "amount")
    with pytest.raises(PostgresReconciliationValidationError):
        repo._result_date_difference("0" * 257)


@pytest.mark.parametrize(("field", "value"), [
    ("amount_difference", _LyingNumpyInteger(100)),
    ("amount_difference", "0" * 257),
    ("date_difference_days", "0" * 257),
])
def test_new_rejections_occur_before_any_single_result_database_access(field: str, value: object) -> None:
    class NoConnection:
        def execute(self, *_: object, **__: object) -> None:
            raise AssertionError("database must not be accessed")

    with pytest.raises(PostgresReconciliationValidationError):
        _append(PostgresReconciliationRepository(NoConnection()), "run", _item(**{field: value}), "single")
