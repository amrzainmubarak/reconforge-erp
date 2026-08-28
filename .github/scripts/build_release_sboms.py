"""Build deterministic, subject-bound CycloneDX 1.7 release SBOMs."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import tarfile
import tomllib
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"
CYCLONEDX_SPEC_VERSION = "1.7"
CYCLONEDX_MEDIA_TYPE = "application/vnd.cyclonedx+json"
CYCLONEDX_PREDICATE_TYPE = "https://cyclonedx.org/bom"
PROJECT_DISTRIBUTION = "reconforge-erp"
SOURCE_REPOSITORY = "https://github.com/amrzainmubarak/reconforge-erp"
IMAGE_REPOSITORY = "ghcr.io/amrzainmubarak/reconforge-erp"
GENERATOR_NAME = "reconforge-release-sbom-builder"
GENERATOR_VERSION = "1.0.0"
SYFT_NAME = "syft"
SYFT_VERSION = "1.51.0"
SYFT_COMMIT = "2293641e3bd628a01bb37639318d62c0ebe89b39"
SBOM_NAMESPACE = uuid.UUID("bcaa96f0-a66e-5c6c-bf71-c0f26e28542c")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
MAX_JSON_BYTES = 256 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000


class SbomBuildError(ValueError):
    """Raised when a release SBOM cannot be built without ambiguity."""


@dataclass(frozen=True)
class DeclaredRequirement:
    canonical: str
    name: str
    project_extra: str | None
    requested_extras: tuple[str, ...]
    specifier: str
    marker: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _inventory_sha256(document: dict[str, Any]) -> str:
    inventory = {
        "components": document.get("components", []),
        "dependencies": document.get("dependencies", []),
        "services": document.get("services", []),
    }
    return hashlib.sha256(_canonical_json(inventory).encode("utf-8")).hexdigest()


def _timestamp(source_date_epoch: int) -> str:
    try:
        value = datetime.fromtimestamp(source_date_epoch, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise SbomBuildError("SOURCE_DATE_EPOCH is outside the supported UTC range") from exc
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _uuid_urn(identity: str) -> str:
    return f"urn:uuid:{uuid.uuid5(SBOM_NAMESPACE, identity)}"


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            temporary.unlink(missing_ok=True)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SbomBuildError(f"JSON object contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SbomBuildError(f"{label} must be a regular file")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise SbomBuildError(f"{label} exceeds the {MAX_JSON_BYTES}-byte limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SbomBuildError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise SbomBuildError(f"{label} must contain one JSON object")
    return payload


def _safe_tar_members(archive: tarfile.TarFile, *, prefix: str, label: str) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if not members or len(members) > MAX_ARCHIVE_MEMBERS:
        raise SbomBuildError(f"{label} has an invalid member count")
    root_name = prefix.rstrip("/")
    for member in members:
        path = PurePosixPath(member.name)
        inside_prefix = member.name == root_name or member.name.startswith(prefix)
        if path.is_absolute() or ".." in path.parts or not inside_prefix:
            raise SbomBuildError(f"{label} contains an unsafe or unexpected path")
        if member.issym() or member.islnk():
            raise SbomBuildError(f"{label} must not contain links")
    return members


def _read_tar_member(
    path: Path,
    *,
    prefix: str,
    member_name: str,
    label: str,
    required: bool = True,
) -> bytes | None:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = _safe_tar_members(archive, prefix=prefix, label=label)
            matches = [member for member in members if member.name == member_name and member.isfile()]
            if not matches and not required:
                return None
            if len(matches) != 1 or matches[0].size > MAX_METADATA_BYTES:
                raise SbomBuildError(f"{label} must contain one bounded {PurePosixPath(member_name).name}")
            handle = archive.extractfile(matches[0])
            if handle is None:
                raise SbomBuildError(f"{label} metadata is unreadable")
            return handle.read(MAX_METADATA_BYTES + 1)
    except tarfile.TarError as exc:
        raise SbomBuildError(f"{label} is not a valid gzip tar archive") from exc


def _read_wheel_metadata(path: Path, *, version: str) -> bytes:
    expected = f"reconforge_erp-{version}.dist-info/METADATA"
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ARCHIVE_MEMBERS:
                raise SbomBuildError("wheel has an invalid member count")
            for entry in entries:
                member = PurePosixPath(entry.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise SbomBuildError("wheel contains an unsafe path")
            matches = [entry for entry in entries if entry.filename == expected and not entry.is_dir()]
            if len(matches) != 1 or matches[0].file_size > MAX_METADATA_BYTES:
                raise SbomBuildError("wheel must contain one bounded root METADATA file")
            return archive.read(matches[0])
    except zipfile.BadZipFile as exc:
        raise SbomBuildError("wheel is not a valid ZIP archive") from exc


def _requirement_base(requirement: Requirement) -> str:
    extras = f"[{','.join(sorted(canonicalize_name(extra) for extra in requirement.extras))}]" if requirement.extras else ""
    if requirement.url:
        return f"{canonicalize_name(requirement.name)}{extras} @ {requirement.url}"
    return f"{canonicalize_name(requirement.name)}{extras}{requirement.specifier}"


def _requirement_record(raw: str, *, project_extra: str | None) -> DeclaredRequirement:
    try:
        parsed = Requirement(raw)
    except InvalidRequirement as exc:
        raise SbomBuildError(f"invalid declared Python requirement: {raw}") from exc
    if parsed.url:
        raise SbomBuildError(f"direct-URL release dependency is outside the SBOM policy: {parsed.name}")
    extra = canonicalize_name(project_extra) if project_extra else None
    marker = str(parsed.marker) if parsed.marker else None
    canonical = _requirement_base(parsed)
    if marker:
        canonical = f"{canonical}; {marker}"
    return DeclaredRequirement(
        canonical=canonical,
        name=canonicalize_name(parsed.name),
        project_extra=extra,
        requested_extras=tuple(sorted(canonicalize_name(value) for value in parsed.extras)),
        specifier=str(parsed.specifier),
        marker=marker,
    )


def _optional_requirement(raw: str, *, project_extra: str) -> DeclaredRequirement:
    try:
        parsed = Requirement(raw)
    except InvalidRequirement as exc:
        raise SbomBuildError(f"invalid optional Python requirement: {raw}") from exc
    extra = canonicalize_name(project_extra)
    marker = f"({parsed.marker}) and extra == \"{extra}\"" if parsed.marker else f"extra == \"{extra}\""
    return _requirement_record(f"{_requirement_base(parsed)}; {marker}", project_extra=extra)


def _unique_requirements(records: list[DeclaredRequirement], *, label: str) -> tuple[DeclaredRequirement, ...]:
    by_identity: dict[str, DeclaredRequirement] = {}
    for record in records:
        if record.canonical in by_identity:
            raise SbomBuildError(f"{label} contains a duplicate declared requirement: {record.canonical}")
        by_identity[record.canonical] = record
    return tuple(by_identity[key] for key in sorted(by_identity))


def _source_requirements(raw: bytes, *, version: str) -> tuple[DeclaredRequirement, ...]:
    try:
        payload = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SbomBuildError("source pyproject.toml is not valid UTF-8 TOML") from exc
    project = payload.get("project")
    if not isinstance(project, dict):
        raise SbomBuildError("source pyproject.toml has no project table")
    if canonicalize_name(str(project.get("name", ""))) != PROJECT_DISTRIBUTION or project.get("version") != version:
        raise SbomBuildError("source project identity does not match the release manifest")
    dependencies = project.get("dependencies", [])
    optional = project.get("optional-dependencies", {})
    if not isinstance(dependencies, list) or not all(isinstance(value, str) for value in dependencies):
        raise SbomBuildError("source project dependencies must be strings")
    if not isinstance(optional, dict):
        raise SbomBuildError("source optional dependencies must be a table")
    records = [_requirement_record(value, project_extra=None) for value in dependencies]
    for extra, values in optional.items():
        if not isinstance(extra, str) or not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise SbomBuildError("source optional dependency groups must contain strings")
        records.extend(_optional_requirement(value, project_extra=extra) for value in values)
    return _unique_requirements(records, label="source metadata")


def _package_requirements(raw: bytes, *, version: str, label: str) -> tuple[str, str, tuple[str, ...]]:
    if len(raw) > MAX_METADATA_BYTES:
        raise SbomBuildError(f"{label} metadata exceeds the bounded size")
    try:
        metadata = Parser().parsestr(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SbomBuildError(f"{label} metadata is not UTF-8") from exc
    name = metadata.get("Name", "")
    metadata_version = metadata.get("Version", "")
    if canonicalize_name(name) != PROJECT_DISTRIBUTION or metadata_version != version:
        raise SbomBuildError(f"{label} identity does not match the release manifest")
    canonical = [_requirement_record(value, project_extra=None).canonical for value in metadata.get_all("Requires-Dist", [])]
    if len(set(canonical)) != len(canonical):
        raise SbomBuildError(f"{label} metadata contains duplicate Requires-Dist values")
    return name, metadata_version, tuple(sorted(canonical))


def _property(name: str, value: str) -> dict[str, str]:
    return {"name": name, "value": value}


def _declared_component(record: DeclaredRequirement) -> dict[str, Any]:
    reference = _uuid_urn(f"python-requirement:{record.canonical}")
    properties = [
        _property("reconforge:python:declared-requirement", record.canonical),
        _property("reconforge:python:project-extra", record.project_extra or "runtime"),
        _property("reconforge:python:resolution", "unresolved"),
    ]
    if record.marker:
        properties.append(_property("reconforge:python:marker", record.marker))
    if record.requested_extras:
        properties.append(_property("reconforge:python:requested-extras", ",".join(record.requested_extras)))
    return {
        "bom-ref": reference,
        "type": "library",
        "name": record.name,
        "scope": "optional" if record.project_extra else "required",
        "properties": sorted(properties, key=lambda item: (item["name"], item["value"])),
    }


def _json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SbomBuildError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise SbomBuildError(f"{label} must contain one JSON object")
    return payload


def _npm_hash(integrity: str) -> list[dict[str, str]]:
    algorithm, separator, encoded = integrity.partition("-")
    algorithms = {"sha256": "SHA-256", "sha384": "SHA-384", "sha512": "SHA-512"}
    if not separator or algorithm not in algorithms:
        raise SbomBuildError("npm package integrity uses an unsupported algorithm")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SbomBuildError("npm package integrity is not valid base64") from exc
    expected_lengths = {"sha256": 32, "sha384": 48, "sha512": 64}
    if len(decoded) != expected_lengths[algorithm]:
        raise SbomBuildError("npm package integrity digest has the wrong length")
    content = decoded.hex()
    return [{"alg": algorithms[algorithm], "content": content}]


def _npm_components(package_raw: bytes | None, lock_raw: bytes | None) -> tuple[dict[str, Any], ...]:
    if package_raw is None and lock_raw is None:
        return ()
    if package_raw is None or lock_raw is None:
        raise SbomBuildError("source archive must contain both apps/web/package.json and package-lock.json")
    package = _json_bytes(package_raw, label="source package.json")
    lock = _json_bytes(lock_raw, label="source package-lock.json")
    if lock.get("lockfileVersion") != 3:
        raise SbomBuildError("source package-lock.json must use lockfileVersion 3")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not packages or len(packages) > MAX_ARCHIVE_MEMBERS:
        raise SbomBuildError("source package-lock.json has an invalid packages map")
    lock_root = packages.get("")
    if not isinstance(lock_root, dict):
        raise SbomBuildError("source package-lock.json has no root package")
    for field in ("name", "version", "dependencies", "devDependencies", "optionalDependencies"):
        package_value = package.get(field, {} if field.endswith("Dependencies") else None)
        lock_value = lock_root.get(field, {} if field.endswith("Dependencies") else None)
        if package_value != lock_value:
            raise SbomBuildError(f"source package-lock.json root {field} does not match package.json")

    components: list[dict[str, Any]] = []
    for location, metadata in packages.items():
        if location == "":
            continue
        if (
            not isinstance(location, str)
            or not location.startswith("node_modules/")
            or "\\" in location
            or ".." in PurePosixPath(location).parts
        ):
            raise SbomBuildError("source package-lock.json contains an unsafe package location")
        if not isinstance(metadata, dict) or metadata.get("link"):
            raise SbomBuildError("source package-lock.json contains an unsupported linked package")
        name = location.rsplit("node_modules/", 1)[-1]
        version = metadata.get("version")
        if not name or not isinstance(version, str) or not version:
            raise SbomBuildError("source package-lock.json package identity is incomplete")
        resolved = metadata.get("resolved")
        if resolved is not None:
            if not isinstance(resolved, str):
                raise SbomBuildError("source package-lock.json contains a non-string resolution")
            parsed_resolution = urlsplit(resolved)
            if (
                parsed_resolution.scheme != "https"
                or not parsed_resolution.hostname
                or parsed_resolution.username
                or parsed_resolution.password
            ):
                raise SbomBuildError("source package-lock.json contains an unsafe non-HTTPS resolution")
        properties = [
            _property("reconforge:npm:lockfile-version", "3"),
            _property("reconforge:npm:package-lock-location", f"apps/web/{location}"),
            _property("reconforge:npm:resolution", "locked-version"),
        ]
        for field in ("dev", "optional", "peer"):
            if metadata.get(field) is True:
                properties.append(_property(f"reconforge:npm:{field}", "true"))
        license_value = metadata.get("license")
        if license_value is not None:
            if not isinstance(license_value, str) or not license_value:
                raise SbomBuildError("source package-lock.json contains an invalid license value")
            properties.append(_property("reconforge:npm:declared-license", license_value))
        if resolved:
            properties.append(_property("reconforge:npm:resolved", resolved))
        component: dict[str, Any] = {
            "bom-ref": _uuid_urn(f"npm-lock:{location}:{name}:{version}"),
            "type": "library",
            "name": name,
            "version": version,
            "scope": "optional" if metadata.get("dev") is True or metadata.get("optional") is True else "required",
            "properties": sorted(properties, key=lambda item: (item["name"], item["value"])),
        }
        integrity = metadata.get("integrity")
        if integrity is not None:
            if not isinstance(integrity, str):
                raise SbomBuildError("source package-lock.json contains a non-string integrity value")
            component["hashes"] = _npm_hash(integrity)
        components.append(component)
    return tuple(sorted(components, key=lambda item: item["bom-ref"]))


def _subject_component(artifact: dict[str, Any], *, version: str, component_type: str) -> dict[str, Any]:
    reference = _uuid_urn(f"subject:{artifact['id']}:{artifact['sha256']}")
    return {
        "bom-ref": reference,
        "type": component_type,
        "name": artifact["name"],
        "version": version,
        "hashes": [{"alg": "SHA-256", "content": artifact["sha256"]}],
        "properties": [
            _property("reconforge:release:artifact-id", artifact["id"]),
            _property("reconforge:release:subject-location", artifact["location"]),
        ],
    }


def _python_sbom(
    artifact: dict[str, Any],
    *,
    requirements: tuple[DeclaredRequirement, ...],
    release: dict[str, Any],
    additional_components: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    root = _subject_component(artifact, version=release["version"], component_type="file")
    python_components = [_declared_component(record) for record in requirements]
    components = [*python_components, *additional_components]
    python_refs = [component["bom-ref"] for component in python_components]
    dependencies = [{"ref": root["bom-ref"], "dependsOn": python_refs}]
    dependencies.extend({"ref": reference, "dependsOn": []} for reference in python_refs)
    return {
        "$schema": CYCLONEDX_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": _uuid_urn(f"sbom:{artifact['id']}:{artifact['sha256']}"),
        "version": 1,
        "metadata": {
            "timestamp": _timestamp(release["source_date_epoch"]),
            "tools": {
                "components": [
                    {"type": "application", "name": GENERATOR_NAME, "version": GENERATOR_VERSION}
                ]
            },
            "component": root,
            "properties": [
                _property("reconforge:sbom:completeness", "unknown"),
                _property(
                    "reconforge:sbom:generation-mode",
                    "declared-python-and-locked-npm-metadata" if additional_components else "declared-python-metadata",
                ),
                _property("reconforge:sbom:predicate-type", CYCLONEDX_PREDICATE_TYPE),
                _property("reconforge:release:source-revision", release["source_revision"]),
            ],
        },
        "components": components,
        "dependencies": dependencies,
        "compositions": [{"aggregate": "unknown", "assemblies": [root["bom-ref"]]}],
    }


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _walk_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _walk_strings(item)]
    return []


def _contains_signature(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_signature(item) for item in value)
    if isinstance(value, dict):
        return "signature" in value or any(_contains_signature(item) for item in value.values())
    return False


def _replace_reference(value: Any, *, old: str, new: str) -> Any:
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace_reference(item, old=old, new=new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_reference(item, old=old, new=new) for key, item in value.items()}
    return value


def _sort_cyclonedx(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _sort_cyclonedx(item, parent_key=key) for key, item in value.items()}
    if not isinstance(value, list):
        return value
    normalized = [_sort_cyclonedx(item) for item in value]
    if parent_key == "components":
        return sorted(normalized, key=lambda item: (item.get("bom-ref", ""), _canonical_json(item)))
    if parent_key == "dependencies":
        for item in normalized:
            if isinstance(item, dict):
                for key in ("dependsOn", "provides"):
                    if isinstance(item.get(key), list):
                        item[key] = sorted(item[key])
        return sorted(normalized, key=lambda item: (item.get("ref", ""), _canonical_json(item)))
    if parent_key == "properties":
        return sorted(normalized, key=lambda item: (item.get("name", ""), item.get("value", "")))
    if parent_key == "hashes":
        return sorted(normalized, key=lambda item: (item.get("alg", ""), item.get("content", "")))
    if parent_key in {"licenses", "externalReferences"}:
        return sorted(normalized, key=_canonical_json)
    return normalized


def _validate_references(document: dict[str, Any]) -> None:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("component"), dict):
        raise SbomBuildError("CycloneDX metadata must identify one subject component")
    root_ref = metadata["component"].get("bom-ref")
    if not isinstance(root_ref, str) or not root_ref:
        raise SbomBuildError("CycloneDX subject component must have a bom-ref")
    components = document.get("components", [])
    if not isinstance(components, list):
        raise SbomBuildError("CycloneDX components must be an array")
    references = [root_ref]
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("bom-ref"), str):
            raise SbomBuildError("every CycloneDX component must have a bom-ref")
        references.append(component["bom-ref"])
    if len(set(references)) != len(references):
        raise SbomBuildError("CycloneDX bom-ref values must be unique")
    known = set(references)
    dependencies = document.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise SbomBuildError("CycloneDX dependencies must be an array")
    dependency_refs: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict) or dependency.get("ref") not in known:
            raise SbomBuildError("CycloneDX dependency has an unknown ref")
        if dependency["ref"] in dependency_refs:
            raise SbomBuildError("CycloneDX dependency refs must be unique")
        dependency_refs.add(dependency["ref"])
        related = dependency.get("dependsOn", [])
        if not isinstance(related, list) or any(value not in known for value in related):
            raise SbomBuildError("CycloneDX dependency has an unknown dependsOn ref")


def _normalize_image_sbom(
    raw: dict[str, Any],
    *,
    artifact: dict[str, Any],
    release: dict[str, Any],
    forbidden_path_prefixes: tuple[str, ...],
) -> dict[str, Any]:
    if raw.get("bomFormat") != "CycloneDX" or raw.get("specVersion") != CYCLONEDX_SPEC_VERSION:
        raise SbomBuildError("Syft output must be CycloneDX 1.7")
    if raw.get("version") != 1 or raw.get("$schema") != CYCLONEDX_SCHEMA:
        raise SbomBuildError("Syft output has an unsupported CycloneDX document identity")
    if _contains_signature(raw):
        raise SbomBuildError("signed Syft input cannot be normalized without invalidating its signature")
    for prefix in forbidden_path_prefixes:
        normalized_prefix = prefix.replace("\\", "/").rstrip("/").casefold()
        if normalized_prefix and any(normalized_prefix in text.replace("\\", "/").casefold() for text in _walk_strings(raw)):
            raise SbomBuildError("Syft output discloses a forbidden host path")

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        raise SbomBuildError("Syft output has no metadata object")
    tools = metadata.get("tools")
    tool_components = tools.get("components") if isinstance(tools, dict) else None
    if not isinstance(tool_components, list):
        raise SbomBuildError("Syft output has no component-form tool identity")
    syft_tools = [
        tool
        for tool in tool_components
        if isinstance(tool, dict) and tool.get("name") == SYFT_NAME and tool.get("version") == SYFT_VERSION
    ]
    if len(syft_tools) != 1:
        raise SbomBuildError("Syft output does not identify exactly the pinned Syft version")
    old_root = metadata.get("component")
    if not isinstance(old_root, dict) or not isinstance(old_root.get("bom-ref"), str):
        raise SbomBuildError("Syft output has no source component bom-ref")
    if old_root.get("name") != artifact["name"] or old_root.get("version") != release["version"]:
        raise SbomBuildError("Syft source identity does not match the image subject")
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise SbomBuildError("Syft image scan must inventory at least one component")

    root = _subject_component(artifact, version=release["version"], component_type="container")
    normalized = _replace_reference(raw, old=old_root["bom-ref"], new=root["bom-ref"])
    normalized["$schema"] = CYCLONEDX_SCHEMA
    normalized["serialNumber"] = _uuid_urn(f"sbom:{artifact['id']}:{artifact['sha256']}")
    normalized["version"] = 1
    normalized_metadata = normalized["metadata"]
    normalized_metadata["timestamp"] = _timestamp(release["source_date_epoch"])
    normalized_metadata["component"] = root
    retained_properties = normalized_metadata.get("properties", [])
    if not isinstance(retained_properties, list):
        raise SbomBuildError("Syft metadata properties must be an array when present")
    if any(
        isinstance(item, dict) and str(item.get("name", "")).startswith("reconforge:")
        for item in retained_properties
    ):
        raise SbomBuildError("Syft input must not predefine ReconForge policy properties")
    normalized_metadata["properties"] = [
        *retained_properties,
        _property("reconforge:sbom:completeness", "unknown"),
        _property("reconforge:sbom:generation-mode", "syft-installed-image-scan"),
        _property("reconforge:sbom:normalized-by", f"{GENERATOR_NAME}@{GENERATOR_VERSION}"),
        _property("reconforge:sbom:predicate-type", CYCLONEDX_PREDICATE_TYPE),
        _property("reconforge:release:source-revision", release["source_revision"]),
    ]
    result = _sort_cyclonedx(normalized)
    _validate_references(result)
    return result


def _artifact_map(release_manifest: dict[str, Any], *, directory: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if release_manifest.get("schema_version") != 1:
        raise SbomBuildError("release manifest schema version is unsupported")
    release = release_manifest.get("release")
    artifacts = release_manifest.get("artifacts")
    if not isinstance(release, dict) or not isinstance(artifacts, list):
        raise SbomBuildError("release manifest has an invalid structure")
    version = release.get("version")
    if (
        not isinstance(version, str)
        or not VERSION_RE.fullmatch(version)
        or release.get("tag") != f"v{version}"
        or release.get("source_repository") != SOURCE_REPOSITORY
        or not isinstance(release.get("source_revision"), str)
        or not REVISION_RE.fullmatch(release["source_revision"])
        or isinstance(release.get("source_date_epoch"), bool)
        or not isinstance(release.get("source_date_epoch"), int)
        or release["source_date_epoch"] < 0
    ):
        raise SbomBuildError("release manifest release identity is invalid")
    expected_ids = ["source-archive", "python-wheel", "python-sdist", "container-image"]
    if [item.get("id") for item in artifacts if isinstance(item, dict)] != expected_ids:
        raise SbomBuildError("release manifest artifact set or order is invalid")
    artifact_map = {item["id"]: item for item in artifacts}
    expected_metadata = {
        "source-archive": (
            f"reconforge-erp-{version}-source.tar.gz",
            f"reconforge-erp-{version}-source.tar.gz",
            "application/gzip",
        ),
        "python-wheel": (
            f"reconforge_erp-{version}-py3-none-any.whl",
            f"reconforge_erp-{version}-py3-none-any.whl",
            "application/vnd.pypa.wheel+zip",
        ),
        "python-sdist": (
            f"reconforge_erp-{version}.tar.gz",
            f"reconforge_erp-{version}.tar.gz",
            "application/gzip",
        ),
        "container-image": (
            IMAGE_REPOSITORY,
            f"{IMAGE_REPOSITORY}@sha256:{artifact_map['container-image'].get('sha256', '')}",
            "application/vnd.oci.image.manifest.v1+json",
        ),
    }
    for artifact_id in expected_ids:
        artifact = artifact_map[artifact_id]
        if not isinstance(artifact.get("sha256"), str) or not SHA256_RE.fullmatch(artifact["sha256"]):
            raise SbomBuildError(f"release manifest {artifact_id} digest is invalid")
        if (artifact.get("name"), artifact.get("location"), artifact.get("media_type")) != expected_metadata[artifact_id]:
            raise SbomBuildError(f"release manifest {artifact_id} metadata is invalid")
        if artifact_id != "container-image":
            path = directory / artifact["location"]
            if path.parent != directory or not path.is_file() or path.is_symlink():
                raise SbomBuildError(f"release manifest {artifact_id} location is unsafe")
            if _sha256(path) != artifact["sha256"]:
                raise SbomBuildError(f"release manifest {artifact_id} digest does not match the artifact")
    image = artifact_map["container-image"]
    if image.get("name") != IMAGE_REPOSITORY or image.get("location") != f"{IMAGE_REPOSITORY}@sha256:{image['sha256']}":
        raise SbomBuildError("release manifest image subject is not digest-addressed")
    return artifact_map, release


def _sbom_filename(artifact_id: str, *, version: str) -> str:
    names = {
        "source-archive": f"reconforge-erp-{version}-source.cdx.json",
        "python-wheel": f"reconforge_erp-{version}-py3-none-any.cdx.json",
        "python-sdist": f"reconforge_erp-{version}-sdist.cdx.json",
        "container-image": f"reconforge-erp-{version}-image.cdx.json",
    }
    return names[artifact_id]


def build_release_sboms(
    *,
    project_root: Path,
    release_dir: Path,
    image_sbom_input: Path,
    source_date_epoch: int,
    forbidden_path_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate all subjects and inputs, then write four SBOMs and one manifest."""
    root = project_root.resolve(strict=True)
    if release_dir.is_symlink():
        raise SbomBuildError("release directory must not be a symbolic link")
    directory = release_dir.resolve(strict=True)
    if not directory.is_dir():
        raise SbomBuildError("release directory must be a real directory")
    if directory != root and root not in directory.parents:
        raise SbomBuildError("release directory must remain inside the project root")
    release_manifest_path = directory / "release-manifest.v1.json"
    release_manifest = _load_json(release_manifest_path, label="release manifest")
    artifacts, release = _artifact_map(release_manifest, directory=directory)
    if release.get("source_date_epoch") != source_date_epoch:
        raise SbomBuildError("SOURCE_DATE_EPOCH does not match the release manifest")
    if not isinstance(release.get("version"), str) or not isinstance(release.get("source_revision"), str):
        raise SbomBuildError("release manifest version or source revision is invalid")
    version = release["version"]

    source_artifact = artifacts["source-archive"]
    source_prefix = f"reconforge-erp-{version}/"
    source_raw = _read_tar_member(
        directory / source_artifact["location"],
        prefix=source_prefix,
        member_name=f"{source_prefix}pyproject.toml",
        label="source archive",
    )
    if source_raw is None:
        raise SbomBuildError("source archive pyproject.toml is missing")
    requirements = _source_requirements(source_raw, version=version)
    expected_requirements = tuple(record.canonical for record in requirements)
    package_raw = _read_tar_member(
        directory / source_artifact["location"],
        prefix=source_prefix,
        member_name=f"{source_prefix}apps/web/package.json",
        label="source archive",
        required=False,
    )
    package_lock_raw = _read_tar_member(
        directory / source_artifact["location"],
        prefix=source_prefix,
        member_name=f"{source_prefix}apps/web/package-lock.json",
        label="source archive",
        required=False,
    )
    npm_components = _npm_components(package_raw, package_lock_raw)

    wheel_raw = _read_wheel_metadata(directory / artifacts["python-wheel"]["location"], version=version)
    _, _, wheel_requirements = _package_requirements(wheel_raw, version=version, label="wheel")
    sdist_prefix = f"reconforge_erp-{version}/"
    sdist_raw = _read_tar_member(
        directory / artifacts["python-sdist"]["location"],
        prefix=sdist_prefix,
        member_name=f"{sdist_prefix}PKG-INFO",
        label="sdist",
    )
    if sdist_raw is None:
        raise SbomBuildError("sdist PKG-INFO is missing")
    _, _, sdist_requirements = _package_requirements(sdist_raw, version=version, label="sdist")
    if wheel_requirements != expected_requirements:
        raise SbomBuildError("wheel Requires-Dist does not exactly match source declarations")
    if sdist_requirements != expected_requirements:
        raise SbomBuildError("sdist Requires-Dist does not exactly match source declarations")

    documents = {
        artifact_id: _python_sbom(artifacts[artifact_id], requirements=requirements, release=release)
        for artifact_id in ("source-archive", "python-wheel", "python-sdist")
    }
    documents["source-archive"] = _python_sbom(
        artifacts["source-archive"],
        requirements=requirements,
        release=release,
        additional_components=npm_components,
    )
    raw_image_sbom = _load_json(image_sbom_input, label="Syft image SBOM")
    documents["container-image"] = _normalize_image_sbom(
        raw_image_sbom,
        artifact=artifacts["container-image"],
        release=release,
        forbidden_path_prefixes=forbidden_path_prefixes,
    )
    for document in documents.values():
        _validate_references(document)

    output_names = {artifact_id: _sbom_filename(artifact_id, version=version) for artifact_id in artifacts}
    allowed_cyclonedx = set(output_names.values())
    unexpected = {
        path.name for path in directory.iterdir() if path.is_file() and path.name.endswith(".cdx.json") and path.name not in allowed_cyclonedx
    }
    if unexpected:
        raise SbomBuildError(f"unexpected CycloneDX outputs already exist: {sorted(unexpected)}")

    rendered = {
        artifact_id: json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        for artifact_id, document in documents.items()
    }
    sbom_digests = {
        artifact_id: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for artifact_id, content in rendered.items()
    }
    entries = []
    for artifact_id in ("source-archive", "python-wheel", "python-sdist", "container-image"):
        artifact = artifacts[artifact_id]
        entries.append(
            {
                "id": artifact_id,
                "subject": {
                    "name": artifact["name"],
                    "location": artifact["location"],
                    "media_type": artifact["media_type"],
                    "sha256": artifact["sha256"],
                },
                "sbom": {
                    "name": output_names[artifact_id],
                    "media_type": CYCLONEDX_MEDIA_TYPE,
                    "spec_version": CYCLONEDX_SPEC_VERSION,
                    "sha256": sbom_digests[artifact_id],
                },
                "generation_mode": (
                    "syft-installed-image-scan"
                    if artifact_id == "container-image"
                    else (
                        "declared-python-and-locked-npm-metadata"
                        if artifact_id == "source-archive" and npm_components
                        else "declared-python-metadata"
                    )
                ),
                "completeness": "unknown",
                "component_count": len(documents[artifact_id].get("components", [])),
                "inventory_sha256": _inventory_sha256(documents[artifact_id]),
            }
        )
    manifest = {
        "schema_version": 1,
        "release_manifest": {
            "name": release_manifest_path.name,
            "sha256": _sha256(release_manifest_path),
        },
        "generator_policy": {
            "cyclonedx_spec_version": CYCLONEDX_SPEC_VERSION,
            "predicate_type": CYCLONEDX_PREDICATE_TYPE,
            "python_generator": f"{GENERATOR_NAME}@{GENERATOR_VERSION}",
            "image_generator": f"{SYFT_NAME}@{SYFT_VERSION}",
            "image_generator_commit": SYFT_COMMIT,
        },
        "sboms": entries,
        "verification_requirements": [
            "subject-sha256-match",
            "sbom-sha256-match",
            "cyclonedx-1.7-schema",
            "expected-generator",
            "expected-repository",
            "expected-workflow",
            "expected-source-ref",
            "expected-source-revision",
            "deny-self-hosted-runner",
        ],
        "claim_boundary": (
            "Package SBOMs list declared Python constraints, the source SBOM also inventories locked npm versions "
            "when present, and the image SBOM lists Syft-observed installed components. "
            "Completeness is unknown; these records are not vulnerability, license, runtime reachability, publication, "
            "signature, SLSA-level, or external-platform-control evidence."
        ),
    }

    for artifact_id, content in rendered.items():
        _atomic_write(directory / output_names[artifact_id], content)
    manifest_path = directory / "sbom-manifest.v1.json"
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    checksum_paths = [*(directory / name for name in output_names.values()), manifest_path]
    checksum_lines = [f"{_sha256(path)}  {path.name}" for path in sorted(checksum_paths, key=lambda item: item.name)]
    _atomic_write(directory / "SBOM_SHA256SUMS", "\n".join(checksum_lines) + "\n")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--image-sbom-input", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--forbidden-path-prefix", action="append", default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        build_release_sboms(
            project_root=args.project_root,
            release_dir=args.release_dir,
            image_sbom_input=args.image_sbom_input,
            source_date_epoch=args.source_date_epoch,
            forbidden_path_prefixes=tuple(args.forbidden_path_prefix),
        )
    except (OSError, KeyError, TypeError, SbomBuildError) as exc:
        raise SystemExit(f"release SBOMs rejected: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
