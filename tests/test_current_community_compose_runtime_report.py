from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs/execution/COMMUNITY_COMPOSE_RUNTIME_E974_2026-08-26.json"
SCHEMA_PATH = ROOT / "docs/schemas/community_compose_runtime_report.schema.json"


def test_current_community_compose_runtime_report_is_schema_valid_and_digest_bound() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    unsigned = {key: value for key, value in report.items() if key != "report_digest"}
    expected = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert report["report_digest"] == expected
    assert report["status"] == "passed"
    assert report["runtime"]["health_after_restart"] == "healthy"
    assert report["database"]["schema_version"] == 46
    assert report["backup_restore"]["restored_schema_version"] == 46
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/execution/COMMUNITY_COMPOSE_RUNTIME_E974_2026-08-26.json" in manifest
    assert "include docs/schemas/community_compose_runtime_report.schema.json" in manifest
