"""Build a locked Linux wheel mirror and prove installation with Docker egress disabled."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from verify_application_upgrade import build_tagged_wheel  # noqa: E402

from reconforge.sovereign.offline_bundle import verify_offline_bundle  # noqa: E402

IMAGE = "python:3.14.1-slim"
IMAGE_REFERENCE = f"{IMAGE}@sha256:b823ded4377ebb5ff1af5926702df2284e53cecbc6e3549e93a19d8632a1897e"
APP_VERSION = "0.7.1"
IDENTITY_RECOVERY_PROBE = ROOT / ".github" / "scripts" / "verify_airgap_identity_recovery.py"
UPGRADE_ROLLBACK_PROBE = ROOT / ".github" / "scripts" / "verify_airgap_upgrade_rollback.py"
NORMALIZE_RE = re.compile(r"[-_.]+")


def _run(argv: tuple[str, ...], *, cwd: Path = ROOT, capture: bool = False) -> str:
    completed = subprocess.run(  # nosec B603
        argv,
        cwd=cwd,
        check=True,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    return completed.stdout.strip() if capture else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_identity(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
            ]
            if len(names) != 1:
                raise RuntimeError("airgap_wheel_metadata_count_invalid")
            metadata = Parser().parsestr(archive.read(names[0]).decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise RuntimeError("airgap_wheel_invalid") from exc
    name = str(metadata.get("Name", "")).strip()
    version = str(metadata.get("Version", "")).strip()
    if not name or not version:
        raise RuntimeError("airgap_wheel_identity_missing")
    return name, version


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-wheel", type=Path)
    parser.add_argument("--expected-application-sha256")
    parser.add_argument("--base-install-only", action="store_true")
    args = parser.parse_args()
    if (args.application_wheel is None) != (args.expected_application_sha256 is None):
        raise RuntimeError("airgap_external_wheel_requires_expected_digest")
    container_name = "reconforge-airgap-" + os.urandom(6).hex()
    with tempfile.TemporaryDirectory(prefix="reconforge-airgap-") as temporary:
        workspace = Path(temporary)
        bundle = workspace / "bundle"
        wheelhouse = bundle / "wheelhouse"
        wheelhouse.mkdir(parents=True)
        exported = workspace / "exported-requirements.txt"
        _run(
            (
                "uv", "export", "--locked", "--no-dev", "--extra", "server", "--extra", "backup",
                "--extra", "connectors", "--extra", "federation", "--extra", "mfa",
                "--extra", "observability", "--extra", "duckdb", "--no-emit-project",
                "--format", "requirements-txt", "--output-file", str(exported),
            )
        )
        if args.application_wheel is None:
            distribution = workspace / "distribution"
            distribution.mkdir()
            _run((sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(distribution)))
            wheels = list(distribution.glob(f"reconforge_erp-{APP_VERSION}-*.whl"))
            if len(wheels) != 1:
                raise RuntimeError("airgap_application_wheel_missing")
            application_wheel = wheels[0]
        else:
            application_wheel = args.application_wheel.resolve(strict=True)
            if application_wheel.is_symlink() or not application_wheel.is_file():
                raise RuntimeError("airgap_external_wheel_unsafe")
            if _sha256(application_wheel) != args.expected_application_sha256:
                raise RuntimeError("airgap_external_wheel_digest_mismatch")
            if _wheel_identity(application_wheel) != ("reconforge-erp", APP_VERSION):
                raise RuntimeError("airgap_external_wheel_identity_mismatch")
        shutil.copy2(application_wheel, wheelhouse / application_wheel.name)

        source_upgrade_wheel: Path | None = None
        target_upgrade_wheel: Path | None = None
        if not args.base_install_only:
            upgrade_bundle = workspace / "upgrade-bundle"
            upgrade_bundle.mkdir()
            source_upgrade_wheel = build_tagged_wheel("v0.7.0", upgrade_bundle)
            target_upgrade_wheel = build_tagged_wheel("v0.7.1", upgrade_bundle)

        _run(
            (
                "docker", "run", "--rm", "--mount", f"type=bind,source={workspace.resolve()},target=/work",
                IMAGE_REFERENCE, "python", "-m", "pip", "download", "--require-hashes", "--only-binary=:all:",
                "--dest", "/work/bundle/wheelhouse", "-r", "/work/exported-requirements.txt",
            )
        )

        requirements: list[str] = []
        entries: list[dict[str, object]] = []
        seen: set[str] = set()
        for wheel in sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.lower()):
            name, version = _wheel_identity(wheel)
            normalized = NORMALIZE_RE.sub("-", name).lower()
            if normalized in seen:
                raise RuntimeError("airgap_duplicate_distribution")
            seen.add(normalized)
            digest = _sha256(wheel)
            requirement_name = "reconforge-erp[backup,connectors,duckdb,federation,mfa,observability,server]" if normalized == "reconforge-erp" else name
            requirements.append(f"{requirement_name}=={version} --hash=sha256:{digest}")
            entries.append(
                {
                    "path": f"wheelhouse/{wheel.name}",
                    "role": "application-wheel" if normalized == "reconforge-erp" else "dependency-wheel",
                    "size": wheel.stat().st_size,
                    "sha256": digest,
                }
            )
        lock = bundle / "requirements.lock"
        lock.write_text("\n".join(requirements) + "\n", encoding="utf-8", newline="\n")
        entries.append(
            {"path": "requirements.lock", "role": "requirements-lock", "size": lock.stat().st_size, "sha256": _sha256(lock)}
        )
        manifest_path = bundle / "offline-bundle.v1.json"
        _atomic_json(
            manifest_path,
            {
                "schema": "reconforge-offline-bundle-v1",
                "bundle_id": "reconforge-linux-cp314-071",
                "application_version": APP_VERSION,
                "python_tag": "cp314",
                "platform_tag": "linux_x86_64",
                "install": {
                    "installer": "pip-no-index-v1",
                    "requirements_path": "requirements.lock",
                    "application_requirement": "reconforge-erp[backup,connectors,duckdb,federation,mfa,observability,server]==0.7.1",
                    "network_policy": "deny-all",
                    "index_policy": "no-index",
                },
                "entries": entries,
                "claim_boundary": "Local artifact integrity only; external signature trust, installation success, and production readiness require separate evidence.",
            },
        )
        verified = verify_offline_bundle(manifest_path)
        try:
            docker_argv = [
                "docker", "run", "--name", container_name, "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",  # nosec B108
                "--tmpfs", "/opt/venv:rw,exec,nosuid,size=1024m",
                "--tmpfs", "/work:rw,noexec,nosuid,size=64m", "--workdir", "/work",
                "--mount", f"type=bind,source={bundle.resolve()},target=/bundle,readonly",
            ]
            commands = [
                "python -m venv /opt/venv",
                "/opt/venv/bin/python -m pip install --no-index --disable-pip-version-check --no-deps --find-links /bundle/wheelhouse --require-hashes -r /bundle/requirements.lock",
            ]
            if not args.base_install_only:
                if source_upgrade_wheel is None or target_upgrade_wheel is None:
                    raise RuntimeError("airgap_upgrade_wheels_missing")
                docker_argv.extend(
                    [
                        "--mount", f"type=bind,source={IDENTITY_RECOVERY_PROBE.resolve()},target=/probe.py,readonly",
                        "--mount", f"type=bind,source={UPGRADE_ROLLBACK_PROBE.resolve()},target=/upgrade-probe.py,readonly",
                        "--mount", f"type=bind,source={source_upgrade_wheel.resolve()},target=/upgrade/reconforge_erp-0.7.0-py3-none-any.whl,readonly",
                        "--mount", f"type=bind,source={target_upgrade_wheel.resolve()},target=/upgrade/reconforge_erp-0.7.1-py3-none-any.whl,readonly",
                    ]
                )
                commands.extend(
                    [
                        "/opt/venv/bin/python /probe.py",
                        "/opt/venv/bin/python /upgrade-probe.py --source-wheel /upgrade/reconforge_erp-0.7.0-py3-none-any.whl --target-wheel /upgrade/reconforge_erp-0.7.1-py3-none-any.whl",
                    ]
                )
            commands.append("/opt/venv/bin/reconforge doctor")
            docker_argv.extend((IMAGE_REFERENCE, "sh", "-ec", " && ".join(commands)))
            _run(tuple(docker_argv))
            network_mode = _run(("docker", "inspect", "--format", "{{.HostConfig.NetworkMode}}", container_name), capture=True)
            exit_code = _run(("docker", "inspect", "--format", "{{.State.ExitCode}}", container_name), capture=True)
            if network_mode != "none" or exit_code != "0":
                raise RuntimeError("airgap_container_boundary_failed")
        finally:
            _run(("docker", "rm", "--force", container_name), capture=True)
        print(
            json.dumps(
                {
                    "application_version": verified.application_version,
                    "bundle_manifest_sha256": verified.manifest_sha256,
                    "container_image": IMAGE,
                    "entry_count": verified.entry_count,
                    "network_mode": "none",
                    "offline_install": True,
                    "total_bytes": verified.total_bytes,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
