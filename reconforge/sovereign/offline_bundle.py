"""Closed, non-executable manifest verification for an offline install bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_MANIFEST_BYTES = 1_048_576
MAX_ENTRY_BYTES = 2_147_483_648
MAX_ENTRIES = 2_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?)"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*) --hash=sha256:(?P<digest>[0-9a-f]{64})$"
)


class OfflineBundleError(ValueError):
    """Raised when a disconnected bundle cannot be proven closed and local."""


class OfflineBundleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=240)
    role: Literal[
        "application-wheel",
        "dependency-wheel",
        "requirements-lock",
        "release-manifest",
        "release-checksums",
        "provenance-bundle",
        "sbom",
        "operator-documentation",
    ]
    size: int = Field(ge=1, le=MAX_ENTRY_BYTES)
    sha256: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or str(path) != value:
            raise ValueError("bundle entry path must be a normalized relative POSIX path")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("bundle entry digest must be lowercase SHA-256")
        return value


class OfflineInstallContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installer: Literal["pip-no-index-v1"]
    requirements_path: str
    application_requirement: str = Field(pattern=r"^reconforge-erp(?:\[[a-z,]+\])?==[0-9]+\.[0-9]+\.[0-9]+$")
    network_policy: Literal["deny-all"]
    index_policy: Literal["no-index"]


class OfflineBundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["reconforge-offline-bundle-v1"] = Field(alias="schema")
    bundle_id: str = Field(pattern=r"^[a-z][a-z0-9-]{7,63}$")
    application_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    python_tag: str = Field(pattern=r"^cp3(11|12|13|14)$")
    platform_tag: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,63}$")
    install: OfflineInstallContract
    entries: tuple[OfflineBundleEntry, ...] = Field(min_length=5, max_length=MAX_ENTRIES)
    claim_boundary: Literal[
        "Local artifact integrity only; external signature trust, installation success, and production readiness require separate evidence."
    ]

    @model_validator(mode="after")
    def validate_closed_inventory(self) -> OfflineBundleManifest:
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("bundle entry paths must be unique")
        requirements = [entry for entry in self.entries if entry.role == "requirements-lock"]
        applications = [entry for entry in self.entries if entry.role == "application-wheel"]
        if len(requirements) != 1 or len(applications) != 1:
            raise ValueError("bundle requires exactly one requirements lock and one application wheel")
        if requirements[0].path != self.install.requirements_path:
            raise ValueError("install requirements path must identify the declared lock entry")
        for entry in self.entries:
            is_wheel = entry.path.endswith(".whl")
            if (entry.role in {"application-wheel", "dependency-wheel"}) != is_wheel:
                raise ValueError("wheel roles and file suffixes must agree")
        return self


class VerifiedOfflineBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: str
    application_version: str
    manifest_sha256: str
    entry_count: int
    total_bytes: int
    install_argv: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise OfflineBundleError("offline_bundle_entry_missing_or_unsafe")
    current = candidate.parent
    while current != root:
        if current.is_symlink():
            raise OfflineBundleError("offline_bundle_entry_parent_symlink")
        current = current.parent
    if candidate.resolve(strict=True).parent != root and root not in candidate.resolve(strict=True).parents:
        raise OfflineBundleError("offline_bundle_entry_escape")
    return candidate


def _verify_requirements(path: Path, application_requirement: str) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise OfflineBundleError("offline_requirements_not_utf8") from exc
    requirements: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise OfflineBundleError("offline_requirement_not_exactly_hashed")
        requirements.append(f"{match.group('name')}=={match.group('version')}")
    if not requirements or application_requirement not in requirements or len(requirements) != len(set(requirements)):
        raise OfflineBundleError("offline_requirements_identity_invalid")


def verify_offline_bundle(manifest_path: Path) -> VerifiedOfflineBundle:
    """Verify a complete local inventory without executing installers or using a network."""
    manifest_file = manifest_path.resolve(strict=True)
    if manifest_path.is_symlink() or not manifest_file.is_file() or manifest_file.stat().st_size > MAX_MANIFEST_BYTES:
        raise OfflineBundleError("offline_bundle_manifest_unsafe")
    root = manifest_file.parent
    if root.is_symlink() or not root.is_dir():
        raise OfflineBundleError("offline_bundle_root_unsafe")
    try:
        raw = manifest_file.read_bytes()
        manifest = OfflineBundleManifest.model_validate(json.loads(raw))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise OfflineBundleError("offline_bundle_manifest_invalid") from exc

    declared = {entry.path: entry for entry in manifest.entries}
    observed: set[str] = set()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in [*directory_names, *file_names]:
            child = directory_path / name
            if child.is_symlink():
                raise OfflineBundleError("offline_bundle_symlink_forbidden")
        for name in file_names:
            child = directory_path / name
            if child != manifest_file:
                observed.add(child.relative_to(root).as_posix())
    if observed != set(declared):
        raise OfflineBundleError("offline_bundle_inventory_mismatch")

    total_bytes = 0
    for relative, entry in declared.items():
        path = _safe_file(root, relative)
        size = path.stat().st_size
        if size != entry.size or _sha256(path) != entry.sha256:
            raise OfflineBundleError("offline_bundle_entry_integrity_failed")
        total_bytes += size
    requirements = _safe_file(root, manifest.install.requirements_path)
    _verify_requirements(requirements, manifest.install.application_requirement)
    return VerifiedOfflineBundle(
        bundle_id=manifest.bundle_id,
        application_version=manifest.application_version,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        entry_count=len(manifest.entries),
        total_bytes=total_bytes,
        install_argv=(
            "python", "-m", "pip", "install", "--no-index", "--disable-pip-version-check",
            "--no-deps", "--find-links", str(root / "wheelhouse"), "--require-hashes", "-r", str(requirements),
        ),
    )
