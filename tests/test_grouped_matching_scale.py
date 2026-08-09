from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reconforge.benchmark.grouped_matching_scale import (
    GROUPED_1M_PARTITIONS,
    GROUPED_1M_PROFILE_ID,
    GROUPED_1M_RECORDS,
    GROUPED_10K_PARTITIONS,
    GROUPED_10K_PROFILE_ID,
    GROUPED_10K_RECORDS,
    GROUPED_100K_PARTITIONS,
    GROUPED_100K_PROFILE_ID,
    GROUPED_100K_RECORDS,
    run_grouped_matching_10k,
    verify_grouped_matching_10k,
)


def test_grouped_matching_10k_profile_runs_with_parity_and_permutation_guards() -> None:
    result = run_grouped_matching_10k()
    verify_grouped_matching_10k(result)
    assert result.profile_id == GROUPED_10K_PROFILE_ID
    assert result.partitions == GROUPED_10K_PARTITIONS == 2_500
    assert result.records == GROUPED_10K_RECORDS == 10_000
    assert result.observed_runtime_seconds > 0
    assert result.observed_peak_memory_mb > 0


def test_grouped_matching_10k_structural_digest_is_reproducible() -> None:
    first = run_grouped_matching_10k(permutation_check=False)
    second = run_grouped_matching_10k(permutation_check=False)
    verify_grouped_matching_10k(first)
    verify_grouped_matching_10k(second)
    assert first.effect_digest == second.effect_digest
    assert first.manifest_digest == second.manifest_digest


def test_grouped_matching_10k_distribution_membership_is_explicit() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8").splitlines()
    assert "include reconforge/benchmark/grouped_matching_scale.py" in manifest
    assert "include docs/adr/0230-grouped-matching-10k-is-partitioned-and-bounded.md" in manifest
    assert "include docs/execution/benchmarks/grouped-matching-10k-tier-v1.md" in manifest
    assert "include docs/adr/0231-grouped-matching-100k-is-partitioned-and-bounded.md" in manifest
    assert "include docs/execution/benchmarks/grouped-matching-100k-tier-v1.md" in manifest
    assert "include docs/adr/0232-grouped-matching-1m-is-partitioned-and-bounded.md" in manifest
    assert "include docs/execution/benchmarks/grouped-matching-1m-tier-v1.md" in manifest


def test_grouped_matching_100k_profile_shape_is_declared() -> None:
    assert GROUPED_100K_PROFILE_ID == "grouped-matching/100k-record-true-many-to-many-v1"
    assert GROUPED_100K_PARTITIONS == 25_000
    assert GROUPED_100K_RECORDS == 100_000


def test_grouped_matching_1m_profile_shape_is_declared() -> None:
    assert GROUPED_1M_PROFILE_ID == "grouped-matching/1m-record-true-many-to-many-v1"
    assert GROUPED_1M_PARTITIONS == 250_000
    assert GROUPED_1M_RECORDS == 1_000_000


def test_current_grouped_matching_1m_report_is_digest_bound() -> None:
    report = json.loads(
        Path("docs/execution/benchmarks/grouped-matching-1m-current-2026-08-06.json").read_text(
            encoding="utf-8"
        )
    )
    supplied = str(report.pop("report_digest"))
    canonical = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert report["status"] == "verified"
    assert report["invariants"]["effect_digest_equal"] is True
    assert report["invariants"]["manifest_digest_equal"] is True


def test_current_grouped_matching_100k_report_is_digest_bound() -> None:
    report = json.loads(
        Path("docs/execution/benchmarks/grouped-matching-100k-current-2026-08-08.json").read_text(
            encoding="utf-8"
        )
    )
    supplied = str(report.pop("report_digest"))
    canonical = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert report["status"] == "verified"
    assert report["invariants"]["effect_digest_equal"] is True
    assert report["invariants"]["manifest_digest_equal"] is True
