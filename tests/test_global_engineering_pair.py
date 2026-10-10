"""Adversarial standalone verification over a retained genuine warmed population."""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("global_pair", ROOT / ".github/scripts/benchmark_global_engineering_pair.py")
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
PACKET = json.loads((ROOT / "tests/fixtures/enterprise-warmup-20-ea83335c.json").read_text())


def verify(packet: dict) -> dict:
    return VERIFIER.verify(packet, Path(PACKET["runtime_root"]).resolve(), PACKET["source_commit"], 20)


def test_real_twenty_cycle_probe_verifies_independently() -> None:
    # Overlapped diagnostic probe, not a quiet 1K acceptance or performance claim.
    result = verify(PACKET)
    assert result["oracle_total_minor"] == "8030262"
    assert result["count"] == 20 and result["container_cpu_seconds"] > 0
    assert result["cost_per_success_currency"] is None


@pytest.mark.parametrize("damage", [
    "extra_effect", "invented_effect", "boolean_index", "missing_prefix", "missing_mode",
    "missing_repetition", "missing_read_effect", "read_failure", "wrong_effect_digest",
    "missing_latency", "wrong_percentile", "wrong_read_median", "wrong_posting_tps",
    "warm_overlap", "warm_index", "warm_missing", "cpu_decrease", "sampler_error",
])
def test_corrupted_populations_and_metrics_are_refused(damage: str) -> None:
    packet = deepcopy(PACKET)
    posting = packet["posting"]
    profile = packet["verified_reads"][0]
    sample = profile["samples"]["bounded_batch"][0]
    warm = packet["posting_warmup"]
    if damage == "extra_effect":
        posting["ordered_effect_ids"].append(posting["ordered_effect_ids"][0])
    elif damage == "invented_effect":
        posting["ordered_effect_ids"][0] = "PST-invented"
    elif damage == "boolean_index":
        posting["completed_indices"][0] = False
    elif damage == "missing_prefix":
        packet["verified_reads"] = []
    elif damage == "missing_mode":
        del profile["samples"]["per_effect_baseline"]
    elif damage == "missing_repetition":
        sample["repetition"] = 1
    elif damage == "missing_read_effect":
        sample["effects"] -= 1
    elif damage == "read_failure":
        sample["error_count"] = 1
    elif damage == "wrong_effect_digest":
        sample["effects_digest"] = "0" * 64
    elif damage == "missing_latency":
        sample["raw_request_latency_seconds"] = []
    elif damage == "wrong_percentile":
        sample["request_latency_seconds"]["p99"] = 0
    elif damage == "wrong_read_median":
        profile["median_seconds_optimized"] = 0
    elif damage == "wrong_posting_tps":
        posting["native_postings_per_second"] *= 10
    elif damage == "warm_overlap":
        warm["effect_ids"][0] = posting["ordered_effect_ids"][0]
    elif damage == "warm_index":
        warm["indices"][0] = 0
    elif damage == "warm_missing":
        warm["raw_cycle_latency_seconds"].pop()
    elif damage == "cpu_decrease":
        packet["posting_container_counters_after"]["parsed"]["cpu_microseconds"]["usage_usec"] = 0
    elif damage == "sampler_error":
        packet["resource_sampling"]["errors"] = ["retained synthetic failure"]
    with pytest.raises(ValueError):
        verify(packet)
