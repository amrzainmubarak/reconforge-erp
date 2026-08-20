from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reconforge.benchmark.sequential_matching_scale import (
    SEQUENTIAL_1M_PARTITIONS,
    SEQUENTIAL_1M_PROFILE_ID,
    SEQUENTIAL_1M_RECORDS,
    SEQUENTIAL_10K_PARTITIONS,
    SEQUENTIAL_10K_PROFILE_ID,
    SEQUENTIAL_10K_RECORDS,
    SEQUENTIAL_100K_PARTITIONS,
    SEQUENTIAL_100K_PROFILE_ID,
    SEQUENTIAL_100K_RECORDS,
    run_sequential_matching_10k,
    verify_sequential_matching_10k,
)


def test_sequential_matching_10k_profile_has_parity_permutation_and_mutation_guards() -> None:
    result = run_sequential_matching_10k()
    verify_sequential_matching_10k(result)
    assert result.profile_id == SEQUENTIAL_10K_PROFILE_ID
    assert result.partitions == SEQUENTIAL_10K_PARTITIONS
    assert result.records == SEQUENTIAL_10K_RECORDS == 10_000
    assert result.cross_engine_checks == SEQUENTIAL_10K_PARTITIONS
    assert result.cross_engine_mismatches == 0
    assert result.permutation_mismatches == 0
    assert result.mutation_guard_passed is True
    assert result.observed_runtime_seconds > 0
    assert result.observed_peak_memory_mb > 0


def test_sequential_matching_10k_structural_digest_is_reproducible() -> None:
    first = run_sequential_matching_10k(parity_check=False)
    second = run_sequential_matching_10k(parity_check=False)
    verify_sequential_matching_10k(first)
    verify_sequential_matching_10k(second)
    assert first.effect_digest == second.effect_digest
    assert first.manifest_digest == second.manifest_digest


def test_sequential_matching_scale_shapes_are_declared() -> None:
    assert SEQUENTIAL_100K_PROFILE_ID == "sequential-matching/100k-record-partitioned-v1"
    assert SEQUENTIAL_100K_PARTITIONS == 100_000 // 5
    assert SEQUENTIAL_100K_RECORDS == 100_000
    assert SEQUENTIAL_1M_PROFILE_ID == "sequential-matching/1m-record-partitioned-v1"
    assert SEQUENTIAL_1M_PARTITIONS == 1_000_000 // 5
    assert SEQUENTIAL_1M_RECORDS == 1_000_000


def test_sequential_matching_scale_distribution_membership_is_explicit() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8").splitlines()
    expected = {
        "include reconforge/benchmark/sequential_matching_scale.py",
        "include tests/test_sequential_matching_scale.py",
        "include docs/adr/0462-sequential-matching-scale-profiles.md",
        "include docs/execution/benchmarks/sequential-matching-10k-tier-v1.md",
        "include docs/execution/benchmarks/sequential-matching-100k-tier-v1.md",
        "include docs/execution/benchmarks/sequential-matching-1m-tier-v1.md",
        "include docs/execution/benchmarks/sequential-matching-10k-current-2026-08-09.json",
        "include docs/execution/benchmarks/sequential-matching-100k-current-2026-08-09.json",
        "include docs/execution/benchmarks/sequential-matching-1m-current-2026-08-09.json",
    }
    assert expected.issubset(set(manifest))


def test_sequential_matching_current_reports_are_digest_bound() -> None:
    for filename in (
        "sequential-matching-10k-current-2026-08-09.json",
        "sequential-matching-100k-current-2026-08-09.json",
        "sequential-matching-1m-current-2026-08-09.json",
    ):
        report = json.loads(Path("docs/execution/benchmarks", filename).read_text(encoding="utf-8"))
        supplied = str(report.pop("report_digest"))
        canonical = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert supplied == hashlib.sha256(canonical).hexdigest()
        assert report["status"] == "verified"
        assert report["invariants"]["cross_engine_mismatches"] == 0
        assert report["invariants"]["permutation_mismatches"] == 0
