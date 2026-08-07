"""Small, dependency-free source-mutation campaign for grouped matching."""

from __future__ import annotations

import hashlib
import os
import subprocess  # nosec B404 - closed local pytest command below
import sys
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


_CONTRACT = """\
from datetime import date
from decimal import Decimal

from reconforge.domain.grouped_matching import GroupedMatchPolicy, GroupedRecord, find_grouped_match


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


def _run_contract(root: Path) -> bool:
    command = (sys.executable, "-m", "pytest", "-q", "tests/test_mutation_contract.py")
    environment = {**os.environ, "PYTHONPATH": str(root)}
    completed = subprocess.run(  # nosec B603 - command and cwd are generated locally and shell is disabled
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return completed.returncode == 0


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


def run_source_mutation_campaign() -> SourceMutationResult:
    source_path = Path(__file__).resolve().parents[1] / "domain" / "grouped_matching.py"
    baseline = source_path.read_text(encoding="utf-8")
    baseline_sha256 = hashlib.sha256(baseline.encode("utf-8")).hexdigest()
    survivors: list[str] = []
    for mutation in _MUTATIONS:
        mutated = _replace_occurrence(baseline, mutation.needle, mutation.replacement, mutation.occurrence)
        with TemporaryDirectory(prefix="reconforge-source-mutant-") as directory:
            root = Path(directory)
            _prepare_child(root, mutated)
            if _run_contract(root):
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
