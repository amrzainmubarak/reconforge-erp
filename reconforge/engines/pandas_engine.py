"""Pandas reconciliation backend."""

from __future__ import annotations

from pathlib import Path

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import EngineResult
from reconforge.engines.signature import (
    CURRENT_RECONCILIATION_SIGNATURE_VERSION,
    build_reconciliation_signature,
)
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import DatasetName
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY


class PandasEngine:
    """Default Pandas backend."""

    name = "pandas"

    def run(self, input_dir: Path, config: ReconForgeConfig) -> EngineResult:
        datasets = read_required_datasets(input_dir, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
        stock = datasets[DatasetName.STOCK_MOVES]
        gl = datasets[DatasetName.GL_ENTRIES]
        result = reconcile_stock_gl(
            stock,
            gl,
            config,
            input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        return EngineResult(
            engine=self.name,
            matched_rows=len(result.matched_transactions),
            exception_rows=len(result.all_exceptions),
            stock_rows=len(stock),
            gl_rows=len(gl),
            summary=result.summary,
            reconciliation_signature=build_reconciliation_signature(
                matched_transactions=result.matched_transactions,
                all_exceptions=result.all_exceptions,
            ),
            reconciliation_signature_version=CURRENT_RECONCILIATION_SIGNATURE_VERSION,
            financial_input_policy=result.financial_input_policy,
            record_identity_policy=result.record_identity_policy,
            matching_ambiguity_policy=result.matching_ambiguity_policy,
        )
