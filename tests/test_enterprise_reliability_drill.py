import importlib.util
import json
from pathlib import Path

import jsonschema


def _script():
    path = Path(".github/scripts/verify_enterprise_reliability.py")
    spec = importlib.util.spec_from_file_location("verify_enterprise_reliability", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reliability_drill_is_closed_and_recovers() -> None:
    report = _script().run_drill()
    assert all(report["checks"].values())
    assert set(report) == {"schema_version", "policy_version", "profile", "failure", "recovery", "checks", "metric_names", "limitations"}
    assert "no_production_slo_claim" in report["limitations"]
    assert "tenant" not in json.dumps(report).lower()


def test_retained_reliability_report_matches_schema_and_runtime() -> None:
    report = json.loads(Path("docs/execution/ENTERPRISE_RELIABILITY_LOCAL_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/enterprise_reliability_drill_report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)
    assert report == _script().run_drill()
