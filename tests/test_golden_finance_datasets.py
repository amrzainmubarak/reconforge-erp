from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import EngineResult
from reconforge.engines.duckdb_engine import DuckDBEngine
from reconforge.engines.pandas_engine import PandasEngine
from reconforge.reconciliation.matching import MatchingAmbiguityPolicy

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tests" / "golden" / "finance_registry.v1.json"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "golden_finance_dataset_registry.schema.json"
SUMMARY_ORDER = (
    "matched_transactions",
    "stock_without_gl",
    "gl_without_stock",
    "value_differences",
    "date_differences",
    "reference_mismatches",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _without(payload: dict[str, Any], field: str) -> dict[str, Any]:
    unsigned = deepcopy(payload)
    unsigned.pop(field)
    return unsigned


def _input_dir(case: dict[str, Any]) -> Path:
    parents = {(ROOT / str(item["path"])).resolve().parent for item in case["files"]}
    assert len(parents) == 1
    return parents.pop()


def _config(case: dict[str, Any]) -> ReconForgeConfig:
    configuration = case["configuration"]
    assert configuration["matching_strategy"] == "standard"
    return ReconForgeConfig(
        amount_tolerance=Decimal(str(configuration["amount_tolerance"])),
        date_tolerance_days=int(configuration["date_tolerance_days"]),
        matching_ambiguity_policy=cast(
            "MatchingAmbiguityPolicy",
            str(configuration["matching_ambiguity_policy"]),
        ),
    )


def _result_contract(result: EngineResult) -> dict[str, object]:
    return {
        "stock_rows": result.stock_rows,
        "gl_rows": result.gl_rows,
        "matched_rows": result.matched_rows,
        "exception_rows": result.exception_rows,
        "summary": result.summary.to_dict(orient="records"),
        "reconciliation_signature": result.reconciliation_signature,
        "reconciliation_signature_version": result.reconciliation_signature_version,
        "financial_input_policy": result.financial_input_policy,
        "record_identity_policy": result.record_identity_policy,
        "matching_ambiguity_policy": result.matching_ambiguity_policy,
    }


REGISTRY = _load_json(REGISTRY_PATH)
CASES = REGISTRY["cases"]


def test_golden_finance_registry_schema_digests_files_and_order_are_valid() -> None:
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(REGISTRY)

    assert REGISTRY["registry_digest"] == _digest(_without(REGISTRY, "registry_digest"))
    assert [case["id"] for case in CASES] == sorted(case["id"] for case in CASES)
    assert len({case["id"] for case in CASES}) == len(CASES)

    root = ROOT.resolve()
    for case in CASES:
        assert case["synthetic"] is True
        assert case["expected_digest"] == _digest(case["expected"])
        assert case["case_digest"] == _digest(_without(case, "case_digest"))
        assert tuple(item["metric"] for item in case["expected"]["summary"]) == SUMMARY_ORDER
        assert {item["dataset"] for item in case["files"]} == {"stock_moves", "gl_entries"}
        for item in case["files"]:
            path = (root / str(item["path"])).resolve()
            assert path.is_relative_to(root)
            content = path.read_bytes()
            assert len(content) == item["bytes"]
            assert hashlib.sha256(content).hexdigest() == item["sha256"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_golden_finance_pandas_outputs_match_registry(case: dict[str, Any]) -> None:
    result = PandasEngine().run(_input_dir(case), _config(case))
    assert _result_contract(result) == case["expected"]


@pytest.mark.skipif(
    importlib.util.find_spec("duckdb") is None,
    reason="optional DuckDB dependency is not installed",
)
@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_golden_finance_duckdb_full_and_partitioned_outputs_match_registry(case: dict[str, Any]) -> None:
    input_dir = _input_dir(case)
    config = _config(case)
    full_scan = DuckDBEngine().run(input_dir, config)
    with patch.object(DuckDBEngine, "_FULL_SCAN_ROW_LIMIT", 1):
        partitioned = DuckDBEngine().run(input_dir, config)
    assert _result_contract(full_scan) == case["expected"]
    assert _result_contract(partitioned) == case["expected"]
