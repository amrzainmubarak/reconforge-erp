from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import tarfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / ".github/fixtures/minio-source"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("build_minio_ci_fixture", ROOT / ".github/scripts/build_minio_ci_fixture.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, Any]:
    return json.loads((FIXTURE / "fixture.v1.json").read_text(encoding="utf-8"))


def test_minio_fixture_pins_official_source_and_preserves_ci_only_archived_boundary() -> None:
    manifest = _module().validate_manifest(_manifest())
    assert manifest["source_commit"] == "07c3a429bfed433e49018cb0f78a52145d4bedeb"
    assert manifest["source_archive_sha256"] == "8819e3e7817e46b7b3798f8f200ead208562e571563c2e040352378031abe9f2"
    assert manifest["scope"] == "synthetic-disposable-ci-only"
    assert manifest["upstream_status"] == "archived-unmaintained"
    recipe = (FIXTURE / "Dockerfile").read_text(encoding="utf-8")
    assert f"FROM {manifest['builder_image']} AS build" in recipe
    assert "FROM scratch" in recipe
    assert "GOTOOLCHAIN=local" in recipe
    assert "CGO_ENABLED=0" in recipe
    assert "-mod=readonly" in recipe
    assert "go mod verify" in recipe
    assert recipe.count("sha256sum -c /tmp/minio-module-locks.sha256") == 2
    assert "COPY --from=build /src/LICENSE /usr/share/licenses/minio/LICENSE" in recipe
    assert f"USER {manifest['runtime_user']}" in recipe
    assert "MINIO_UPDATE=off" in recipe
    assert "minio/minio:latest" not in recipe


@pytest.mark.parametrize(("field", "value"), [
    ("unexpected", True), ("schema_version", True), ("scope", "production"),
    ("upstream_status", "maintained"), ("license", "MIT"),
    ("source_commit", "master"), ("source_archive_sha256", "0" * 63),
    ("source_archive_url", "https://example.com/minio.tar.gz"),
    ("source_release", "latest"), ("builder_image", "golang:latest"),
    ("go_version", "go1.27"), ("runtime_base", "ubuntu:latest"),
    ("runtime_user", "0:0"), ("runtime_identity_kind", "oci-manifest"),
])
def test_minio_fixture_rejects_unpinned_or_misrepresented_contract(field: str, value: object) -> None:
    module = _module()
    manifest = deepcopy(_manifest())
    manifest[field] = value
    with pytest.raises(module.FixtureBuildError):
        module.validate_manifest(manifest)


def test_minio_fixture_rejects_source_tampering_before_archive_processing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"substituted source")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unverified source reached archive processing")

    monkeypatch.setattr(module.tarfile, "open", forbidden)
    with pytest.raises(module.FixtureBuildError, match="SHA256"):
        module.verify_archive(archive, _manifest())


@pytest.mark.parametrize("mutation", ["digest", "release", "commit", "go"])
def test_minio_fixture_refuses_wrong_built_identity(mutation: str) -> None:
    module = _module()
    manifest = _manifest()
    image_id = "sha256:" + "a" * 64
    version = f"minio version {manifest['source_release']} (commit-id={manifest['source_commit']})\nRuntime: {manifest['go_version']} linux/amd64"
    if mutation == "digest":
        image_id = "reconforge-minio-ci:latest"
    else:
        field = {"release": "source_release", "commit": "source_commit", "go": "go_version"}[mutation]
        version = version.replace(manifest[field], "unexpected")
    with pytest.raises(module.FixtureBuildError):
        module.verify_runtime_identity(image_id, version, manifest)


def test_minio_fixture_accepts_verified_version_commit_toolchain_and_config_digest() -> None:
    module = _module()
    manifest = _manifest()
    version = f"minio version {manifest['source_release']} (commit-id={manifest['source_commit']})\nRuntime: {manifest['go_version']} linux/amd64"
    module.verify_runtime_identity("sha256:" + "a" * 64, version, manifest)


def test_build_provenance_binds_the_recipe_snapshot_actually_passed_to_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    manifest = _manifest()
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in ("LICENSE", "go.mod", "go.sum"):
            content = f"synthetic {name}".encode()
            entry = tarfile.TarInfo(f"minio-{manifest['source_commit']}/{name}")
            entry.size = len(content)
            bundle.addfile(entry, io.BytesIO(content))
    manifest["source_archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    manifest_bytes = json.dumps(manifest).encode()
    recipe_bytes = (FIXTURE / "Dockerfile").read_bytes()
    (fixture / "fixture.v1.json").write_bytes(manifest_bytes)
    (fixture / "Dockerfile").write_bytes(recipe_bytes)
    monkeypatch.setattr(module, "FIXTURE_DIRECTORY", fixture)
    monkeypatch.setattr(module, "_download", lambda _manifest, target: shutil.copyfile(archive, target))

    def run(command: list[str], **options: Any) -> SimpleNamespace:
        if command[1] == "build":
            assert (Path(command[-1]) / "Dockerfile").read_bytes() == recipe_bytes
            Path(command[command.index("--iidfile") + 1]).write_text("sha256:" + "a" * 64, encoding="utf-8")
            (fixture / "fixture.v1.json").write_text("changed during build", encoding="utf-8")
            (fixture / "Dockerfile").write_text("changed during build", encoding="utf-8")
        version = f"minio version {manifest['source_release']} (commit-id={manifest['source_commit']})\nRuntime: {manifest['go_version']} linux/amd64"
        return SimpleNamespace(stdout=version)

    monkeypatch.setattr(module.subprocess, "run", run)
    report = module.build_fixture(tmp_path / "provenance.json", tmp_path / "image.iid")
    assert report["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert report["recipe_sha256"] == hashlib.sha256(recipe_bytes).hexdigest()
    assert report["image_config_digest"] == "sha256:" + "a" * 64
