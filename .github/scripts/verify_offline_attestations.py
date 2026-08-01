"""Verify a ReconForge release evidence set without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404
from pathlib import Path, PurePosixPath
from typing import Any

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
REPOSITORY_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$")
PREDICATE_CYCLONEDX = "https://cyclonedx.org/bom"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise RuntimeError("offline_attestation_path_invalid")
    candidate = root.joinpath(*posix.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError("offline_attestation_file_missing_or_symlink")
    if root.resolve() not in candidate.resolve().parents:
        raise RuntimeError("offline_attestation_path_escape")
    return candidate


def _checksum_inventory(root: Path, name: str) -> list[str]:
    inventory = _safe_file(root, name)
    entries: list[str] = []
    seen: set[str] = set()
    for raw_line in inventory.read_text(encoding="utf-8").splitlines():
        parts = raw_line.split("  ", maxsplit=1)
        if len(parts) != 2 or not HEX_SHA256.fullmatch(parts[0]):
            raise RuntimeError("offline_attestation_checksum_line_invalid")
        expected, relative = parts
        if relative in seen:
            raise RuntimeError("offline_attestation_checksum_duplicate")
        target = _safe_file(root, relative)
        if _sha256(target) != expected:
            raise RuntimeError("offline_attestation_checksum_mismatch")
        seen.add(relative)
        entries.append(relative)
    if not entries:
        raise RuntimeError("offline_attestation_checksum_inventory_empty")
    return entries


def _load_manifest(root: Path) -> tuple[dict[str, Any], str, str, str, str]:
    payload = json.loads(_safe_file(root, "release-manifest.v1.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("offline_attestation_manifest_invalid")
    release = payload.get("release")
    builder = payload.get("builder")
    if not isinstance(release, dict) or not isinstance(builder, dict):
        raise RuntimeError("offline_attestation_manifest_invalid")
    repository_match = REPOSITORY_URL.fullmatch(str(release.get("source_repository", "")))
    revision = str(release.get("source_revision", ""))
    tag = str(release.get("tag", ""))
    workflow = str(builder.get("workflow_identity", ""))
    if (
        repository_match is None
        or not REVISION.fullmatch(revision)
        or not TAG.fullmatch(tag)
        or workflow != f"{repository_match.group(1)}/.github/workflows/release.yml"
        or builder.get("runner_class") != "github-hosted"
    ):
        raise RuntimeError("offline_attestation_identity_invalid")
    return payload, repository_match.group(1), revision, tag, workflow


def _run_json(argv: tuple[str, ...]) -> object:
    completed = subprocess.run(  # nosec B603
        argv,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("offline_attestation_verifier_output_invalid") from exc
    if not result:
        raise RuntimeError("offline_attestation_verifier_output_empty")
    return result


def verify(
    evidence_dir: Path,
    gh_binary: Path,
    trusted_root: Path,
    *,
    expected_gh_sha256: str,
    expected_trusted_root_sha256: str,
) -> dict[str, object]:
    root = evidence_dir.resolve()
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("offline_attestation_evidence_directory_invalid")
    if not HEX_SHA256.fullmatch(expected_gh_sha256) or _sha256(gh_binary) != expected_gh_sha256:
        raise RuntimeError("offline_attestation_verifier_digest_mismatch")
    if not HEX_SHA256.fullmatch(expected_trusted_root_sha256) or _sha256(trusted_root) != expected_trusted_root_sha256:
        raise RuntimeError("offline_attestation_trusted_root_digest_mismatch")

    primary = _checksum_inventory(root, "SHA256SUMS")
    sboms = _checksum_inventory(root, "SBOM_SHA256SUMS")
    bundles = _checksum_inventory(root, "ATTESTATION_SHA256SUMS")
    manifest, repository, revision, tag, workflow = _load_manifest(root)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeError("offline_attestation_manifest_invalid")
    by_id = {str(item.get("id")): item for item in artifacts if isinstance(item, dict)}
    required_ids = {"source-archive", "python-wheel", "python-sdist", "container-image"}
    if set(by_id) != required_ids:
        raise RuntimeError("offline_attestation_artifact_set_invalid")
    for artifact_id in required_ids:
        digest = str(by_id[artifact_id].get("sha256", ""))
        if not HEX_SHA256.fullmatch(digest):
            raise RuntimeError("offline_attestation_artifact_digest_invalid")

    common = (
        "--repo", repository,
        "--signer-workflow", workflow,
        "--signer-digest", revision,
        "--source-ref", f"refs/tags/{tag}",
        "--source-digest", revision,
        "--deny-self-hosted-runners",
        "--custom-trusted-root", str(trusted_root),
        "--format", "json",
    )
    file_subjects = list(dict.fromkeys([*primary, *sboms, "SHA256SUMS", "SBOM_SHA256SUMS"]))
    file_bundle = _safe_file(root, "release/files-provenance.sigstore.json")
    for relative in file_subjects:
        _run_json((str(gh_binary), "attestation", "verify", str(_safe_file(root, relative)), *common, "--bundle", str(file_bundle)))

    image = by_id["container-image"]
    image_location = str(image.get("location", ""))
    expected_location = f"ghcr.io/{repository}@sha256:{image['sha256']}"
    if image_location != expected_location:
        raise RuntimeError("offline_attestation_image_location_invalid")
    # gh 2.78 resolves OCI subjects against their registry even when --bundle is
    # local. An offline verifier must not silently enable network access, so the
    # two OCI attestations remain checksum-verified but are reported separately.
    sbom_bundles = {
        str(by_id["source-archive"].get("location", "")): "release/source-sbom.sigstore.json",
        str(by_id["python-wheel"].get("location", "")): "release/wheel-sbom.sigstore.json",
        str(by_id["python-sdist"].get("location", "")): "release/sdist-sbom.sigstore.json",
    }
    expected_sbom_files = {
        "reconforge-erp-0.7.1-source.cdx.json",
        "reconforge_erp-0.7.1-py3-none-any.cdx.json",
        "reconforge_erp-0.7.1-sdist.cdx.json",
        "reconforge-erp-0.7.1-image.cdx.json",
        "sbom-manifest.v1.json",
    }
    if set(sboms) != expected_sbom_files:
        raise RuntimeError("offline_attestation_sbom_set_invalid")
    for relative, bundle in sbom_bundles.items():
        _run_json(
            (
                str(gh_binary), "attestation", "verify", str(_safe_file(root, relative)), *common,
                "--predicate-type", PREDICATE_CYCLONEDX, "--bundle", str(_safe_file(root, bundle)),
            )
        )
    return {
        "attestation_bundle_count": len(bundles),
        "checksum_file_count": len(primary) + len(sboms) + len(bundles),
        "file_provenance_subject_count": len(file_subjects),
        "offline_oci_attestation_count": 0,
        "oci_bundle_integrity_count": 2,
        "repository": repository,
        "offline_file_sbom_attestation_count": len(sbom_bundles),
        "source_ref": f"refs/tags/{tag}",
        "source_revision": revision,
        "workflow": workflow,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--gh-binary", type=Path, required=True)
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--expected-gh-sha256", required=True)
    parser.add_argument("--expected-trusted-root-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(
        args.evidence_dir,
        args.gh_binary,
        args.trusted_root,
        expected_gh_sha256=args.expected_gh_sha256,
        expected_trusted_root_sha256=args.expected_trusted_root_sha256,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
