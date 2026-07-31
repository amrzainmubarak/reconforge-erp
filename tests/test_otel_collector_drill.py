import json
from pathlib import Path

import jsonschema


def test_retained_otel_collector_drill_is_closed() -> None:
    report = json.loads(Path("docs/execution/OTEL_COLLECTOR_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/otel_collector_drill_report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)
    assert all(report["checks"].values())
    assert report["backend"]["bytes"] > 0
