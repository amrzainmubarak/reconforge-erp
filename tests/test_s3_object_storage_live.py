from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "verify_s3_object_storage_live.py"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "s3_object_storage_live_report.schema.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_s3_object_storage_live", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(module: Any) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "report_id": "s3-compatible-object-store-live-v1",
        "status": "verified",
        "provider": "minio",
        "image_digest": "sha256:" + "a" * 64,
        "endpoint": "http://127.0.0.1:19000",
        "bucket_profile": "synthetic-disposable-normal-and-object-lock-buckets",
        "observed": {
            "hierarchical_scope_isolation": True,
            "immutable_conflict_refusal": True,
            "checksum_tamper_refusal": True,
            "object_lock_delete_refusal": True,
            "cleanup": True,
        },
        "elapsed_ms": 1.0,
        "limitations": ["single-node", "synthetic", "no HA"],
    }
    report["report_digest"] = module._canonical_digest(report)
    return report


def test_live_report_schema_and_digest_are_closed() -> None:
    module = _module()
    report = _report(module)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)
    module.verify_report(report)
    tampered = dict(report)
    tampered["observed"] = dict(report["observed"])  # type: ignore[arg-type]
    tampered["observed"]["cleanup"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="invariant"):
        module.verify_report(tampered)


def test_live_report_rejects_credential_fields() -> None:
    module = _module()
    report = _report(module)
    report["secret_reference"] = "must-not-be-recorded"
    report.pop("report_digest")
    report["report_digest"] = module._canonical_digest(report)
    with pytest.raises(ValueError, match="credentials"):
        module.verify_report(report)


def test_ci_has_digest_pinned_live_object_storage_job() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job = workflow["jobs"]["object-storage"]
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
    environments = "\n".join(str(step.get("env", "")) for step in job["steps"])
    uses = "\n".join(str(step.get("uses", "")) for step in job["steps"])
    assert "minio/minio@sha256:13582eff79c6605a2d315bdd0e70164142ea7e98fc8411e9e10d089502a6d883" in environments
    assert "verify_s3_object_storage_live.py" in runs
    assert "tests/test_object_storage_foundation.py -k 'live_s3_'" in runs
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in uses
    assert any(step.get("name") == "Stop MinIO" and step.get("if") == "always()" for step in job["steps"])
