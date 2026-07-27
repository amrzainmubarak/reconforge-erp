from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pandas as pd
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from reconforge.config import ReconForgeConfig
from reconforge.db.migrations import MIGRATIONS
from reconforge.engines.base import EngineResult
from reconforge.engines.duckdb_engine import DuckDBEngine
from reconforge.engines.pandas_engine import PandasEngine
from reconforge.engines.signature import build_reconciliation_signature
from reconforge.platform.matching import MatchingService
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY, MatchingStrategy
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import REQUIRED_COLUMNS, DatasetName
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

PROPERTY_SETTINGS = settings(
    max_examples=35,
    derandomize=True,
    deadline=None,
)
ENGINE_PARITY_SETTINGS = settings(
    max_examples=10,
    derandomize=True,
    deadline=None,
)
_RECORD_CODES = st.lists(
    st.integers(min_value=0, max_value=4),
    min_size=1,
    max_size=7,
)


def _stock_record(code: int) -> dict[str, object]:
    records: tuple[dict[str, object], ...] = (
        {
            "move_id": "MOVE-TIE-A",
            "date": "2026-07-25",
            "source_document": "REF-TIE",
            "work_order": "WO-TIE",
            "total_cost": Decimal("10.00"),
            "currency": "USD",
        },
        {
            "move_id": "MOVE-TIE-B",
            "date": "2026-07-25",
            "source_document": "REF-TIE",
            "work_order": "WO-TIE",
            "total_cost": Decimal("10.00"),
            "currency": "USD",
        },
        {
            "move_id": "MOVE-BAD",
            "date": "2026-07-25",
            "source_document": "REF-BAD",
            "work_order": "WO-BAD",
            "total_cost": "not-an-amount",
            "currency": "USD",
        },
        {
            "move_id": "MOVE-OTHER",
            "date": "2026-07-24",
            "source_document": "REF-OTHER",
            "work_order": "WO-OTHER",
            "total_cost": Decimal("25.00"),
            "currency": "USD",
        },
        {
            "move_id": "MOVE-NO-DATE",
            "date": "",
            "source_document": "REF-NO-DATE",
            "work_order": "WO-NO-DATE",
            "total_cost": Decimal("5.00"),
            "currency": "USD",
        },
    )
    return dict(records[code])


def _gl_record(code: int) -> dict[str, object]:
    records: tuple[dict[str, object], ...] = (
        {
            "entry_id": "GL-TIE-A",
            "date": "2026-07-25",
            "reference": "REF-TIE",
            "work_order": "WO-TIE",
            "amount": Decimal("10.00"),
            "currency": "USD",
        },
        {
            "entry_id": "GL-TIE-B",
            "date": "2026-07-25",
            "reference": "REF-TIE",
            "work_order": "WO-TIE",
            "amount": Decimal("10.00"),
            "currency": "USD",
        },
        {
            "entry_id": "GL-BAD",
            "date": "2026-07-25",
            "reference": "REF-BAD",
            "work_order": "WO-BAD",
            "amount": "not-an-amount",
            "currency": "USD",
        },
        {
            "entry_id": "GL-OTHER",
            "date": "2026-07-24",
            "reference": "REF-OTHER",
            "work_order": "WO-OTHER",
            "amount": Decimal("25.00"),
            "currency": "USD",
        },
        {
            "entry_id": "GL-NO-DATE",
            "date": "",
            "reference": "REF-NO-DATE",
            "work_order": "WO-NO-DATE",
            "amount": Decimal("5.00"),
            "currency": "USD",
        },
    )
    return dict(records[code])


@st.composite
def _stock_gl_permutation_cases(
    draw: st.DrawFn,
) -> tuple[list[int], list[int], list[int], list[int], MatchingStrategy]:
    stock_codes = draw(_RECORD_CODES)
    gl_codes = draw(_RECORD_CODES)
    stock_permutation = list(draw(st.permutations(tuple(stock_codes))))
    gl_permutation = list(draw(st.permutations(tuple(gl_codes))))
    matching_strategy = cast(
        MatchingStrategy,
        draw(st.sampled_from(("standard", "strict", "aggressive", "audit-safe"))),
    )
    return stock_codes, gl_codes, stock_permutation, gl_permutation, matching_strategy


@PROPERTY_SETTINGS
@given(_stock_gl_permutation_cases())
def test_stock_gl_signature_is_property_invariant_under_duplicate_invalid_and_tied_permutations(
    case: tuple[list[int], list[int], list[int], list[int], MatchingStrategy],
) -> None:
    stock_codes, gl_codes, stock_permutation, gl_permutation, matching_strategy = case
    config = ReconForgeConfig()

    original = reconcile_stock_gl(
        pd.DataFrame([_stock_record(code) for code in stock_codes]),
        pd.DataFrame([_gl_record(code) for code in gl_codes]),
        config,
        matching_strategy=matching_strategy,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    permuted = reconcile_stock_gl(
        pd.DataFrame([_stock_record(code) for code in stock_permutation]),
        pd.DataFrame([_gl_record(code) for code in gl_permutation]),
        config,
        matching_strategy=matching_strategy,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    original_signature = build_reconciliation_signature(
        matched_transactions=original.matched_transactions,
        all_exceptions=original.all_exceptions,
    )
    permuted_signature = build_reconciliation_signature(
        matched_transactions=permuted.matched_transactions,
        all_exceptions=permuted.all_exceptions,
    )
    assert original_signature == permuted_signature
    assert original.summary.to_dict(orient="records") == permuted.summary.to_dict(orient="records")
    assert original.invariants == permuted.invariants


def _engine_stock_record(code: int) -> dict[str, object]:
    record = _stock_record(code)
    record.update(
        {
            "product_code": "PRODUCT-1",
            "product_name": "Synthetic product",
            "category": "Engine",
            "quantity": "1",
            "unit_cost": record["total_cost"],
            "warehouse": "WAREHOUSE-1",
            "movement_type": "ISSUE",
            "customer_code": "CUSTOMER-1",
            "equipment_serial": "SERIAL-1",
            "created_by": "property-test",
        }
    )
    return record


def _engine_gl_record(code: int) -> dict[str, object]:
    record = _gl_record(code)
    record.update(
        {
            "journal": "INVENTORY",
            "account_code": "1400",
            "account_name": "Inventory",
            "source_document": record["reference"],
            "debit": "0",
            "credit": "0",
            "cost_center": "COST-CENTER-1",
            "created_by": "property-test",
        }
    )
    return record


def _write_engine_case(target: Path, *, stock_codes: list[int], gl_codes: list[int]) -> None:
    target.mkdir(parents=True)
    stock_columns = [*REQUIRED_COLUMNS[DatasetName.STOCK_MOVES], "currency"]
    gl_columns = [*REQUIRED_COLUMNS[DatasetName.GL_ENTRIES], "currency"]
    pd.DataFrame(
        [_engine_stock_record(code) for code in stock_codes],
        columns=stock_columns,
    ).to_csv(target / "stock_moves.csv", index=False)
    pd.DataFrame(
        [_engine_gl_record(code) for code in gl_codes],
        columns=gl_columns,
    ).to_csv(target / "gl_entries.csv", index=False)


def _engine_result_contract(result: EngineResult) -> tuple[object, ...]:
    return (
        result.reconciliation_signature,
        result.reconciliation_signature_version,
        result.financial_input_policy,
        result.record_identity_policy,
        result.matching_ambiguity_policy,
        result.matched_rows,
        result.exception_rows,
        result.stock_rows,
        result.gl_rows,
        tuple(
            (str(item["metric"]), int(item["count"]))
            for item in result.summary.to_dict(orient="records")
        ),
    )


@st.composite
def _engine_permutation_cases(
    draw: st.DrawFn,
) -> tuple[list[int], list[int], list[int], list[int]]:
    stock_codes = draw(_RECORD_CODES)
    gl_codes = draw(_RECORD_CODES)
    stock_permutation = list(draw(st.permutations(tuple(stock_codes))))
    gl_permutation = list(draw(st.permutations(tuple(gl_codes))))
    return stock_codes, gl_codes, stock_permutation, gl_permutation


@pytest.mark.skipif(
    importlib.util.find_spec("duckdb") is None,
    reason="optional DuckDB dependency is not installed",
)
@ENGINE_PARITY_SETTINGS
@given(_engine_permutation_cases())
@example(([0], [0], [0], [0]))
@example(
    (
        [0, 0, 2, 4],
        [0, 0, 2, 4],
        [4, 0, 2, 0],
        [2, 0, 4, 0],
    )
)
def test_pandas_duckdb_full_scan_and_partitioned_digests_are_property_equivalent(
    case: tuple[list[int], list[int], list[int], list[int]],
) -> None:
    stock_codes, gl_codes, stock_permutation, gl_permutation = case
    config = ReconForgeConfig()

    with tempfile.TemporaryDirectory(prefix="reconforge-engine-parity-") as temporary:
        root = Path(temporary)
        original = root / "original"
        permuted = root / "permuted"
        _write_engine_case(original, stock_codes=stock_codes, gl_codes=gl_codes)
        _write_engine_case(permuted, stock_codes=stock_permutation, gl_codes=gl_permutation)

        results = [
            PandasEngine().run(original, config),
            PandasEngine().run(permuted, config),
            DuckDBEngine().run(original, config),
            DuckDBEngine().run(permuted, config),
        ]
        with patch.object(DuckDBEngine, "_FULL_SCAN_ROW_LIMIT", 1):
            results.extend(
                (
                    DuckDBEngine().run(original, config),
                    DuckDBEngine().run(permuted, config),
                )
            )

    contracts = [_engine_result_contract(result) for result in results]
    assert all(contract == contracts[0] for contract in contracts[1:])
    assert contracts[0][0]
    assert contracts[0][1:5] == (
        "reconciliation-signature-v3",
        STRICT_FINANCIAL_INPUT_POLICY,
        RECORD_IDENTITY_POLICY,
        "stable-tie-break-v1",
    )


def _platform_record(code: int, *, side: str) -> dict[str, object]:
    identifier_prefix = "LEFT" if side == "left" else "RIGHT"
    records: tuple[dict[str, object], ...] = (
        {
            "id": f"{identifier_prefix}-TIE-A",
            "reference": "REF-TIE",
            "amount": "10.00",
            "date": "2026-07-25",
        },
        {
            "id": f"{identifier_prefix}-TIE-B",
            "reference": "REF-TIE",
            "amount": "10.00",
            "date": "2026-07-25",
        },
        {
            "id": f"{identifier_prefix}-BAD",
            "reference": "REF-BAD",
            "amount": "not-an-amount",
            "date": "2026-07-25",
        },
        {
            "id": f"{identifier_prefix}-OTHER",
            "reference": "REF-OTHER",
            "amount": "25.00",
            "date": "2026-07-24",
        },
        {
            "id": f"{identifier_prefix}-NO-DATE",
            "reference": "REF-NO-DATE",
            "amount": "5.00",
            "date": "",
        },
    )
    return dict(records[code])


def _platform_output(
    *,
    left_codes: list[int],
    right_codes: list[int],
    mode: str,
    amount_tolerance: str,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        for migration in MIGRATIONS:
            connection.executescript(migration.sql)
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[_platform_record(code, side="left") for code in left_codes],
            right_records=[_platform_record(code, side="right") for code in right_codes],
            amount_tolerance=amount_tolerance,
            allow_many_to_one=mode == "many_to_one",
            allow_one_to_many=mode == "one_to_many",
            allow_many_to_many=mode == "many_to_many",
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
        )
        return output.results, output.exceptions
    finally:
        connection.close()


@st.composite
def _platform_permutation_cases(
    draw: st.DrawFn,
) -> tuple[list[int], list[int], list[int], list[int], str, str]:
    left_codes = draw(_RECORD_CODES)
    right_codes = draw(_RECORD_CODES)
    left_permutation = list(draw(st.permutations(tuple(left_codes))))
    right_permutation = list(draw(st.permutations(tuple(right_codes))))
    mode = draw(st.sampled_from(("one_to_one", "many_to_one", "one_to_many", "many_to_many")))
    tolerance = draw(st.sampled_from(("0", "0.01", "1.00")))
    return left_codes, right_codes, left_permutation, right_permutation, mode, tolerance


@PROPERTY_SETTINGS
@given(_platform_permutation_cases())
def test_platform_output_is_property_invariant_across_grouping_modes(
    case: tuple[list[int], list[int], list[int], list[int], str, str],
) -> None:
    left_codes, right_codes, left_permutation, right_permutation, mode, tolerance = case

    original = _platform_output(
        left_codes=left_codes,
        right_codes=right_codes,
        mode=mode,
        amount_tolerance=tolerance,
    )
    permuted = _platform_output(
        left_codes=left_permutation,
        right_codes=right_permutation,
        mode=mode,
        amount_tolerance=tolerance,
    )

    assert original == permuted


@st.composite
def _relocation_cases(draw: st.DrawFn) -> tuple[int, int, int, str]:
    filler_count = draw(st.integers(min_value=0, max_value=6))
    first_position = draw(st.integers(min_value=0, max_value=filler_count))
    second_position = draw(st.integers(min_value=0, max_value=filler_count))
    invalid_value = draw(st.sampled_from(("", "not-an-amount", "NaN", "Infinity")))
    return filler_count, first_position, second_position, invalid_value


def _quality_row_at(*, filler_count: int, position: int, invalid_value: str) -> pd.Series:
    records = [
        {
            "move_id": f"MOVE-GOOD-{index}",
            "date": "2026-07-25",
            "source_document": f"REF-GOOD-{index}",
            "work_order": "WO-GOOD",
            "total_cost": Decimal("1.00"),
            "currency": "USD",
        }
        for index in range(filler_count)
    ]
    records.insert(
        position,
        {
            "move_id": "MOVE-RELOCATED-BAD",
            "date": "2026-07-25",
            "source_document": "REF-RELOCATED-BAD",
            "work_order": "WO-BAD",
            "total_cost": invalid_value,
            "currency": "USD",
        },
    )
    empty_gl = pd.DataFrame(
        columns=["entry_id", "date", "reference", "work_order", "amount", "currency"]
    )
    result = reconcile_stock_gl(
        pd.DataFrame(records),
        empty_gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    return result.data_quality_exceptions.loc[
        result.data_quality_exceptions["move_id"].eq("MOVE-RELOCATED-BAD")
    ].iloc[0]


@PROPERTY_SETTINGS
@given(_relocation_cases())
def test_data_quality_identity_property_excludes_physical_row_location(
    case: tuple[int, int, int, str],
) -> None:
    filler_count, first_position, second_position, invalid_value = case
    first = _quality_row_at(
        filler_count=filler_count,
        position=first_position,
        invalid_value=invalid_value,
    )
    second = _quality_row_at(
        filler_count=filler_count,
        position=second_position,
        invalid_value=invalid_value,
    )

    assert first["exception_id"] == second["exception_id"]
    assert first["record_instance_id"] == second["record_instance_id"]
    assert first["source_position"] == first_position + 1
    assert second["source_position"] == second_position + 1
    assert first["source_row"] == first_position + 2
    assert second["source_row"] == second_position + 2
