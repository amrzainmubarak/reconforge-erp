"""Build a deterministic, evidence-bounded release-candidate manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_DISTRIBUTION = "reconforge-erp"
ARCHIVE_DISTRIBUTION = "reconforge_erp"
SOURCE_REPOSITORY = "https://github.com/amrzainmubarak/reconforge-erp"
WORKFLOW_IDENTITY = "amrzainmubarak/reconforge-erp/.github/workflows/release.yml"
IMAGE_REPOSITORY = "ghcr.io/amrzainmubarak/reconforge-erp"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
MAX_SOURCE_DATE_EPOCH = (1 << 32) - 1


class ReleaseManifestError(ValueError):
    """Raised when release-candidate identity cannot be proven locally."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _metadata_identity(raw: bytes, *, source: str) -> tuple[str, str]:
    try:
        metadata = Parser().parsestr(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ReleaseManifestError(f"{source} metadata is not UTF-8") from exc
    name = metadata.get("Name", "")
    version = metadata.get("Version", "")
    if not name or not version:
        raise ReleaseManifestError(f"{source} metadata must contain Name and Version")
    return name, version


def _validate_wheel(path: Path, version: str) -> None:
    expected_suffix = ".dist-info/METADATA"
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(expected_suffix)]
            if len(metadata_names) != 1:
                raise ReleaseManifestError("wheel must contain exactly one dist-info METADATA file")
            name, metadata_version = _metadata_identity(
                archive.read(metadata_names[0]),
                source="wheel",
            )
    except zipfile.BadZipFile as exc:
        raise ReleaseManifestError("wheel is not a valid ZIP archive") from exc
    if _normalized_distribution(name) != PROJECT_DISTRIBUTION or metadata_version != version:
        raise ReleaseManifestError("wheel metadata does not match the release identity")


def _safe_tar_members(archive: tarfile.TarFile, *, prefix: str, source: str) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if not members:
        raise ReleaseManifestError(f"{source} archive is empty")
    root_name = prefix.rstrip("/")
    for member in members:
        path = PurePosixPath(member.name)
        inside_prefix = member.name == root_name or member.name.startswith(prefix)
        if path.is_absolute() or ".." in path.parts or not inside_prefix:
            raise ReleaseManifestError(f"{source} archive contains an unsafe or unexpected path")
        if member.issym() or member.islnk():
            raise ReleaseManifestError(f"{source} archive must not contain links")
    return members


def _validate_sdist(path: Path, version: str) -> None:
    prefix = f"{ARCHIVE_DISTRIBUTION}-{version}/"
    metadata_path = f"{prefix}PKG-INFO"
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = _safe_tar_members(archive, prefix=prefix, source="sdist")
            matches = [member for member in members if member.name == metadata_path and member.isfile()]
            if len(matches) != 1:
                raise ReleaseManifestError("sdist must contain exactly one root PKG-INFO")
            handle = archive.extractfile(matches[0])
            if handle is None:
                raise ReleaseManifestError("sdist PKG-INFO is unreadable")
            name, metadata_version = _metadata_identity(handle.read(), source="sdist")
    except tarfile.TarError as exc:
        raise ReleaseManifestError("sdist is not a valid gzip tar archive") from exc
    if _normalized_distribution(name) != PROJECT_DISTRIBUTION or metadata_version != version:
        raise ReleaseManifestError("sdist metadata does not match the release identity")


def _validate_source_archive(path: Path, version: str) -> None:
    prefix = f"reconforge-erp-{version}/"
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = _safe_tar_members(archive, prefix=prefix, source="source")
            names = {member.name for member in members if member.isfile()}
    except tarfile.TarError as exc:
        raise ReleaseManifestError("source is not a valid gzip tar archive") from exc
    if f"{prefix}pyproject.toml" not in names:
        raise ReleaseManifestError("source archive does not contain the release pyproject.toml")


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_release_manifest(
    *,
    project_root: Path,
    release_dir: Path,
    release_tag: str,
    source_revision: str,
    source_date_epoch: int,
    image_subject: str,
) -> dict[str, Any]:
    """Validate a release set, then atomically write its manifest and checksums."""
    root = project_root.resolve(strict=True)
    directory = release_dir.resolve(strict=True)
    if not directory.is_dir() or directory.is_symlink():
        raise ReleaseManifestError("release directory must be a real directory")
    if directory != root and root not in directory.parents:
        raise ReleaseManifestError("release directory must remain inside the project root")

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject.get("project", {}).get("version", ""))
    if not VERSION_RE.fullmatch(version) or release_tag != f"v{version}":
        raise ReleaseManifestError("release tag must exactly match the project version")
    if not REVISION_RE.fullmatch(source_revision):
        raise ReleaseManifestError("source revision must be a lowercase full Git SHA-1")
    if source_date_epoch < 0 or source_date_epoch > MAX_SOURCE_DATE_EPOCH:
        raise ReleaseManifestError("SOURCE_DATE_EPOCH is outside the gzip timestamp range")

    image_prefix = f"{IMAGE_REPOSITORY}@sha256:"
    if not image_subject.startswith(image_prefix):
        raise ReleaseManifestError("image subject must use the approved digest-addressed GHCR repository")
    image_digest = image_subject.removeprefix(image_prefix)
    if not SHA256_RE.fullmatch(image_digest):
        raise ReleaseManifestError("image subject must contain one lowercase SHA-256 digest")

    expected_paths = {
        "source-archive": directory / f"reconforge-erp-{version}-source.tar.gz",
        "python-wheel": directory / f"reconforge_erp-{version}-py3-none-any.whl",
        "python-sdist": directory / f"reconforge_erp-{version}.tar.gz",
    }
    for artifact_id, path in expected_paths.items():
        if not path.is_file() or path.is_symlink():
            raise ReleaseManifestError(f"missing or unsafe {artifact_id} artifact: {path.name}")

    unexpected = {
        path.name
        for path in directory.iterdir()
        if path.is_file()
        and (path.name.endswith(".whl") or path.name.endswith(".tar.gz"))
        and path not in expected_paths.values()
    }
    if unexpected:
        raise ReleaseManifestError(f"unexpected distributable artifacts: {sorted(unexpected)}")

    _validate_source_archive(expected_paths["source-archive"], version)
    _validate_wheel(expected_paths["python-wheel"], version)
    _validate_sdist(expected_paths["python-sdist"], version)

    artifacts = [
        {
            "id": "source-archive",
            "name": expected_paths["source-archive"].name,
            "location": expected_paths["source-archive"].name,
            "media_type": "application/gzip",
            "sha256": _sha256(expected_paths["source-archive"]),
        },
        {
            "id": "python-wheel",
            "name": expected_paths["python-wheel"].name,
            "location": expected_paths["python-wheel"].name,
            "media_type": "application/vnd.pypa.wheel+zip",
            "sha256": _sha256(expected_paths["python-wheel"]),
        },
        {
            "id": "python-sdist",
            "name": expected_paths["python-sdist"].name,
            "location": expected_paths["python-sdist"].name,
            "media_type": "application/gzip",
            "sha256": _sha256(expected_paths["python-sdist"]),
        },
        {
            "id": "container-image",
            "name": IMAGE_REPOSITORY,
            "location": image_subject,
            "media_type": "application/vnd.oci.image.manifest.v1+json",
            "sha256": image_digest,
        },
    ]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "release": {
            "tag": release_tag,
            "version": version,
            "source_repository": SOURCE_REPOSITORY,
            "source_revision": source_revision,
            "source_date_epoch": source_date_epoch,
            "signed_annotated_tag_required": True,
        },
        "builder": {
            "workflow_identity": WORKFLOW_IDENTITY,
            "runner_class": "github-hosted",
            "assessment": "UNEVALUATED",
        },
        "artifacts": artifacts,
        "verification_requirements": [
            "sha256-subject-match",
            "expected-repository",
            "expected-workflow",
            "expected-source-ref",
            "expected-source-revision",
            "deny-self-hosted-runner",
        ],
        "claim_boundary": (
            "This manifest records a release candidate identity. It is not a signature, attestation, "
            "publication record, SLSA level, or proof that external platform controls operated."
        ),
    }

    manifest_path = directory / "release-manifest.v1.json"
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    checksum_paths = [*expected_paths.values(), manifest_path]
    checksum_lines = [f"{_sha256(path)}  {path.name}" for path in sorted(checksum_paths, key=lambda item: item.name)]
    _atomic_write(directory / "SHA256SUMS", "\n".join(checksum_lines) + "\n")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--image-subject", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        build_release_manifest(
            project_root=args.project_root,
            release_dir=args.release_dir,
            release_tag=args.tag,
            source_revision=args.source_revision,
            source_date_epoch=args.source_date_epoch,
            image_subject=args.image_subject,
        )
    except (OSError, ReleaseManifestError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"release manifest rejected: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
