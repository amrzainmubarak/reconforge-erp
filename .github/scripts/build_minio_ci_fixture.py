"""Build a pinned, archived MinIO source fixture for disposable synthetic CI only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = ROOT / ".github" / "fixtures" / "minio-source"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MANIFEST_FIELDS = frozenset({
    "schema_version", "fixture_id", "scope", "upstream_status", "license", "source_commit",
    "source_release", "source_archive_url", "source_archive_sha256", "builder_image", "go_version",
    "runtime_base", "runtime_user", "runtime_identity_kind",
})


class FixtureBuildError(ValueError):
    """A source, toolchain, runtime identity, or provenance check failed."""


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_manifest(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != MANIFEST_FIELDS:
        raise FixtureBuildError("MinIO fixture manifest fields violate the closed contract")
    expected = {
        "schema_version": 1, "fixture_id": "minio-source-ci-v1", "scope": "synthetic-disposable-ci-only",
        "upstream_status": "archived-unmaintained", "license": "AGPL-3.0-or-later",
        "runtime_base": "scratch", "runtime_user": "65532:65532", "runtime_identity_kind": "oci-config",
    }
    if type(payload["schema_version"]) is not int or any(payload[key] != value for key, value in expected.items()):
        raise FixtureBuildError("MinIO fixture scope, license, or runtime contract is invalid")
    if any(not isinstance(payload[key], str) for key in MANIFEST_FIELDS - {"schema_version"}):
        raise FixtureBuildError("MinIO fixture manifest scalar values are invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", payload["source_commit"]):
        raise FixtureBuildError("MinIO fixture source commit must be immutable")
    if not re.fullmatch(r"[0-9a-f]{64}", payload["source_archive_sha256"]):
        raise FixtureBuildError("MinIO fixture source archive must have an exact SHA256")
    if payload["source_archive_url"] != f"https://codeload.github.com/minio/minio/tar.gz/{payload['source_commit']}":
        raise FixtureBuildError("MinIO fixture source must be the pinned official archive")
    if not re.fullmatch(r"RELEASE\.[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z", payload["source_release"]):
        raise FixtureBuildError("MinIO fixture release identity is invalid")
    if not re.fullmatch(r"go[0-9]+\.[0-9]+\.[0-9]+", payload["go_version"]):
        raise FixtureBuildError("MinIO fixture Go version must be exact")
    image_prefix = f"golang:{payload['go_version'][2:]}-bookworm@sha256:"
    if not payload["builder_image"].startswith(image_prefix) or not re.fullmatch(r"[0-9a-f]{64}", payload["builder_image"][len(image_prefix):]):
        raise FixtureBuildError("MinIO fixture builder must be a digest-pinned official Go image")
    return payload


def verify_archive(path: Path, manifest: dict[str, Any]) -> dict[str, str]:
    if path.stat().st_size > MAX_ARCHIVE_BYTES or _sha256(path) != manifest["source_archive_sha256"]:
        raise FixtureBuildError("MinIO source archive size or SHA256 check failed")
    hashes = {}
    with tarfile.open(path, "r:gz") as archive:
        for name in ("LICENSE", "go.mod", "go.sum"):
            member = archive.getmember(f"minio-{manifest['source_commit']}/{name}")
            if not member.isfile() or member.size > 2 * 1024 * 1024:
                raise FixtureBuildError("MinIO source license or module lock is invalid")
            stream = archive.extractfile(member)
            if stream is None:
                raise FixtureBuildError("MinIO source license or module lock is missing")
            with stream:
                hashes[name] = hashlib.sha256(stream.read()).hexdigest()
    return hashes


def _download(manifest: dict[str, Any], destination: Path) -> None:
    # validate_manifest permits only the fixed official HTTPS codeload path.
    with urlopen(manifest["source_archive_url"], timeout=60) as response, destination.open("wb") as stream:  # nosec B310
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise FixtureBuildError("MinIO source archive exceeded the download size limit")
            stream.write(chunk)


def verify_runtime_identity(image_id: str, version_output: str, manifest: dict[str, Any]) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise FixtureBuildError("Built MinIO image config digest is invalid")
    expected = f"minio version {manifest['source_release']} (commit-id={manifest['source_commit']})"
    if expected not in version_output or f"Runtime: {manifest['go_version']} linux/amd64" not in version_output:
        raise FixtureBuildError("Built MinIO version, commit, or Go runtime differs from the fixture manifest")


def build_fixture(output: Path, iidfile: Path, *, source_archive: Path | None = None) -> dict[str, object]:
    manifest_path = FIXTURE_DIRECTORY / "fixture.v1.json"
    recipe = FIXTURE_DIRECTORY / "Dockerfile"
    manifest_bytes = manifest_path.read_bytes()
    recipe_bytes = recipe.read_bytes()
    manifest = validate_manifest(json.loads(manifest_bytes))
    if f"FROM {manifest['builder_image']} AS build" not in recipe_bytes.decode("utf-8"):
        raise FixtureBuildError("MinIO fixture recipe builder differs from the manifest")
    output.parent.mkdir(parents=True, exist_ok=True)
    iidfile.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="reconforge-minio-ci-") as temporary:
        context = Path(temporary)
        archive = context / "minio-source.tar.gz"
        if source_archive is None:
            _download(manifest, archive)
        else:
            verify_archive(source_archive, manifest)
            shutil.copyfile(source_archive, archive)
        source_hashes = verify_archive(archive, manifest)
        (context / "Dockerfile").write_bytes(recipe_bytes)
        subprocess.run([
            "docker", "build", "--platform", "linux/amd64", "--progress", "plain",
            "--tag", f"reconforge-minio-ci:{manifest['source_commit'][:12]}", "--iidfile", str(iidfile.resolve()),
            "--build-arg", f"MINIO_SOURCE_SHA256={manifest['source_archive_sha256']}",
            "--build-arg", f"MINIO_COMMIT={manifest['source_commit']}",
            "--build-arg", f"MINIO_RELEASE={manifest['source_release']}",
            "--build-arg", f"MINIO_GO_VERSION={manifest['go_version']}", str(context),
        ], check=True, timeout=1800)
    image_id = iidfile.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise FixtureBuildError("Built MinIO image config digest is invalid")
    version = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image_id, "--version"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    verify_runtime_identity(image_id, version, manifest)
    report: dict[str, object] = {
        "schema_version": 1, "fixture_id": manifest["fixture_id"], "scope": manifest["scope"],
        "upstream_status": manifest["upstream_status"], "license": manifest["license"],
        "source_commit": manifest["source_commit"], "source_release": manifest["source_release"],
        "source_archive_url": manifest["source_archive_url"], "source_archive_sha256": manifest["source_archive_sha256"],
        "source_file_sha256": source_hashes, "builder_image": manifest["builder_image"],
        "runtime_base": manifest["runtime_base"], "image_config_digest": image_id,
        "image_digest_kind": "oci-config", "version_output": version,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest(),
        "limitations": ["archived and unmaintained upstream; synthetic CI fixture only", "not a supported production provider or shipped ReconForge image"],
    }
    report["report_digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iidfile", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, help="Previously downloaded official archive; the pinned checksum is still required")
    args = parser.parse_args()
    build_fixture(args.output, args.iidfile, source_archive=args.source_archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
