import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_offline_attestations", ROOT / ".github/scripts/verify_offline_attestations.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(root: Path, relative: str, content: bytes = b"fixture") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _inventory(root: Path, name: str, entries: list[str]) -> None:
    (root / name).write_text(
        "".join(f"{_digest(root / entry)}  {entry}\n" for entry in entries), encoding="utf-8"
    )


def _fixture(root: Path) -> tuple[Path, Path]:
    primary = [
        "reconforge-erp-0.7.1-source.tar.gz",
        "reconforge_erp-0.7.1-py3-none-any.whl",
        "reconforge_erp-0.7.1.tar.gz",
        "release-manifest.v1.json",
    ]
    sboms = [
        "reconforge-erp-0.7.1-image.cdx.json",
        "reconforge-erp-0.7.1-source.cdx.json",
        "reconforge_erp-0.7.1-py3-none-any.cdx.json",
        "reconforge_erp-0.7.1-sdist.cdx.json",
        "sbom-manifest.v1.json",
    ]
    bundles = [
        "release/files-provenance.sigstore.json",
        "release/image-provenance.sigstore.json",
        "release/source-sbom.sigstore.json",
        "release/wheel-sbom.sigstore.json",
        "release/sdist-sbom.sigstore.json",
        "release/image-sbom.sigstore.json",
    ]
    manifest = {
        "schema_version": 1,
        "release": {
            "source_repository": "https://github.com/amrzainmubarak/reconforge-erp",
            "source_revision": "d47edd845e6aef3bae16e05698e07878086d690b",
            "tag": "v0.7.1",
        },
        "builder": {
            "runner_class": "github-hosted",
            "workflow_identity": "amrzainmubarak/reconforge-erp/.github/workflows/release.yml",
        },
        "artifacts": [
            {"id": "source-archive", "location": primary[0], "sha256": "1" * 64},
            {"id": "python-wheel", "location": primary[1], "sha256": "2" * 64},
            {"id": "python-sdist", "location": primary[2], "sha256": "3" * 64},
            {
                "id": "container-image",
                "location": "ghcr.io/amrzainmubarak/reconforge-erp@sha256:" + "4" * 64,
                "sha256": "4" * 64,
            },
        ],
    }
    for relative in [*primary[:-1], *sboms, *bundles]:
        _write(root, relative)
    _write(root, "release-manifest.v1.json", json.dumps(manifest).encode())
    _inventory(root, "SHA256SUMS", primary)
    _inventory(root, "SBOM_SHA256SUMS", sboms)
    _inventory(root, "ATTESTATION_SHA256SUMS", bundles)
    gh = _write(root, "tools/gh", b"trusted-gh")
    trusted_root = _write(root, "trusted_root.jsonl", b"trusted-root")
    return gh, trusted_root


def test_verifier_checks_all_offline_file_subjects_and_never_resolves_oci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh, trusted_root = _fixture(tmp_path)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(VERIFIER, "_run_json", lambda argv: calls.append(argv) or [{"verified": True}])
    result = VERIFIER.verify(
        tmp_path,
        gh,
        trusted_root,
        expected_gh_sha256=_digest(gh),
        expected_trusted_root_sha256=_digest(trusted_root),
    )
    assert result["file_provenance_subject_count"] == 11
    assert result["offline_file_sbom_attestation_count"] == 3
    assert result["offline_oci_attestation_count"] == 0
    assert result["oci_bundle_integrity_count"] == 2
    assert len(calls) == 14
    assert all(not any(argument.startswith("oci://") for argument in call) for call in calls)
    assert all("--source-digest" in call and "--deny-self-hosted-runners" in call for call in calls)


def test_verifier_fails_closed_on_tampered_subject(tmp_path: Path) -> None:
    gh, trusted_root = _fixture(tmp_path)
    _write(tmp_path, "reconforge_erp-0.7.1-py3-none-any.whl", b"tampered")
    with pytest.raises(RuntimeError, match="offline_attestation_checksum_mismatch"):
        VERIFIER.verify(
            tmp_path,
            gh,
            trusted_root,
            expected_gh_sha256=_digest(gh),
            expected_trusted_root_sha256=_digest(trusted_root),
        )


def test_checksum_inventory_rejects_path_traversal(tmp_path: Path) -> None:
    (tmp_path / "SHA256SUMS").write_text(f"{'0' * 64}  ../escape\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="offline_attestation_path_invalid"):
        VERIFIER._checksum_inventory(tmp_path, "SHA256SUMS")
