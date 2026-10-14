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


@pytest.mark.parametrize("captures", [1, 3])
def test_isolated_financial_proofs_and_inputs_remain_private_after_complete_publication(tmp_path: Path, captures: int) -> None:
    """Real isolated stdlib readers over synthetic rows; no database or browser."""
    private = tmp_path / "private"
    originals = private / "playwright-artifacts/native-customer-return-originals"
    originals.mkdir(parents=True)
    for capture in range(1, captures + 1):
        write_capture(originals, rows(), capture)
    input_bytes = {path.name: path.read_bytes() for path in originals.iterdir()}
    verified = RUNNER.verify_customer_return_original_rows(private, required_captures=captures)
    executions = private / "independent-customer-return-row-verification"
    proof_bytes = {name: (executions / name).read_bytes() for name in ("I.json", "IO.json")}
    (private / "browser.log").write_bytes(b"Scoped synthetic reader custody status200\n")
    output = tmp_path / "public"
    output.mkdir()

    published = RUNNER.publish_browser_diagnostics(output, private, [], financial_verification=verified)

    assert published["status"] == "published"
    RUNNER.require_financial_original_binding(private, verified)
    assert input_bytes == {path.name: path.read_bytes() for path in originals.iterdir()}
    assert proof_bytes == {name: (executions / name).read_bytes() for name in proof_bytes}
    assert proof_bytes["I.json"] == proof_bytes["IO.json"]
    assert not (output / "playwright-artifacts/native-customer-return-originals").exists()
    assert not (output / "independent-customer-return-row-verification").exists()
    assert not list(output.rglob("I.json")) and not list(output.rglob("IO.json"))


@pytest.mark.parametrize("name", ["I.json", "IO.json"])
@pytest.mark.parametrize("drift", ["changed", "missing"])
@pytest.mark.parametrize("stage", ["before_publication", "after_public_move"])
def test_isolated_financial_proof_custody_refuses_drift_around_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, drift: str, stage: str,
) -> None:
    private = tmp_path / "private"
    originals = private / "playwright-artifacts/native-customer-return-originals"
    originals.mkdir(parents=True)
    write_capture(originals, rows())
    input_bytes = {path.name: path.read_bytes() for path in originals.iterdir()}
    verified = RUNNER.verify_customer_return_original_rows(private, required_captures=1)
    executions = private / "independent-customer-return-row-verification"
    original_proof = (executions / name).read_bytes()
    (private / "browser.log").write_bytes(b"Scoped synthetic reader custody status200\n")
    output = tmp_path / "public"
    output.mkdir()
    mutated = False

    def mutate_proof() -> None:
        nonlocal mutated
        if drift == "changed":
            (executions / name).write_bytes(b'{"changed_after_isolated_reader":true}\n')
        else:
            (executions / name).rename(executions / ("retained-missing-" + name))
        mutated = True

    if stage == "before_publication":
        mutate_proof()
        with pytest.raises(ValueError):
            RUNNER.require_financial_original_binding(private, verified)
    else:
        original_rename = Path.rename

        def rename_and_drift(path: Path, target: Path) -> Path:
            result = original_rename(path, target)
            if target == output / "browser.log":
                mutate_proof()
            return result

        monkeypatch.setattr(Path, "rename", rename_and_drift)

    published = RUNNER.publish_browser_diagnostics(output, private, [], financial_verification=verified)

    assert mutated, "The intended before/after-publication drift boundary must actually execute."
    assert published["status"] == "quarantined"
    assert RUNNER._public_diagnostic_paths(output) == []
    assert input_bytes == {path.name: path.read_bytes() for path in originals.iterdir()}
    if drift == "missing":
        assert (executions / ("retained-missing-" + name)).read_bytes() == original_proof
        assert not (executions / name).exists()
    else:
        assert (executions / name).read_bytes() != original_proof
    assert not (output / "playwright-artifacts/native-customer-return-originals").exists()
    assert not (output / "independent-customer-return-row-verification").exists()


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
