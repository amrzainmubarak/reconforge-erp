from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import EngineResult
from reconforge.engines.duckdb_engine import DuckDBEngine
from reconforge.engines.pandas_engine import PandasEngine
from reconforge.engines.signature import build_reconciliation_signature
from reconforge.reconciliation.stock_gl import StockGLReconciliationResult, reconcile_stock_gl
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

ROOT = Path(__file__).resolve().parents[1]


def _stock_row(identifier: str, *, currency: str, amount: str, reference: str) -> dict[str, object]:
    return {
        "move_id": identifier,
        "date": "2026-07-25",
        "source_document": reference,
        "work_order": "WO-DENSE",
        "total_cost": Decimal(amount),
        "currency": currency,
    }


def _gl_row(identifier: str, *, currency: str, amount: str, reference: str) -> dict[str, object]:
    return {
        "entry_id": identifier,
        "date": "2026-07-25",
        "reference": reference,
        "work_order": "WO-DENSE",
        "amount": Decimal(amount),
        "currency": currency,
    }


def _dense_currency_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    stock = [
        *(
            _stock_row(f"MOVE-USD-{index}", currency="USD", amount="100.00", reference="REF-USD")
            for index in range(1, 4)
        ),
        *(
            _stock_row(f"MOVE-JPY-{index}", currency="JPY", amount="5000", reference="REF-JPY")
            for index in range(1, 3)
        ),
        _stock_row("MOVE-EUR-UNIQUE", currency="EUR", amount="42.00", reference="REF-EUR-UNIQUE"),
    ]
    gl = [
        *(
            _gl_row(f"GL-USD-{index}", currency="USD", amount="100.00", reference="REF-USD")
            for index in range(1, 4)
        ),
        *(
            _gl_row(f"GL-JPY-{index}", currency="JPY", amount="5000", reference="REF-JPY")
            for index in range(1, 3)
        ),
        _gl_row("GL-EUR-UNIQUE", currency="EUR", amount="42.00", reference="REF-EUR-UNIQUE"),
    ]
    return pd.DataFrame(stock), pd.DataFrame(gl)


def _signature(result: StockGLReconciliationResult) -> str:
    return build_reconciliation_signature(
        matched_transactions=result.matched_transactions,
        all_exceptions=result.all_exceptions,
    )


def _engine_contract(result: EngineResult) -> tuple[object, ...]:
    return (
        result.reconciliation_signature,
        result.reconciliation_signature_version,
        result.financial_input_policy,
        result.record_identity_policy,
        result.matching_ambiguity_policy,
        result.matched_rows,
        result.exception_rows,
        tuple(
            (str(row["metric"]), int(row["count"]))
            for row in result.summary.to_dict(orient="records")
        ),
    )


def test_unresolved_equal_cost_policy_is_currency_scoped_explainable_and_permutation_stable() -> None:
    stock, gl = _dense_currency_frames()
    config = ReconForgeConfig(matching_ambiguity_policy="unresolved-equal-cost-v1")

    first = reconcile_stock_gl(
        stock,
        gl,
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    permuted = reconcile_stock_gl(
        stock.sample(frac=1, random_state=47).reset_index(drop=True),
        gl.sample(frac=1, random_state=48).reset_index(drop=True),
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert first.matching_ambiguity_policy == "unresolved-equal-cost-v1"
    assert list(first.matched_transactions[["move_id", "entry_id"]].itertuples(index=False, name=None)) == [
        ("MOVE-EUR-UNIQUE", "GL-EUR-UNIQUE")
    ]
    ambiguities = first.all_exceptions[first.all_exceptions["exception_type"].eq("ambiguous_match")]
    assert len(ambiguities) == 10
    assert ambiguities["ambiguity_group_id"].nunique() == 2
    assert set(ambiguities["ambiguity_reason"]) == {"equal_cost_alternative"}
    assert set(ambiguities["ambiguity_candidate_count"]) == {4, 9}
    assert set(ambiguities["ambiguity_optimal_cardinality"]) == {2, 3}
    assert set(ambiguities["matching_ambiguity_policy"]) == {"unresolved-equal-cost-v1"}
    assert first.invariants["record_accounting_ok"] is True
    assert _signature(first) == _signature(permuted)
    assert first.summary.to_dict(orient="records") == permuted.summary.to_dict(orient="records")

    compatible = reconcile_stock_gl(
        stock,
        gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    assert compatible.matching_ambiguity_policy == "stable-tie-break-v1"
    assert len(compatible.matched_transactions) == 6
    assert not compatible.all_exceptions["exception_type"].eq("ambiguous_match").any()


def test_unresolved_policy_fails_closed_when_candidate_budget_is_exceeded() -> None:
    stock = pd.DataFrame(
        [
            _stock_row(f"MOVE-BUDGET-{index}", currency="USD", amount="10.00", reference="REF-BUDGET")
            for index in range(1, 10)
        ]
    )
    gl = pd.DataFrame(
        [
            _gl_row(f"GL-BUDGET-{index}", currency="USD", amount="10.00", reference="REF-BUDGET")
            for index in range(1, 10)
        ]
    )

    result = reconcile_stock_gl(
        stock,
        gl,
        ReconForgeConfig(matching_ambiguity_policy="unresolved-equal-cost-v1"),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert result.matched_transactions.empty
    assert len(result.all_exceptions) == 18
    assert set(result.all_exceptions["exception_type"]) == {"ambiguous_match"}
    assert set(result.all_exceptions["ambiguity_reason"]) == {"search_budget_exceeded"}
    assert set(result.all_exceptions["ambiguity_candidate_count"]) == {81}
    assert set(result.all_exceptions["ambiguity_optimal_cardinality"]) == {9}
    assert result.all_exceptions["ambiguity_group_id"].nunique() == 1
    assert result.invariants["record_accounting_ok"] is True


@pytest.mark.skipif(
    importlib.util.find_spec("duckdb") is None,
    reason="optional DuckDB dependency is not installed",
)
def test_dense_ambiguity_is_cross_engine_and_csv_permutation_stable(tmp_path: Path) -> None:
    source = ROOT / "tests" / "golden" / "stock_gl_dense_ambiguity_v1"
    permuted = tmp_path / "permuted"
    permuted.mkdir()
    pd.read_csv(source / "stock_moves.csv", dtype=str).sample(
        frac=1,
        random_state=49,
    ).to_csv(permuted / "stock_moves.csv", index=False)
    pd.read_csv(source / "gl_entries.csv", dtype=str).sample(
        frac=1,
        random_state=50,
    ).to_csv(permuted / "gl_entries.csv", index=False)
    config = ReconForgeConfig(matching_ambiguity_policy="unresolved-equal-cost-v1")

    results = [
        PandasEngine().run(source, config),
        PandasEngine().run(permuted, config),
        DuckDBEngine().run(source, config),
        DuckDBEngine().run(permuted, config),
    ]
    with patch.object(DuckDBEngine, "_FULL_SCAN_ROW_LIMIT", 1):
        results.extend(
            (
                DuckDBEngine().run(source, config),
                DuckDBEngine().run(permuted, config),
            )
        )

    contracts = [_engine_contract(result) for result in results]
    assert all(contract == contracts[0] for contract in contracts[1:])
    assert contracts[0] == (
        "cdfb89883b491920dcbd52a27a19003275ffea6e87b9219d059b7d2b67a9d914",
        "reconciliation-signature-v3",
        "strict-financial-input-v2",
        "canonical-multiset-occurrence-v1",
        "unresolved-equal-cost-v1",
        1,
        10,
        (
            ("matched_transactions", 1),
            ("stock_without_gl", 5),
            ("gl_without_stock", 5),
            ("value_differences", 0),
            ("date_differences", 0),
            ("reference_mismatches", 0),
        ),
    )
