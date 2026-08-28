from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCRIPT = ROOT / ".github" / "scripts" / "build_release_manifest.py"
SBOM_SCRIPT = ROOT / ".github" / "scripts" / "build_release_sboms.py"
SBOM_SCHEMA = json.loads((ROOT / "docs" / "schemas" / "sbom_manifest.schema.json").read_text(encoding="utf-8"))
VERSION = "0.7.0"
REVISION = "a" * 40
IMAGE_DIGEST = "b" * 64
SOURCE_DATE_EPOCH = 1_700_000_000
IMAGE_REPOSITORY = "ghcr.io/amrzainmubarak/reconforge-erp"
REQUIREMENTS = ["fastapi>=0.111", 'pytest>=8.2; extra == "dev"']
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
LEGACY_SBOM_WORKFLOW = ROOT / ".github" / "workflows" / "sbom.yml"


def _add_tar_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def _add_tar_directory(archive: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = 0
    archive.addfile(info)


def _candidate_files(
    directory: Path,
    *,
    wheel_requirements: list[str] | None = None,
    lock_root_dependencies: dict[str, str] | None = None,
) -> None:
    directory.mkdir(parents=True)
    pyproject = b"""[project]
name = "reconforge-erp"
version = "0.7.0"
dependencies = ["fastapi>=0.111"]

[project.optional-dependencies]
dev = ["pytest>=8.2"]
"""
    source_root = f"reconforge-erp-{VERSION}"
    with tarfile.open(directory / f"{source_root}-source.tar.gz", "w:gz") as archive:
        _add_tar_directory(archive, source_root)
        _add_tar_file(archive, f"{source_root}/pyproject.toml", pyproject)
        package = {
            "name": "@reconforge/studio-web",
            "version": "0.1.0",
            "dependencies": {"react": "^19.2.8"},
        }
        lock_root = dict(package)
        if lock_root_dependencies is not None:
            lock_root["dependencies"] = lock_root_dependencies
        package_lock = {
            "name": "@reconforge/studio-web",
            "version": "0.1.0",
            "lockfileVersion": 3,
            "packages": {
                "": lock_root,
                "node_modules/react": {
                    "version": "19.2.8",
                    "license": "MIT",
                    "integrity": f"sha512-{base64.b64encode(bytes(range(64))).decode()}",
                },
            },
        }
        _add_tar_file(archive, f"{source_root}/apps/web/package.json", json.dumps(package).encode())
        _add_tar_file(archive, f"{source_root}/apps/web/package-lock.json", json.dumps(package_lock).encode())

    metadata_requirements = REQUIREMENTS if wheel_requirements is None else wheel_requirements
    wheel_metadata = (
        f"Metadata-Version: 2.4\nName: reconforge-erp\nVersion: {VERSION}\n"
        + "".join(f"Requires-Dist: {requirement}\n" for requirement in metadata_requirements)
    )
    wheel_name = f"reconforge_erp-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(directory / wheel_name, "w") as archive:
        archive.writestr(f"reconforge_erp-{VERSION}.dist-info/METADATA", wheel_metadata)

    sdist_root = f"reconforge_erp-{VERSION}"
    sdist_metadata = (
        f"Metadata-Version: 2.4\nName: reconforge-erp\nVersion: {VERSION}\n"
        + "".join(f"Requires-Dist: {requirement}\n" for requirement in REQUIREMENTS)
    ).encode()
    with tarfile.open(directory / f"{sdist_root}.tar.gz", "w:gz") as archive:
        _add_tar_directory(archive, sdist_root)
        _add_tar_file(archive, f"{sdist_root}/PKG-INFO", sdist_metadata)


def _ensure_test_project(project_root: Path) -> None:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(
            '[project]\nname = "reconforge-erp"\nversion = "0.7.0"\n',
            encoding="utf-8",
        )


def _run_release_manifest(directory: Path) -> subprocess.CompletedProcess[str]:
    project_root = directory.parent
    _ensure_test_project(project_root)
    return subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--project-root",
            str(project_root),
            "--release-dir",
            str(directory),
            "--tag",
            f"v{VERSION}",
            "--source-revision",
            REVISION,
            "--source-date-epoch",
            str(SOURCE_DATE_EPOCH),
            "--image-subject",
            f"{IMAGE_REPOSITORY}@sha256:{IMAGE_DIGEST}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _raw_image_sbom(*, variable: str, forbidden_path: str | None = None, duplicate_ref: bool = False) -> dict[str, object]:
    first_ref = "pkg:pypi/fastapi@0.111.0"
    second_ref = first_ref if duplicate_ref else "pkg:pypi/uvicorn@0.30.0"
    metadata: dict[str, object] = {
        "timestamp": f"2025-01-01T00:00:0{variable}Z",
        "tools": {
            "components": [
                {
                    "type": "application",
                    "author": "anchore",
                    "name": "syft",
                    "version": "1.51.0",
                }
            ]
        },
        "component": {
            "bom-ref": f"random-root-{variable}",
            "type": "container",
            "name": IMAGE_REPOSITORY,
            "version": VERSION,
        },
    }
    if forbidden_path:
        metadata["properties"] = [{"name": "test:path", "value": f"{forbidden_path}/extract"}]
    components = [
        {
            "bom-ref": first_ref,
            "type": "library",
            "name": "fastapi",
            "version": "0.111.0",
            "properties": [
                {"name": "syft:package:type", "value": "python"},
                {"name": "syft:package:language", "value": "python"},
            ],
        },
        {
            "bom-ref": second_ref,
            "type": "library",
            "name": "uvicorn",
            "version": "0.30.0",
        },
    ]
    if variable == "2":
        components.reverse()
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.7.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:00000000-0000-4000-8000-00000000000{variable}",
        "version": 1,
        "metadata": metadata,
        "components": components,
        "dependencies": [
            {"ref": second_ref, "dependsOn": []},
            {"ref": f"random-root-{variable}", "dependsOn": [second_ref, first_ref]},
            {"ref": first_ref, "dependsOn": []},
        ],
    }


def _write_raw_image(path: Path, **kwargs: object) -> None:
    path.write_text(json.dumps(_raw_image_sbom(**kwargs)), encoding="utf-8")


def _run_sbom(directory: Path, raw_image: Path, *, forbidden_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
    project_root = directory.parent
    _ensure_test_project(project_root)
    command = [
        sys.executable,
        str(SBOM_SCRIPT),
        "--project-root",
        str(project_root),
        "--release-dir",
        str(directory),
        "--image-sbom-input",
        str(raw_image),
        "--source-date-epoch",
        str(SOURCE_DATE_EPOCH),
    ]
    if forbidden_prefix is not None:
        command.extend(["--forbidden-path-prefix", str(forbidden_prefix)])
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def _prepare_release(directory: Path, *, wheel_requirements: list[str] | None = None) -> None:
    _candidate_files(directory, wheel_requirements=wheel_requirements)
    result = _run_release_manifest(directory)
    assert result.returncode == 0, result.stderr


def test_release_sboms_are_deterministic_subject_bound_and_schema_valid(tmp_path: Path) -> None:
    base = tmp_path / "base"
    _candidate_files(base)
    left = tmp_path / "left"
    right = tmp_path / "right"
    shutil.copytree(base, left)
    shutil.copytree(base, right)
    for directory in (left, right):
        result = _run_release_manifest(directory)
        assert result.returncode == 0, result.stderr

    left_raw = tmp_path / "left-image.json"
    right_raw = tmp_path / "right-image.json"
    _write_raw_image(left_raw, variable="1")
    _write_raw_image(right_raw, variable="2")
    first = _run_sbom(left, left_raw)
    second = _run_sbom(right, right_raw)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    manifest_name = "sbom-manifest.v1.json"
    left_manifest = json.loads((left / manifest_name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(SBOM_SCHEMA).validate(left_manifest)
    assert [entry["id"] for entry in left_manifest["sboms"]] == [
        "source-archive",
        "python-wheel",
        "python-sdist",
        "container-image",
    ]
    assert {entry["completeness"] for entry in left_manifest["sboms"]} == {"unknown"}
    assert left_manifest["generator_policy"]["image_generator"] == "syft@1.51.0"

    for entry in left_manifest["sboms"]:
        sbom_path = left / entry["sbom"]["name"]
        assert hashlib.sha256(sbom_path.read_bytes()).hexdigest() == entry["sbom"]["sha256"]
        document = json.loads(sbom_path.read_text(encoding="utf-8"))
        assert document["bomFormat"] == "CycloneDX"
        assert document["specVersion"] == "1.7"
        assert document["metadata"]["timestamp"] == "2023-11-14T22:13:20Z"
        subject = document["metadata"]["component"]
        assert subject["hashes"] == [{"alg": "SHA-256", "content": entry["subject"]["sha256"]}]
        assert subject["name"] == entry["subject"]["name"]
        right_bytes = (right / entry["sbom"]["name"]).read_bytes()
        assert sbom_path.read_bytes() == right_bytes

    source_document = json.loads((left / left_manifest["sboms"][0]["sbom"]["name"]).read_text(encoding="utf-8"))
    assert {component["name"] for component in source_document["components"]} == {"fastapi", "pytest", "react"}
    python_components = [
        component
        for component in source_document["components"]
        if any(prop["name"] == "reconforge:python:resolution" for prop in component["properties"])
    ]
    assert all("version" not in component for component in python_components)
    assert all(
        {prop["name"]: prop["value"] for prop in component["properties"]}[
            "reconforge:python:resolution"
        ]
        == "unresolved"
        for component in python_components
    )
    react = next(component for component in source_document["components"] if component["name"] == "react")
    assert react["version"] == "19.2.8"
    assert react["hashes"] == [{"alg": "SHA-512", "content": bytes(range(64)).hex()}]
    assert left_manifest["sboms"][0]["generation_mode"] == "declared-python-and-locked-npm-metadata"
    assert (left / manifest_name).read_bytes() == (right / manifest_name).read_bytes()
    assert (left / "SBOM_SHA256SUMS").read_bytes() == (right / "SBOM_SHA256SUMS").read_bytes()


def test_release_sboms_reject_python_metadata_drift_before_writing(tmp_path: Path) -> None:
    release_dir = tmp_path / "metadata-drift"
    _prepare_release(release_dir, wheel_requirements=["fastapi>=0.111"])
    raw_image = tmp_path / "image.json"
    _write_raw_image(raw_image, variable="1")

    result = _run_sbom(release_dir, raw_image)
    assert result.returncode != 0
    assert "wheel Requires-Dist does not exactly match source declarations" in result.stderr
    assert not list(release_dir.glob("*.cdx.json"))
    assert not (release_dir / "sbom-manifest.v1.json").exists()

    lock_drift = tmp_path / "lock-drift"
    _candidate_files(lock_drift, lock_root_dependencies={"react": "^18.0.0"})
    release_result = _run_release_manifest(lock_drift)
    assert release_result.returncode == 0, release_result.stderr
    lock_result = _run_sbom(lock_drift, raw_image)
    assert lock_result.returncode != 0
    assert "package-lock.json root dependencies does not match package.json" in lock_result.stderr
    assert not list(lock_drift.glob("*.cdx.json"))


def test_release_sboms_reject_host_path_disclosure_and_duplicate_refs(tmp_path: Path) -> None:
    release_dir = tmp_path / "invalid-image"
    _prepare_release(release_dir)
    runner_temp = tmp_path / "runner-secret-path"
    raw_image = tmp_path / "path-image.json"
    _write_raw_image(raw_image, variable="1", forbidden_path=str(runner_temp))

    disclosed = _run_sbom(release_dir, raw_image, forbidden_prefix=runner_temp)
    assert disclosed.returncode != 0
    assert "forbidden host path" in disclosed.stderr
    assert not list(release_dir.glob("*.cdx.json"))

    _write_raw_image(raw_image, variable="1", duplicate_ref=True)
    duplicate = _run_sbom(release_dir, raw_image)
    assert duplicate.returncode != 0
    assert "bom-ref values must be unique" in duplicate.stderr
    assert not list(release_dir.glob("*.cdx.json"))


def test_release_sboms_reject_release_artifact_digest_drift(tmp_path: Path) -> None:
    release_dir = tmp_path / "digest-drift"
    _prepare_release(release_dir)
    wheel = release_dir / f"reconforge_erp-{VERSION}-py3-none-any.whl"
    wheel.write_bytes(wheel.read_bytes() + b"tamper")
    raw_image = tmp_path / "image.json"
    _write_raw_image(raw_image, variable="1")

    result = _run_sbom(release_dir, raw_image)
    assert result.returncode != 0
    assert "python-wheel digest does not match" in result.stderr
    assert not list(release_dir.glob("*.cdx.json"))

    identity_drift = tmp_path / "identity-drift"
    _prepare_release(identity_drift)
    manifest_path = identity_drift / "release-manifest.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][1]["media_type"] = "application/octet-stream"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    identity_result = _run_sbom(identity_drift, raw_image)
    assert identity_result.returncode != 0
    assert "python-wheel metadata is invalid" in identity_result.stderr
    assert not list(identity_drift.glob("*.cdx.json"))

    atomic_guard = tmp_path / "atomic-guard"
    _prepare_release(atomic_guard)
    temporary = atomic_guard / f".reconforge-erp-{VERSION}-source.cdx.json.tmp"
    temporary.write_text("pre-existing sentinel", encoding="utf-8")
    atomic_result = _run_sbom(atomic_guard, raw_image)
    assert atomic_result.returncode != 0
    assert temporary.read_text(encoding="utf-8") == "pre-existing sentinel"
    assert not list(atomic_guard.glob("*.cdx.json"))


def test_release_workflow_pins_scans_attests_and_verifies_each_sbom_subject() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert not LEGACY_SBOM_WORKFLOW.exists()
    for required in [
        'SYFT_VERSION: "1.51.0"',
        "SYFT_COMMIT: 2293641e3bd628a01bb37639318d62c0ebe89b39",
        "SYFT_LINUX_AMD64_SHA256: 2a2e837a2c8d59ec9af5472ee22d3b04ee463c4e44476ecf993fd1e5ab6ebc7f",
        'curl --fail --location --silent --show-error --proto \'=https\' --tlsv1.2 --retry 3',
        'printf \'%s  %s\\n\' "$SYFT_LINUX_AMD64_SHA256" "$syft_archive_path" | sha256sum --check --strict',
        'GRYPE_VERSION: "0.117.0"',
        "GRYPE_COMMIT: b5fa92bbcbef655497e3be840a2f718380e2cdd3",
        "GRYPE_LINUX_AMD64_SHA256: 38525dab1e06f162ebaa02f94d82d1f807076b011a44180cf2777edf1a7b9c26",
        '"sbom:${RUNNER_TEMP}/image.syft.json"',
        "python .github/scripts/validate_container_security.py",
        'cyclonedx-json=${RUNNER_TEMP}/image-syft.raw.cdx.json',
        "python .github/scripts/build_release_sboms.py",
        "--forbidden-path-prefix \"$RUNNER_TEMP\"",
        "--forbidden-path-prefix \"$GITHUB_WORKSPACE\"",
        "--predicate-type \"$SBOM_PREDICATE_TYPE\"",
        "sha256sum --check SBOM_SHA256SUMS",
        "sha256sum release/*sigstore.json > release/ATTESTATION_SHA256SUMS",
    ]:
        assert required in raw
    assert raw.count("sbom-path:") == 4
    assert raw.count("create-storage-record: false") == 6
    assert raw.count('--predicate-type "$SBOM_PREDICATE_TYPE"') == 4
    assert raw.count("-sbom.sigstore.json") >= 8
    assert "pip install cyclonedx-bom" not in raw
    assert "curl |" not in raw and "curl|" not in raw
