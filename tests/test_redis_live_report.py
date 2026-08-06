from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "verify_redis_live.py"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "redis_live_report.schema.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_redis_live", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(module: Any) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "report_id": "redis-live-session-policy-v1",
        "status": "verified",
        "provider": "redis",
        "image_digest": "sha256:" + "a" * 64,
        "endpoint": "redis://127.0.0.1:6379",
        "observed": {
            "tenant_key_isolation": True,
            "session_raw_token_absent": True,
            "policy_generation_shared": True,
            "policy_cache_cross_process_invalidation": True,
            "cleanup": True,
        },
        "elapsed_ms": 1.0,
        "limitations": ["single-node", "synthetic", "no HA"],
    }
    report["report_digest"] = module._canonical_digest(report)
    return report


def test_live_redis_report_schema_and_digest_are_closed() -> None:
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


def test_ci_uses_digest_pinned_redis_and_uploads_the_live_report() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job = workflow["jobs"]["server-boundaries"]
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
    environments = "\n".join(str(step.get("env", "")) for step in job["steps"])
    assert job["services"]["redis"]["image"] == (
        "redis:7.4-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"
    )
    assert "verify_redis_live.py" in runs
    assert "RECONFORGE_REDIS_IMAGE_DIGEST" in environments
    assert "reconforge-redis-live-report" in "\n".join(str(step.get("with", "")) for step in job["steps"])
    assert any(step.get("name") == "Upload live Redis report" and step.get("if") == "always()" for step in job["steps"])


def test_current_redis_live_report_is_schema_valid_and_digest_bound() -> None:
    module = _module()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for name in (
        "REDIS_LIVE_DOCKER_DRILL_2026-08-05.json",
        "REDIS_LIVE_DOCKER_DRILL_2026-08-06.json",
    ):
        report = json.loads((ROOT / "docs" / "execution" / name).read_text(encoding="utf-8"))
        validator.validate(report)
        module.verify_report(report)
        payload = dict(report)
        supplied = str(payload.pop("report_digest"))
        assert supplied == module._canonical_digest(payload)
        assert all(bool(value) for value in report["observed"].values())


def test_historical_redis_live_report_keeps_v1_observation_compatibility() -> None:
    module = _module()
    historical = json.loads(
        (ROOT / "docs" / "execution" / "REDIS_LIVE_DOCKER_DRILL_2026-08-05.json").read_text(encoding="utf-8")
    )
    assert "policy_cache_cross_process_invalidation" not in historical["observed"]
    module.verify_report(historical)
