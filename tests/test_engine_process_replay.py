from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from reconforge.generator.synthetic import generate_synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]
_CHILD_RUNNER = """
import json
import sys
from pathlib import Path

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import get_engine
from reconforge.engines.duckdb_engine import DuckDBEngine

engine_name = sys.argv[1]
if engine_name == "duckdb":
    DuckDBEngine._FULL_SCAN_ROW_LIMIT = 1
result = get_engine(engine_name).run(Path(sys.argv[2]), ReconForgeConfig())
print(json.dumps({
    "exception_rows": result.exception_rows,
    "financial_input_policy": result.financial_input_policy,
    "gl_rows": result.gl_rows,
    "matched_rows": result.matched_rows,
    "matching_ambiguity_policy": result.matching_ambiguity_policy,
    "record_identity_policy": result.record_identity_policy,
    "reconciliation_signature": result.reconciliation_signature,
    "reconciliation_signature_version": result.reconciliation_signature_version,
    "stock_rows": result.stock_rows,
    "summary": result.summary.to_dict(orient="records"),
}, sort_keys=True, separators=(",", ":")))
"""


def _run_in_fresh_process(engine_name: str, input_dir: Path, *, hash_seed: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = hash_seed
    environment["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_RUNNER, engine_name, str(input_dir)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="optional DuckDB dependency is not installed")
def test_pandas_and_partitioned_duckdb_results_are_process_replay_stable(tmp_path: Path) -> None:
    input_dir = tmp_path / "process-replay"
    generate_synthetic_dataset(500, input_dir, seed=1085)

    pandas_seed_one = _run_in_fresh_process("pandas", input_dir, hash_seed="1")
    pandas_seed_two = _run_in_fresh_process("pandas", input_dir, hash_seed="2")
    duckdb_seed_one = _run_in_fresh_process("duckdb", input_dir, hash_seed="1")
    duckdb_seed_two = _run_in_fresh_process("duckdb", input_dir, hash_seed="2")

    assert pandas_seed_one == pandas_seed_two
    assert duckdb_seed_one == duckdb_seed_two
    assert pandas_seed_one == duckdb_seed_one
