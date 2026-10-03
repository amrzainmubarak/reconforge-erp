from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
from decimal import localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from reconforge.benchmark.amlsim_reconciliation import (
    AMLSimProfile,
    AMLSimWorkloadError,
    canonical_digest,
    load_amlsim_profile,
    parse_amlsim_sample,
    run_amlsim_reconciliation,
)
from reconforge.reconciliation.deterministic_engine import DeterministicMatchingEngine

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/amlsim/tx.csv"
PROFILE = ROOT / "docs/validation/amlsim-workload.v1.yaml"


def changed_source(**fields: str) -> tuple[bytes, AMLSimProfile]:
    profile = load_amlsim_profile(PROFILE)
    rows = list(csv.DictReader(io.StringIO(SOURCE.read_text(encoding="utf-8"))))
    rows[0].update(fields)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    content = output.getvalue().encode()
    return content, profile.model_copy(update={"input_sha256": hashlib.sha256(content).hexdigest()})


def test_pinned_upstream_bytes_license_and_explicit_projection() -> None:
    profile = load_amlsim_profile(PROFILE)
    records = parse_amlsim_sample(SOURCE.read_bytes(), profile)
    assert len(records) == 45
    assert records[0] == {"source_id": "2", "reference": "AMLSIM-2", "account": "15", "counterparty": "25", "transfer_type": "CHECK", "source_step": "1", "amount": "125.05", "currency": "USD", "date": "2000-01-02"}
    assert hashlib.sha256((SOURCE.parent / "LICENSE").read_bytes()).hexdigest() == "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"


def test_real_upstream_sample_matches_independent_fault_oracle() -> None:
    profile = load_amlsim_profile(PROFILE)
    report = run_amlsim_reconciliation(SOURCE.read_bytes(), profile)
    assert report["input_records"] == report["left_records"] == report["right_records"] == 45
    assert report["matched_pairs"] == 42
    assert report["unmatched_left"] == report["unmatched_right"] == 3
    assert report["result_statuses"] == {"Matched": 42, "Unmatched": 6}
    assert report["seeded_faults"] == {"missing": 1, "amount_changed": 1, "duplicate": 1, "delayed": 1}
    assert report["oracle_passed"] is True and report["permutation_equal"] is True
    assert run_amlsim_reconciliation(SOURCE.read_bytes(), profile) == report


def test_oracle_rejects_the_legacy_scored_policy_that_accepts_seeded_variances(monkeypatch: pytest.MonkeyPatch) -> None:
    real_match = DeterministicMatchingEngine.match_records

    def use_legacy(self: DeterministicMatchingEngine, **kwargs: object) -> object:
        kwargs.pop("constraint_policy")
        return real_match(self, **kwargs)

    monkeypatch.setattr(DeterministicMatchingEngine, "match_records", use_legacy)
    with pytest.raises(AMLSimWorkloadError, match="independent fault oracle"):
        run_amlsim_reconciliation(SOURCE.read_bytes(), load_amlsim_profile(PROFILE))


def test_exact_amounts_ignore_ambient_decimal_precision() -> None:
    content, profile = changed_source(TXN_AMOUNT_ORIG="90071992547409931234567890.01")
    expected = run_amlsim_reconciliation(content, profile)
    with localcontext() as context:
        context.prec = 4
        records = parse_amlsim_sample(content, profile)
        assert records[0]["amount"] == "90071992547409931234567890.01"
        assert run_amlsim_reconciliation(content, profile) == expected


def test_row_permutation_changes_source_receipt_but_not_decisions() -> None:
    profile = load_amlsim_profile(PROFILE)
    original = SOURCE.read_bytes()
    lines = original.splitlines()
    reversed_rows = b"\n".join([lines[0], *reversed(lines[1:])]) + b"\n"
    reordered = run_amlsim_reconciliation(reversed_rows, profile.model_copy(update={"input_sha256": hashlib.sha256(reversed_rows).hexdigest()}))
    expected = run_amlsim_reconciliation(original, profile)
    assert reordered["decision_digest"] == expected["decision_digest"]
    assert reordered["canonical_source_digest"] == expected["canonical_source_digest"]
    assert reordered["source"]["sha256"] != expected["source"]["sha256"]


@pytest.mark.parametrize(("currency", "scale"), [("JPY", 0), ("KWD", 3), ("CLF", 4)])
def test_assigned_currency_scale_is_explicit_and_not_fixed_to_two_places(currency: str, scale: int) -> None:
    profile = load_amlsim_profile(PROFILE)
    rows = list(csv.DictReader(io.StringIO(SOURCE.read_text(encoding="utf-8"))))
    for row in rows:
        row["TXN_AMOUNT_ORIG"] = row["TXN_AMOUNT_ORIG"].split(".")[0]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    content = output.getvalue().encode()
    assigned = profile.model_copy(update={"input_sha256": hashlib.sha256(content).hexdigest(), "assigned_currency": currency, "assigned_minor_units": scale})
    report = run_amlsim_reconciliation(content, assigned)
    assert report["matched_pairs"] == 42
    first = parse_amlsim_sample(content, assigned)[0]
    assert first["amount"] == ("125" if scale == 0 else "125." + "0" * scale)
    assert first["currency"] == currency


@pytest.mark.parametrize("fields", [
    {"TXN_AMOUNT_ORIG": "NaN"}, {"TXN_AMOUNT_ORIG": "Infinity"}, {"TXN_AMOUNT_ORIG": "1e2"},
    {"TXN_AMOUNT_ORIG": "1.001"}, {"TXN_AMOUNT_ORIG": " 1.00"}, {"TXN_AMOUNT_ORIG": "-1"},
    {"TXN_ID": "4"}, {"TXN_ID": ""}, {"TXN_ID": "2\n"}, {"ACCOUNT_ID": "1.2"},
    {"tx_count": "2"}, {"end": "2"}, {"start": "999999999999999999", "end": "999999999999999999"},
    {"TXN_SOURCE_TYPE_CODE": "=formula"},
])
def test_invalid_source_is_rejected_not_coerced(fields: dict[str, str]) -> None:
    content, profile = changed_source(**fields)
    with pytest.raises(AMLSimWorkloadError):
        parse_amlsim_sample(content, profile)


def test_integrity_schema_and_row_boundaries_fail_closed() -> None:
    profile = load_amlsim_profile(PROFILE)
    content = SOURCE.read_bytes()
    with pytest.raises(AMLSimWorkloadError, match="SHA-256"):
        parse_amlsim_sample(content + b"\n", profile)
    for bad in (content.replace(b"TXN_ID", b"ID", 1), content + content.splitlines()[1] + b"\n", content.replace(b",125.05,1,1", b",125.05,1", 1), b"\xff", content + b"\x00"):
        with pytest.raises(AMLSimWorkloadError):
            parse_amlsim_sample(bad, profile.model_copy(update={"input_sha256": hashlib.sha256(bad).hexdigest()}))
    with pytest.raises(AMLSimWorkloadError, match="byte boundary"):
        parse_amlsim_sample(content, profile.model_copy(update={"max_bytes": 10}))


def test_manifest_rejects_implicit_currency_unknown_fields_and_overlapping_faults() -> None:
    original = load_amlsim_profile(PROFILE).model_dump(mode="json")
    for change in ({"assigned_currency": "usd"}, {"assigned_minor_units": True}, {"unknown": 1}, {"upstream_commit": "main"}, {"faults": {**original["faults"], "missing_id": "4"}}):
        with pytest.raises(ValidationError):
            AMLSimProfile.model_validate({**original, **change})
    original.pop("assigned_currency")
    with pytest.raises(ValidationError):
        AMLSimProfile.model_validate(original)


def test_offline_runner_emits_digest_bound_report(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(ROOT / ".github/scripts/verify_amlsim_reconciliation.py"), "--output", str(target)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(target.read_text(encoding="utf-8"))
    supplied = report.pop("report_digest")
    assert supplied == canonical_digest(report)
    assert report["execution"]["network_calls"] == 0
    assert report["execution"]["python_peak_allocated_bytes"] > 0
    assert report["matched_pairs"] == 42


def test_retained_sample_evidence_binds_verified_source_and_decisions() -> None:
    report = json.loads((ROOT / "docs/execution/OPEN_SOURCE_AMLSIM_2026-10-03.json").read_text(encoding="utf-8"))
    supplied = report.pop("report_digest")
    assert supplied == canonical_digest(report)
    for path, expected in report["execution"]["source_files"].items():
        canonical = (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        assert hashlib.sha256(canonical).hexdigest() == expected
    live = run_amlsim_reconciliation(SOURCE.read_bytes(), load_amlsim_profile(PROFILE))
    assert {key: value for key, value in report.items() if key != "execution"} == live
