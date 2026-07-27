"""Engine abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from reconforge.config import ReconForgeConfig


@dataclass(frozen=True)
class EngineResult:
    """Standard reconciliation engine output."""

    engine: str
    matched_rows: int
    exception_rows: int
    stock_rows: int
    gl_rows: int
    summary: pd.DataFrame
    reconciliation_signature: str = ""
    reconciliation_signature_version: str = ""
    financial_input_policy: str = ""
    record_identity_policy: str = ""
    matching_ambiguity_policy: str = ""


class ReconciliationEngine(Protocol):
    """Protocol for reconciliation execution backends."""

    name: str

    def run(self, input_dir: Path, config: ReconForgeConfig) -> EngineResult:
        """Run reconciliation and return metrics."""


def get_engine(name: str) -> ReconciliationEngine:
    """Backward-compatible engine lookup wrapper."""

    from reconforge.engines.registry import get_engine as registry_get_engine

    return registry_get_engine(name)
