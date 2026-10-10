"""Adversarial offline tests for the independently executable evidence verifier."""
from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_native_posting_pair.py"
VERIFIER = runpy.run_path(str(SCRIPT))
ERROR = VERIFIER["VerificationError"]


def posting_prefix() -> dict:
    """Only fields needed before read verification, to isolate rejected attacks."""
    return {
        "status": "passed", "source_unchanged": True, "owned_container_removed": True,
        "source_commit": "source", "source_commit_after": "source", "source_sha256": "a" * 64,
        "source_sha256_after": "a" * 64, "profile": "native-three-human-cash-equity-v1",
        "seed": "enterprise-native-v1", "counts": [100, 1000], "workers": 4,
        "repetitions": 3, "max_seconds": 1800, "runtime_role_flags": [False, False],
        "cost_per_transaction": None, "posting_profile": {"enabled": False},
        "postgres_configuration": dict.fromkeys(("fsync", "full_page_writes", "synchronous_commit"), "on"),
        "posting": {"requested_cycles": 1000, "admitted_cycles": 1000, "completed_cycles": 1000,
                    "error_count": 0, "not_admitted_cycles": 0, "failed_cycles": [],
                    "completed_indices": list(range(1000)), "ordered_effect_ids": [f"E-{i}" for i in range(1000)],
                    "expected": dict.fromkeys(("debit_minor", "credit_minor", "cash_minor", "equity_minor"), "493671004"),
                    "seconds": 1000, "native_postings_per_second": 1,
                    "raw_cycle_latency_seconds": [1] * 1000, "cycle_latency_seconds": {"p50": 1, "p95": 1, "p99": 1}},
    }


def test_independent_seed_oracle_matches_retained_integer_golden_totals() -> None:
    assert VERIFIER["minor_oracle"](100) == "46669102"
    assert VERIFIER["minor_oracle"](1000) == "493671004"


@pytest.mark.parametrize("attack", ["money", "indices", "effects", "percentile", "durability"])
def test_forged_complete_financial_evidence_is_rejected(attack: str) -> None:
    report = posting_prefix()
    messages = {"money": "Posting oracle", "indices": "posting index", "effects": "duplicate effect",
                "percentile": "percentile mismatch", "durability": "Durability disabled"}
    if attack == "money":
        report["posting"]["expected"]["cash_minor"] = "493671003"
    elif attack == "indices":
        report["posting"]["completed_indices"][-1] = 998
    elif attack == "effects":
        report["posting"]["ordered_effect_ids"][-1] = "E-0"
    elif attack == "percentile":
        report["posting"]["cycle_latency_seconds"]["p99"] = 2
    else:
        report["postgres_configuration"]["fsync"] = "off"
    with pytest.raises(ERROR, match=messages[attack]):
        VERIFIER["validate_measurement"](report, "source")


def test_modified_hardware_is_not_accepted_as_a_matched_pair() -> None:
    baseline = dict.fromkeys(VERIFIER["CONFIG_FIELDS"], None)
    candidate = {**baseline, "logical_cpus": 8}
    with pytest.raises(ERROR, match="configuration differs: logical_cpus"):
        VERIFIER["compare_configuration"](baseline, candidate)


def test_original_report_reconstruction_rejects_changed_nested_measurement() -> None:
    measurement = {"seed": "enterprise-native-v1"}
    original = (json.dumps(measurement, indent=2) + "\n").replace("\n", "\r\n").encode()
    packet = {"measurement": {"seed": "forged"}, "original_report_sha256": hashlib.sha256(original).hexdigest(),
              "original_report_serialization": {"encoding": "utf-8", "indent": 2, "ensure_ascii": True,
                                                "final_newline": True, "line_endings": "CRLF"}}
    with pytest.raises(ERROR, match="SHA reconstruction"):
        VERIFIER["retained_measurement"](packet)


def test_duplicate_json_keys_cannot_change_verifier_interpretation(tmp_path: Path) -> None:
    packet = tmp_path / "duplicate.json"
    packet.write_text('{"status":"failed","status":"passed"}', encoding="utf-8")
    with pytest.raises(ERROR, match="Duplicate JSON key"):
        VERIFIER["read_json"](packet)


def test_cli_preserves_existing_report_and_guards_survive_optimized_python(tmp_path: Path) -> None:
    report = tmp_path / "retained.json"
    report.write_bytes(b"retained evidence\n")
    result = subprocess.run([sys.executable, "-O", str(SCRIPT), "--root", str(tmp_path), "--report", str(report)],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 1
    assert report.read_bytes() == b"retained evidence\n"
    probe = subprocess.run([sys.executable, "-O", "-c",
                            f"import runpy; runpy.run_path({str(SCRIPT)!r})['require'](False, 'guard active')"],
                           text=True, capture_output=True, check=False)
    assert probe.returncode != 0
    assert "VerificationError: guard active" in probe.stderr
