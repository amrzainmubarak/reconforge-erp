"""Verify an exact tagged application cutover and rollback from local wheels only."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from reconforge.upgrade.application_adapter import PythonWheelApplicationAdapter, write_deployment_marker
from reconforge.upgrade.orchestrator import UpgradeStep


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _install_source(wheel: Path, target: Path) -> None:
    completed = subprocess.run(  # nosec B603
        (
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--no-index",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError("airgap_upgrade_source_install_failed")


def run_drill(source_wheel: Path, target_wheel: Path, workspace: Path) -> dict[str, object]:
    source = source_wheel.resolve(strict=True)
    target = target_wheel.resolve(strict=True)
    if source.is_symlink() or target.is_symlink() or source.name != "reconforge_erp-0.7.0-py3-none-any.whl" or target.name != "reconforge_erp-0.7.1-py3-none-any.whl":
        raise RuntimeError("airgap_upgrade_wheel_identity_invalid")
    deployment = workspace / "deployment"
    current = deployment / "current"
    current.mkdir(parents=True)
    _install_source(source, current)
    source_artifact = _sha256(source)
    source_content = write_deployment_marker(current, version="0.7.0", artifact_sha256=source_artifact)
    target_artifact = _sha256(target)
    step = UpgradeStep(
        kind="application",
        resource_id="application-main",
        from_version="0.7.0",
        to_version="0.7.1",
        target_sha256=target_artifact,
        rollback_required=True,
        compatibility_reader="wheel-import-v1",
    )
    adapter = PythonWheelApplicationAdapter(
        resource_id="application-main", deployment_root=deployment, wheel_path=target
    )
    evidence = adapter.preflight(step)
    receipt = adapter.apply(step, evidence)
    target_content = adapter.verify(step, receipt)
    restored_content = adapter.rollback(step, receipt)
    if restored_content != source_content:
        raise RuntimeError("airgap_upgrade_rollback_digest_mismatch")
    return {
        "cutover_verified": True,
        "from_version": "0.7.0",
        "network_inputs": 0,
        "rollback_exact": True,
        "rollback_sha256": restored_content,
        "source_wheel_sha256": source_artifact,
        "target_content_sha256": target_content,
        "target_version": "0.7.1",
        "target_wheel_sha256": target_artifact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-wheel", type=Path, required=True)
    parser.add_argument("--target-wheel", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="reconforge-airgap-upgrade-") as directory:
        print(json.dumps(run_drill(args.source_wheel, args.target_wheel, Path(directory)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
