from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs/execution/POSTGRES_GOVERNANCE_RUNTIME_E972_2026-08-26.json"
SCHEMA_PATH = ROOT / "docs/schemas/postgres_governance_runtime_report.schema.json"


def test_current_postgres_governance_runtime_report_is_schema_valid_and_digest_bound() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    digest = report["report_digest"]
    unsigned = {key: value for key, value in report.items() if key != "report_digest"}
    expected = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == expected
    assert report["status"] == "passed"
    assert report["migration_head"] == "0092_pg_close_lock_evidence"
    assert report["application_role"]["superuser"] is False
    assert report["application_role"]["bypass_rls"] is False
    assert all(test["passed"] for test in report["tests"].values())
    assert "include docs/execution/POSTGRES_GOVERNANCE_RUNTIME_E972_2026-08-26.json" in (
        ROOT / "MANIFEST.in"
    ).read_text(encoding="utf-8")
    assert "include docs/schemas/postgres_governance_runtime_report.schema.json" in (
        ROOT / "MANIFEST.in"
    ).read_text(encoding="utf-8")
