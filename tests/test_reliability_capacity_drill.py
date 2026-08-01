import json
from pathlib import Path

import jsonschema


def test_retained_reliability_capacity_drill_is_closed() -> None:
    report = json.loads(Path("docs/execution/RELIABILITY_CAPACITY_LOCAL_DRILL_2026-07-30.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/reliability_capacity_drill_report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)
    assert all(report["checks"].values())
    assert report["measurements"]["requests"] == report["measurements"]["queued_jobs"] == 1000
