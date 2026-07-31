import importlib.util
from pathlib import Path

import pytest

from reconforge.upgrade.application_adapter import write_deployment_marker

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_airgap_upgrade_rollback", ROOT / ".github/scripts/verify_airgap_upgrade_rollback.py"
)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def test_airgap_upgrade_rejects_unversioned_wheel_names(tmp_path: Path) -> None:
    source = tmp_path / "source.whl"
    target = tmp_path / "target.whl"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    with pytest.raises(RuntimeError, match="airgap_upgrade_wheel_identity_invalid"):
        PROBE.run_drill(source, target, tmp_path / "work")


def test_deployment_marker_digest_is_stable_and_excludes_marker(tmp_path: Path) -> None:
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    (deployment / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    first = write_deployment_marker(deployment, version="0.7.0", artifact_sha256="a" * 64)
    second = write_deployment_marker(deployment, version="0.7.0", artifact_sha256="a" * 64)
    assert first == second
