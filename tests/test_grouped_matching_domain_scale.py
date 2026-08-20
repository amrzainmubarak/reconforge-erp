from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from reconforge.benchmark.grouped_matching_domain_scale import (
    DOMAIN_SCALE_MODES,
    DOMAIN_SCALE_PARTITIONS,
    DOMAIN_SCALE_PROFILE_ID,
    DOMAIN_SCALE_RECORDS,
    run_grouped_matching_domain_scale,
    verify_grouped_matching_domain_scale,
)


def test_domain_diverse_profile_declares_10k_six_mode_shape() -> None:
    assert DOMAIN_SCALE_PROFILE_ID == "grouped-matching/10k-domain-diverse-v1"
    assert DOMAIN_SCALE_PARTITIONS == 2_500
    assert DOMAIN_SCALE_RECORDS == 10_000
    assert len(DOMAIN_SCALE_MODES) == 6


def test_domain_diverse_small_profile_preserves_adapter_and_permutation_contracts() -> None:
    result = run_grouped_matching_domain_scale(partitions=30, permutation_stride=1)
    assert result.partitions == 30
    assert result.records == 120
    assert result.matched_partitions == 25
    assert result.ambiguous_partitions == 5
    assert result.unmatched_partitions == 0
    assert result.adapter_mismatches == 0
    assert result.permutation_mismatches == 0
    assert result.mode_counts == {mode: 5 for mode in DOMAIN_SCALE_MODES}
    assert result.decision_digest and result.manifest_digest


def test_domain_diverse_verifier_rejects_non_full_shape() -> None:
    result = run_grouped_matching_domain_scale(partitions=30, permutation_stride=1)
    with pytest.raises(AssertionError, match="shape mismatch"):
        verify_grouped_matching_domain_scale(result)


def test_domain_diverse_benchmark_is_packaged_and_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/grouped_matching_domain_scale.py" in manifest
    assert "include tests/test_grouped_matching_domain_scale.py" in manifest
    assert "include docs/execution/benchmarks/grouped-matching-10k-domain-diverse-v1.json" in manifest
    assert "include docs/schemas/grouped_matching_domain_scale.schema.json" in manifest
    assert (root / "docs/adr/0305-grouped-matching-domain-diverse-scale.md").is_file()
    assert (root / "docs/execution/benchmarks/grouped-matching-10k-domain-diverse-v1.md").is_file()
    assert (root / "docs/execution/benchmarks/grouped-matching-10k-domain-diverse-v1.json").is_file()


def test_published_domain_diverse_artifact_is_schema_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs/schemas/grouped_matching_domain_scale.schema.json").read_text(encoding="utf-8"))
    artifact = json.loads(
        (root / "docs/execution/benchmarks/grouped-matching-10k-domain-diverse-v1.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(artifact)
    assert artifact["matched_partitions"] + artifact["ambiguous_partitions"] == artifact["partitions"]
