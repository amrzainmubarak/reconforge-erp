from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.sovereign.offline_bundle import OfflineBundleError, verify_offline_bundle

ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "offline-bundle"
    files = {
        "wheelhouse/reconforge_erp-0.7.1-py3-none-any.whl": b"synthetic application wheel",
        "wheelhouse/pydantic-2.11.0-py3-none-any.whl": b"synthetic dependency wheel",
        "requirements.lock": (
            b"reconforge-erp[server,backup]==0.7.1 --hash=sha256:"
            + b"a" * 64
            + b"\npydantic==2.11.0 --hash=sha256:"
            + b"b" * 64
            + b"\n"
        ),
        "release/release-manifest.v1.json": b'{"synthetic":true}\n',
        "release/files-provenance.sigstore.json": b'{"synthetic":true}\n',
    }
    roles = {
        "wheelhouse/reconforge_erp-0.7.1-py3-none-any.whl": "application-wheel",
        "wheelhouse/pydantic-2.11.0-py3-none-any.whl": "dependency-wheel",
        "requirements.lock": "requirements-lock",
        "release/release-manifest.v1.json": "release-manifest",
        "release/files-provenance.sigstore.json": "provenance-bundle",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "schema": "reconforge-offline-bundle-v1",
        "bundle_id": "synthetic-offline-071",
        "application_version": "0.7.1",
        "python_tag": "cp314",
        "platform_tag": "win_amd64",
        "install": {
            "installer": "pip-no-index-v1",
            "requirements_path": "requirements.lock",
            "application_requirement": "reconforge-erp[server,backup]==0.7.1",
            "network_policy": "deny-all",
            "index_policy": "no-index",
        },
        "entries": [
            {"path": relative, "role": roles[relative], "size": len(content), "sha256": _sha256(content)}
            for relative, content in sorted(files.items())
        ],
        "claim_boundary": "Local artifact integrity only; external signature trust, installation success, and production readiness require separate evidence.",
    }
    manifest_path = root / "offline-bundle.v1.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest_path


def test_offline_bundle_schema_and_runtime_contract_agree(tmp_path: Path) -> None:
    schema = json.loads((ROOT / "docs/schemas/offline_bundle.schema.json").read_text(encoding="utf-8"))
    manifest_path = _bundle(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)

    verified = verify_offline_bundle(manifest_path)

    assert verified.entry_count == 5
    assert verified.application_version == "0.7.1"
    assert verified.install_argv[3:7] == ("install", "--no-index", "--disable-pip-version-check", "--no-deps")
    assert "http" not in " ".join(verified.install_argv).lower()


@pytest.mark.parametrize("mutation", ["tamper", "extra", "url", "unhashed", "duplicate", "escape"])
def test_offline_bundle_fails_closed_for_hostile_or_open_inventory(tmp_path: Path, mutation: str) -> None:
    manifest_path = _bundle(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "tamper":
        (manifest_path.parent / payload["entries"][0]["path"]).write_bytes(b"tampered")
    elif mutation == "extra":
        (manifest_path.parent / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    elif mutation in {"url", "unhashed"}:
        requirements = manifest_path.parent / "requirements.lock"
        requirements.write_text(
            "reconforge-erp[server,backup]==0.7.1 https://example.invalid/pkg.whl"
            if mutation == "url"
            else "reconforge-erp[server,backup]==0.7.1",
            encoding="utf-8",
        )
        content = requirements.read_bytes()
        entry = next(item for item in payload["entries"] if item["role"] == "requirements-lock")
        entry.update(size=len(content), sha256=_sha256(content))
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "duplicate":
        payload["entries"].append(payload["entries"][0])
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload["entries"][0]["path"] = "../escape.whl"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OfflineBundleError):
        verify_offline_bundle(manifest_path)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation requires an external privilege")
def test_offline_bundle_rejects_symlinked_content(tmp_path: Path) -> None:
    manifest_path = _bundle(tmp_path)
    target = manifest_path.parent / "release/release-manifest.v1.json"
    target.unlink()
    target.symlink_to(manifest_path)
    with pytest.raises(OfflineBundleError, match="symlink"):
        verify_offline_bundle(manifest_path)
