import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def test_current_s3_object_storage_live_report_is_schema_valid_and_digest_bound() -> None:
    report = json.loads(
        (ROOT / "docs/execution/S3_OBJECT_STORAGE_LIVE_DOCKER_DRILL_2026-08-05.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/s3_object_storage_live_report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(report)
    payload = dict(report)
    supplied = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert all(bool(value) for value in report["observed"].values())
