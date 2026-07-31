import importlib.util
import json
from pathlib import Path

import jsonschema


def _script():
    path = Path(".github/scripts/verify_otlp_http_collector.py")
    spec = importlib.util.spec_from_file_location("verify_otlp_http_collector", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_otlp_collector_drill_matches_closed_retained_report() -> None:
    report = _script().run_drill()
    retained = json.loads(Path("docs/execution/OTLP_HTTP_COLLECTOR_LOCAL_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/otlp_http_collector_drill_report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(retained)
    assert report == retained
    assert all(report["checks"].values())
