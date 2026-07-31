"""Build tagged wheels and verify the real v0.7.0 -> v0.7.1 cutover contract."""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
from pathlib import Path

from reconforge.upgrade.application_adapter import PythonWheelApplicationAdapter, write_deployment_marker
from reconforge.upgrade.orchestrator import UpgradeStep

ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE_MEMBERS = 20_000
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def _run(argv: tuple[str, ...], *, cwd: Path) -> None:
    completed = subprocess.run(argv, cwd=cwd, shell=False, check=False)  # nosec B603
    if completed.returncode != 0:
        raise RuntimeError(f"verification command failed with exit code {completed.returncode}")


def _extract_tag(tag: str, target: Path) -> None:
    archive = target.parent / f"{tag}.tar"
    _run(("git", "archive", "--format=tar", "--output", str(archive), tag), cwd=ROOT)
    total = 0
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise RuntimeError("tag archive member limit exceeded")
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                raise RuntimeError("tag archive contains an unsafe member")
            destination = target / relative
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise RuntimeError("tag archive contains a special member")
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise RuntimeError("tag archive expanded-size limit exceeded")
            destination.parent.mkdir(parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError("tag archive member is unreadable")
            with destination.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    output.write(chunk)


def build_tagged_wheel(tag: str, workspace: Path) -> Path:
    """Build exactly one wheel from an immutable local Git tag."""
    checkout = workspace / f"source-{tag}"
    checkout.mkdir()
    _extract_tag(tag, checkout)
    output = workspace / f"wheel-{tag}"
    output.mkdir()
    _run((sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output)), cwd=checkout)
    wheels = list(output.glob("reconforge_erp-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("tag build did not produce exactly one ReconForge wheel")
    return wheels[0]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="reconforge-real-upgrade-") as temporary:
        workspace = Path(temporary)
        source_wheel = build_tagged_wheel("v0.7.0", workspace)
        target_wheel = build_tagged_wheel("v0.7.1", workspace)
        deployment = workspace / "deployment"
        current = deployment / "current"
        current.mkdir(parents=True)
        _run(
            (
                sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                "--no-index", "--no-deps", "--target", str(current), str(source_wheel),
            ),
            cwd=ROOT,
        )
        source_artifact = hashlib.sha256(source_wheel.read_bytes()).hexdigest()
        source_content = write_deployment_marker(current, version="0.7.0", artifact_sha256=source_artifact)
        target_artifact = hashlib.sha256(target_wheel.read_bytes()).hexdigest()
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
            resource_id="application-main", deployment_root=deployment, wheel_path=target_wheel
        )
        evidence = adapter.preflight(step)
        receipt = adapter.apply(step, evidence)
        target_content = adapter.verify(step, receipt)
        restored_content = adapter.rollback(step, receipt)
        if restored_content != source_content:
            raise RuntimeError("application rollback did not restore the exact source content digest")
        print(
            json.dumps(
                {
                    "from": "0.7.0",
                    "rollback_sha256": restored_content,
                    "source_wheel_sha256": source_artifact,
                    "target_sha256": target_content,
                    "target_wheel_sha256": target_artifact,
                    "to": "0.7.1",
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
