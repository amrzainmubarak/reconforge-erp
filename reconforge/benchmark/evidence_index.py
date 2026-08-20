"""Verify the checked-in benchmark evidence index without executing workloads."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

BENCHMARK_INDEX_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_CLAIMS = re.compile(
    r"\b(?:best globally|bank[- ]grade|enterprise[- ]ready|millions of transactions|production[- ]ready)\b",
    re.IGNORECASE,
)
_REQUIRED_ENTRY_KEYS = frozenset(
    {
        "artifact",
        "artifact_sha256",
        "claim_boundary",
        "digest_fields",
        "engine",
        "profile_id",
        "status",
        "workload_family",
    }
)


class BenchmarkEvidenceIndexError(ValueError):
    """Raised when checked-in benchmark evidence cannot be verified safely."""


def _canonical_artifact_bytes(artifact: Path) -> bytes:
    """Return the platform-independent bytes used for artifact provenance.

    Tracked JSON artifacts are declared as LF text in ``.gitattributes``.  A
    checkout on Windows can still expose CRLF bytes to a local verifier, so
    provenance must hash the canonical LF representation rather than the
    checkout's platform line endings.
    """

    return artifact.read_bytes().replace(b"\r\n", b"\n")


def _safe_artifact(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise BenchmarkEvidenceIndexError("benchmark artifact path must be a non-empty POSIX relative path")
    unresolved = root / relative
    if unresolved.is_symlink():
        raise BenchmarkEvidenceIndexError("benchmark artifact must not be a symlink")
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise BenchmarkEvidenceIndexError("benchmark artifact path escapes the benchmark root") from exc
    if candidate.suffix.casefold() != ".json" or not candidate.is_file():
        raise BenchmarkEvidenceIndexError("benchmark artifact must be an ordinary JSON file")
    return candidate


def _digest_at(document: object, field: object) -> str:
    if not isinstance(field, str) or not field or "." in field:
        raise BenchmarkEvidenceIndexError("benchmark digest field must be a direct JSON field")
    if not isinstance(document, dict):
        raise BenchmarkEvidenceIndexError("benchmark artifact must be a JSON object")
    value = document.get(field)
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise BenchmarkEvidenceIndexError(f"benchmark artifact digest field is invalid: {field}")
    return value


def verify_benchmark_index(index_path: Path | str, *, project_root: Path | str | None = None) -> dict[str, Any]:
    """Verify artifact paths, file hashes, profile identities, and claim boundaries."""

    index_file = Path(index_path).resolve()
    if project_root is not None:
        root = Path(project_root).resolve()
    elif index_file.parent.name == "benchmarks" and index_file.parent.parent.name == "execution":
        root = index_file.parents[3].resolve()
    else:
        root = index_file.parent.resolve()
    try:
        raw = json.loads(index_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkEvidenceIndexError("benchmark evidence index is not readable JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"index_id", "schema_version", "entries", "claim_boundary"}:
        raise BenchmarkEvidenceIndexError("benchmark evidence index has an unexpected top-level shape")
    if raw["index_id"] != "benchmark-evidence-index-v1" or raw["schema_version"] != BENCHMARK_INDEX_SCHEMA_VERSION:
        raise BenchmarkEvidenceIndexError("benchmark evidence index identity is unsupported")
    boundary = raw["claim_boundary"]
    if not isinstance(boundary, str) or not boundary.strip() or _FORBIDDEN_CLAIMS.search(boundary):
        raise BenchmarkEvidenceIndexError("benchmark evidence index claim boundary is invalid")
    entries = raw["entries"]
    if not isinstance(entries, list) or not entries:
        raise BenchmarkEvidenceIndexError("benchmark evidence index entries must be non-empty")

    seen_artifacts: set[str] = set()
    verified: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _REQUIRED_ENTRY_KEYS:
            raise BenchmarkEvidenceIndexError("benchmark evidence entry shape is not closed")
        artifact_name = entry["artifact"]
        if not isinstance(artifact_name, str) or artifact_name in seen_artifacts:
            raise BenchmarkEvidenceIndexError("benchmark evidence artifact paths must be unique")
        seen_artifacts.add(artifact_name)
        artifact = _safe_artifact(root, artifact_name)
        expected_sha = entry["artifact_sha256"]
        if not isinstance(expected_sha, str) or not _SHA256.fullmatch(expected_sha):
            raise BenchmarkEvidenceIndexError("benchmark artifact_sha256 is invalid")
        actual_sha = hashlib.sha256(_canonical_artifact_bytes(artifact)).hexdigest()
        if actual_sha != expected_sha:
            raise BenchmarkEvidenceIndexError(f"benchmark artifact hash mismatch: {artifact_name}")
        try:
            document = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BenchmarkEvidenceIndexError(f"benchmark artifact is not readable JSON: {artifact_name}") from exc
        if not isinstance(entry["profile_id"], str) or document.get("profile_id") != entry["profile_id"]:
            raise BenchmarkEvidenceIndexError(f"benchmark profile identity mismatch: {artifact_name}")
        status = entry["status"]
        if status not in {"observed", "verified", "partial"}:
            raise BenchmarkEvidenceIndexError(f"benchmark status is unsupported: {artifact_name}")
        fields = entry["digest_fields"]
        if not isinstance(fields, list) or not fields:
            raise BenchmarkEvidenceIndexError(f"benchmark digest field list is empty: {artifact_name}")
        digests = {field: _digest_at(document, field) for field in fields}
        claim = entry["claim_boundary"]
        if not isinstance(claim, str) or not claim.strip() or _FORBIDDEN_CLAIMS.search(claim):
            raise BenchmarkEvidenceIndexError(f"benchmark claim boundary is invalid: {artifact_name}")
        verified.append(
            {
                "artifact": artifact_name,
                "artifact_sha256": actual_sha,
                "profile_id": entry["profile_id"],
                "status": status,
                "digests": digests,
            }
        )
    return {"index_id": raw["index_id"], "schema_version": raw["schema_version"], "verified_entries": verified}


__all__ = ["BENCHMARK_INDEX_SCHEMA_VERSION", "BenchmarkEvidenceIndexError", "verify_benchmark_index"]
