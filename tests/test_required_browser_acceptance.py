"""Wire acceptance must reject missing, skipped and retry-flaky execution."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from tests.test_customer_returns_financial_oracle import rows, write_capture

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "required_erp_browser_runner", ROOT / ".github/scripts/verify_erp_expansion_browser.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_required_financial_row_reader_executes_both_isolated_modes_over_complete_private_cohort(tmp_path: Path) -> None:
    """Synthetic reader orchestration; this test executes no database or browser."""
    private = tmp_path / "private"
    originals = private / "playwright-artifacts/native-customer-return-originals"
    originals.mkdir(parents=True)
    for capture in range(1, 4):
        write_capture(originals, rows(), capture)
    before = {path.name: path.read_bytes() for path in originals.iterdir()}
    proof = RUNNER.verify_customer_return_original_rows(private, required_captures=3)
    assert proof["status"] == "passed" and proof["isolated_actual_executions"] == 2
    assert proof["captures"] == 3 and proof["tables_per_capture"] == 13
    assert proof["optimized_result_bytes_equal"] is True and proof["raw_financial_originals_published"] is False
    assert before == {path.name: path.read_bytes() for path in originals.iterdir()}
    assert (private / "independent-customer-return-row-verification/I.json").read_bytes() == (
        private / "independent-customer-return-row-verification/IO.json").read_bytes()


def test_required_financial_row_reader_refuses_incomplete_restore_cohort(tmp_path: Path) -> None:
    private = tmp_path / "private"
    originals = private / "playwright-artifacts/native-customer-return-originals"
    originals.mkdir(parents=True)
    write_capture(originals, rows())
    with pytest.raises(ValueError, match="complete required native cohort"):
        RUNNER.verify_customer_return_original_rows(private, required_captures=3)
    assert (private / "independent-customer-return-row-verification/I.json").is_file()
    assert (private / "independent-customer-return-row-verification/IO.json").is_file()


@pytest.mark.parametrize("drift", ["changed", "missing", "additional", "bool_number", "duplicate_number", "wrong_hash"])
def test_isolated_financial_original_input_seal_refuses_drift_before_diagnostic_publication(tmp_path: Path, drift: str) -> None:
    private = tmp_path / "private"
    originals = private / "playwright-artifacts/native-customer-return-originals"
    originals.mkdir(parents=True)
    write_capture(originals, rows())
    proof = RUNNER.verify_customer_return_original_rows(private, required_captures=1)
    first = originals / "native-financial-snapshot-oracle-1.json"
    if drift == "changed":
        first.write_bytes(b'{"changed_after_isolated_reader":true}')
    elif drift == "missing":
        first.rename(originals / "missing-original.json")
    elif drift == "additional":
        (originals / "unexpected.json").write_bytes(first.read_bytes())
    elif drift == "bool_number":
        proof["input_identities"][0]["number"] = True
    elif drift == "duplicate_number":
        proof["input_identities"][1]["number"] = 1
    else:
        proof["input_identities"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Independent financial original"):
        RUNNER.require_financial_original_binding(private, proof)
    output = tmp_path / "public"
    output.mkdir()
    published = RUNNER.publish_browser_diagnostics(output, private, [], financial_verification=proof)
    assert published["status"] == "quarantined" and RUNNER._public_diagnostic_paths(output) == []
    assert not (output / "playwright-artifacts/native-customer-return-originals").exists()


def test_required_wire_cycle_accepts_one_complete_nonflaky_execution() -> None:
    RUNNER.require_browser_acceptance({"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0, "duration": 100})


@pytest.mark.parametrize("stats", [
    None, {}, {"expected": 0, "skipped": 1, "unexpected": 0, "flaky": 0},
    {"expected": 1, "skipped": 1, "unexpected": 0, "flaky": 0},
    {"expected": 1, "skipped": 0, "unexpected": 1, "flaky": 0},
    {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 1},
    {"expected": True, "skipped": 0, "unexpected": 0, "flaky": 0},
    {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": False},
    {"expected": 2, "skipped": 0, "unexpected": 0, "flaky": 0},
])
def test_required_wire_cycle_refuses_incomplete_execution(stats: Any) -> None:
    with pytest.raises(RuntimeError, match="browser"):
        RUNNER.require_browser_acceptance(stats)


def test_return_wire_gate_requires_business_and_both_language_recovery_cases() -> None:
    complete = {"expected": 3, "skipped": 0, "unexpected": 0, "flaky": 0}
    RUNNER.require_browser_acceptance(complete, required_cases=3)
    with pytest.raises(RuntimeError, match="browser"):
        RUNNER.require_browser_acceptance(complete)
    for expected in (0, 1, 2, 4, True):
        with pytest.raises(RuntimeError, match="browser"):
            RUNNER.require_browser_acceptance({**complete, "expected": expected}, required_cases=3)
    for outcome in ("skipped", "unexpected", "flaky"):
        for value in (1, False):
            with pytest.raises(RuntimeError, match="browser"):
                RUNNER.require_browser_acceptance({**complete, outcome: value}, required_cases=3)


@pytest.mark.parametrize("required", [0, 2, 4, True, 3.0, "3", None])
def test_browser_case_contract_cannot_be_widened_by_an_untyped_count(required: Any) -> None:
    with pytest.raises(RuntimeError, match="browser"):
        RUNNER.require_browser_acceptance({"expected": 3, "skipped": 0, "unexpected": 0, "flaky": 0}, required_cases=required)
