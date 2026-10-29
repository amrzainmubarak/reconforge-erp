"""Small, dependency-free source-mutation campaign for grouped matching."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess  # nosec B404 - closed local pytest command below
import sys
import xml.etree.ElementTree as ET  # nosec B405 - pytest generates this local report
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class SourceMutation:
    name: str
    needle: str
    replacement: str
    occurrence: int = 1


@dataclass(frozen=True)
class SourceMutationResult:
    campaign_id: str
    mutants: int
    killed: int
    survivors: tuple[str, ...]
    baseline_sha256: str

    @property
    def kill_ratio(self) -> float:
        return self.killed / self.mutants if self.mutants else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "mutants": self.mutants,
            "killed": self.killed,
            "survivors": list(self.survivors),
            "baseline_sha256": self.baseline_sha256,
            "limitations": [
                "Targeted source mutations only; this is not a domain-wide mutation score.",
                "The child contract is synthetic and in-process; PostgreSQL parity and distributed faults remain open.",
            ],
        }


_MUTATIONS = (
    SourceMutation(
        "partial_settlement_disabled",
        "                    if exact or partial:\n",
        "                    if exact:\n",
    ),
    SourceMutation(
        "date_window_boundary_inclusive",
        "                    if date_span > policy.date_window_days:\n",
        "                    if date_span >= policy.date_window_days:\n",
    ),
    SourceMutation(
        "signed_difference_without_absolute",
        "                    difference = abs(left_net_total - right_net_total)\n",
        "                    difference = left_net_total - right_net_total\n",
    ),
)

# Expected failures are part of the synthetic mutation contract.  The date
# mutation also breaks partial settlement because its window is zero days.
_EXPECTED_FAILURES = {
    "partial_settlement_disabled": ("test_partial_settlement_is_supported",),
    "date_window_boundary_inclusive": (
        "test_date_window_includes_the_declared_boundary", "test_partial_settlement_is_supported",
    ),
    "signed_difference_without_absolute": ("test_mismatched_group_is_not_accepted_as_exact",),
}
_EXPECTED_ASSERTIONS = {
    "test_partial_settlement_is_supported": 'assert result.status == "matched"',
    "test_date_window_includes_the_declared_boundary": 'assert result.status == "matched"',
    "test_mismatched_group_is_not_accepted_as_exact": 'assert result.status == "unmatched"',
}


_CONTRACT = """\
from datetime import date
from decimal import Decimal
from pathlib import Path

import reconforge.domain.grouped_matching as grouped_matching
from reconforge.domain.grouped_matching import GroupedMatchPolicy, GroupedRecord, find_grouped_match


def test_contract_imports_the_isolated_source() -> None:
    expected = Path(__file__).resolve().parents[1] / "reconforge" / "domain" / "grouped_matching.py"
    assert Path(grouped_matching.__file__).resolve() == expected.resolve()


def record(record_id: str, amount: str, day: int = 1) -> GroupedRecord:
    return GroupedRecord(
        record_id=record_id,
        amount=Decimal(amount),
        fee=Decimal("0"),
        currency="USD",
        business_date=date(2026, 8, day),
        partition_key="P",
    )


def test_partial_settlement_is_supported() -> None:
    result = find_grouped_match(
        (record("L1", "100"),),
        (record("R1", "80"),),
        GroupedMatchPolicy(mode="partial-settlement"),
    )
    assert result.status == "matched"
    assert result.reason_code == "PARTIAL_SETTLEMENT_PROPOSAL"
    assert result.settled_amount == Decimal("80")


def test_date_window_includes_the_declared_boundary() -> None:
    result = find_grouped_match(
        (record("L1", "50", 1), record("L2", "50", 2)),
        (record("R1", "50", 1), record("R2", "50", 2)),
        GroupedMatchPolicy(mode="many-to-many", max_left_cardinality=2, max_right_cardinality=2, date_window_days=1),
    )
    assert result.status == "matched"
    assert result.amount_difference == Decimal("0")


def test_mismatched_group_is_not_accepted_as_exact() -> None:
    result = find_grouped_match(
        (record("L1", "45"), record("L2", "45")),
        (record("R1", "60"), record("R2", "40")),
        GroupedMatchPolicy(mode="many-to-many", max_left_cardinality=2, max_right_cardinality=2),
    )
    assert result.status == "unmatched"
    assert result.left_record_ids == result.right_record_ids == ()
"""


def _replace_occurrence(source: str, needle: str, replacement: str, occurrence: int) -> str:
    if occurrence < 1:
        raise AssertionError("mutation occurrence must be positive")
    offset = 0
    position = -1
    for _ in range(occurrence):
        position = source.find(needle, offset)
        if position < 0:
            raise AssertionError("mutation needle occurrence is missing")
        offset = position + len(needle)
    return source[:position] + replacement + source[position + len(needle) :]


def _run_contract(root: Path, expected_failure: tuple[str, ...] = ()) -> bool:
    report = root / "contract-results.xml"
    command = (
        sys.executable, "-m", "pytest", "-q", "-c", str(root / "pytest.ini"),
        "--junitxml", str(report), "tests/test_mutation_contract.py",
    )
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""}
    environment.pop("PYTEST_PLUGINS", None)
    completed = subprocess.run(  # nosec B603 - command and cwd are generated locally and shell is disabled
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    try:
        suites = ET.parse(report).getroot()  # nosec B314 - report is generated by this local pytest child
        suite = suites if suites.tag == "testsuite" else suites.find("testsuite")
        if suite is None:
            raise ValueError("missing suite")
        tests = int(suite.attrib["tests"])
        failures = int(suite.attrib["failures"])
        errors = int(suite.attrib["errors"])
        skipped = int(suite.attrib["skipped"])
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        raise RuntimeError("mutation contract did not produce a valid test report") from exc
    if tests != 4 or errors or skipped or completed.returncode not in (0, 1):
        raise RuntimeError("mutation contract did not execute all required tests cleanly")
    cases = suite.findall("testcase")
    expected_names = {
        "test_contract_imports_the_isolated_source",
        "test_partial_settlement_is_supported",
        "test_date_window_includes_the_declared_boundary",
        "test_mismatched_group_is_not_accepted_as_exact",
    }
    if len(cases) != len(expected_names) or {case.get("name") for case in cases} != expected_names:
        raise RuntimeError("mutation contract did not run the expected tests")
    origin = next(case for case in cases if case.get("name") == "test_contract_imports_the_isolated_source")
    if len(origin):
        raise RuntimeError("mutation contract source origin verification failed")
    if completed.returncode != (1 if failures else 0):
        raise RuntimeError("mutation contract exit status disagrees with its report")
    failing_cases = [case for case in cases if case.find("failure") is not None]
    if len(failing_cases) != failures:
        raise RuntimeError("mutation contract report has inconsistent failure counts")
    if failures:
        names = {case.get("name") for case in failing_cases}
        if not expected_failure or expected_failure[0] not in names or not names.issubset(expected_failure):
            raise RuntimeError("unexpected mutation contract failure")
        for case in failing_cases:
            failure = case.find("failure")
            if failure is None or not (failure.get("message") or "").startswith("AssertionError:"):
                raise RuntimeError("unexpected mutation contract failure type")
            trace = (failure.text or "").strip()
            expected_assertion = _EXPECTED_ASSERTIONS.get(case.get("name", ""))
            if (
                expected_assertion is None
                or f">       {expected_assertion}" not in trace
                or not re.search(r"tests[\\/]test_mutation_contract\.py:\d+: AssertionError$", trace)
            ):
                raise RuntimeError("unexpected mutation contract failure location")
    return failures == 0


def _prepare_child(root: Path, source: str) -> None:
    package = root / "reconforge"
    domain = package / "domain"
    tests = root / "tests"
    domain.mkdir(parents=True)
    tests.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (domain / "__init__.py").write_text("", encoding="utf-8")
    (domain / "grouped_matching.py").write_text(source, encoding="utf-8")
    (tests / "test_mutation_contract.py").write_text(_CONTRACT, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def run_source_mutation_campaign() -> SourceMutationResult:
    source_path = Path(__file__).resolve().parents[1] / "domain" / "grouped_matching.py"
    baseline = source_path.read_text(encoding="utf-8")
    baseline_sha256 = hashlib.sha256(baseline.encode("utf-8")).hexdigest()
    survivors: list[str] = []
    with TemporaryDirectory(prefix="reconforge-source-baseline-") as directory:
        root = Path(directory)
        _prepare_child(root, baseline)
        try:
            baseline_passed = _run_contract(root)
        except RuntimeError as exc:
            raise RuntimeError("mutation baseline contract could not be verified") from exc
        if not baseline_passed:
            raise RuntimeError("mutation baseline contract failed")
    for mutation in _MUTATIONS:
        mutated = _replace_occurrence(baseline, mutation.needle, mutation.replacement, mutation.occurrence)
        with TemporaryDirectory(prefix="reconforge-source-mutant-") as directory:
            root = Path(directory)
            _prepare_child(root, mutated)
            if _run_contract(root, _EXPECTED_FAILURES[mutation.name]):
                survivors.append(mutation.name)
    return SourceMutationResult(
        campaign_id="grouped-matching-source-mutation/targeted-v1",
        mutants=len(_MUTATIONS),
        killed=len(_MUTATIONS) - len(survivors),
        survivors=tuple(survivors),
        baseline_sha256=baseline_sha256,
    )


def verify_source_mutation_campaign(result: SourceMutationResult) -> None:
    if result.mutants != len(_MUTATIONS) or result.killed != result.mutants or result.survivors:
        raise AssertionError("targeted grouped-matching source mutant survived")
