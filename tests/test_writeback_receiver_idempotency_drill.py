from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs/execution/WRITEBACK_RECEIVER_IDEMPOTENCY_DRILL_2026-08-22.json"
SCHEMA_PATH = ROOT / "docs/schemas/writeback_receiver_idempotency_drill.schema.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_writeback_receiver_idempotency.py"
RECEIVER_PATH = ROOT / "reconforge/connectors/writeback_receiver.py"


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _report() -> dict[str, object]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_retained_receiver_drill_is_closed_digest_bound_and_source_bound() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)

    payload = dict(report)
    supplied = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert datetime.fromisoformat(str(report["executed_at"])).tzinfo is UTC

    subject = report["subject"]
    assert isinstance(subject, dict)
    assert subject["receiver_source_sha256"] == _source_digest(RECEIVER_PATH)
    assert subject["runner_source_sha256"] == _source_digest(RUNNER_PATH)
    subprocess.run(
        ("git", "cat-file", "-e", f"{subject['base_commit']}^{{commit}}"),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_receiver_drill_proves_one_effect_conflict_refusal_crash_replay_and_restore() -> None:
    report = _report()
    cases = report["cases"]
    history = report["history"]
    checks = report["checks"]
    assert isinstance(cases, dict)
    assert isinstance(history, dict)
    assert isinstance(checks, dict)
    assert cases["concurrent"]["applied"] == 1
    assert cases["concurrent"]["replayed"] == 7
    assert cases["crash_after_commit"]["retry_disposition"] == "replayed"
    assert history["receipts"] == history["effects"] == 3
    assert history["canonical_sha256"] == history["restored_canonical_sha256"]
    assert all(checks.values())
    assert len({case["request_digest"] for case in cases.values()}) == 3
    assert len({case["response_digest"] for case in cases.values()}) == 3


def test_receiver_drill_assets_are_packaged_and_report_is_secret_payload_free() -> None:
    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include reconforge/connectors/writeback_receiver.py",
        "include .github/scripts/verify_writeback_receiver_idempotency.py",
        "include docs/execution/WRITEBACK_RECEIVER_IDEMPOTENCY_DRILL_2026-08-22.json",
        "include docs/schemas/writeback_receiver_idempotency_drill.schema.json",
        "include tests/test_connector_writeback_receiver.py",
        "include tests/test_writeback_receiver_idempotency_drill.py",
        "include docs/adr/0542-prove-bounded-writeback-receiver-idempotency.md",
    } <= manifest
    raw = REPORT_PATH.read_text(encoding="utf-8")
    assert "Authorization" not in raw
    assert "credential" not in raw
    assert '"amount"' not in raw


def test_ci_runs_and_preserves_receiver_drill_before_broader_live_boundaries() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    run_index = names.index("Run write-back receiver idempotency drill")
    upload_index = names.index("Upload write-back receiver idempotency drill")
    live_index = names.index("Run live server-boundary tests")
    assert run_index < upload_index < live_index
    run_step = steps[run_index]
    assert run_step["env"]["RECONFORGE_WRITEBACK_RECEIVER_REPORT"] == (
        "${{ runner.temp }}/reconforge-writeback-receiver-idempotency.json"
    )
    assert str(run_step["run"]).strip() == (
        "uv run --no-sync python .github/scripts/verify_writeback_receiver_idempotency.py "
        '--output "${RECONFORGE_WRITEBACK_RECEIVER_REPORT}"'
    )
    upload = steps[upload_index]
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload["with"]["if-no-files-found"] == "ignore"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda report: report["checks"].update(one_concurrent_effect=False), "checks.one_concurrent_effect"),
        (lambda report: report["cases"]["concurrent"].update(applied=2), "cases.concurrent.applied"),
        (lambda report: report["history"].update(effects=4), "history.effects"),
        (lambda report: report.update(undeclared=True), ""),
    ),
)
def test_receiver_drill_schema_refuses_false_drifted_or_undeclared_evidence(
    mutation: object, expected_path: str
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    assert callable(mutation)
    mutation(report)
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
    assert errors
    paths = {".".join(str(part) for part in error.path) for error in errors}
    assert expected_path in paths
