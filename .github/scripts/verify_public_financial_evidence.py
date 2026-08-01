"""Fetch or load pinned public financial inputs and emit a redacted evidence report."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from reconforge.benchmark.public_financial import (
    PUBLIC_DATA_HOSTS,
    ArtifactSpec,
    PublicFinancialEvidenceError,
    PublicFinancialEvidenceManifest,
    load_public_financial_manifest,
    run_public_financial_evidence,
)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_USER_AGENT = "ReconForge-public-financial-evidence/1"
_REDIRECT_HOSTS = {
    "admin.opendatani.gov.uk": frozenset({"83025b28472d6aa2bf5ae59f3724aa78.eu.r2.cloudflarestorage.com"}),
}
ExecutionScope = Literal["maintainer-local", "external-operator-candidate", "offline-replay"]


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    """Permit redirects only across the artifact's closed exact HTTPS host set."""

    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        source = urlsplit(req.full_url)
        target = urlsplit(newurl)
        allowed_targets = {source.hostname, *_REDIRECT_HOSTS.get(str(source.hostname), ())}
        if (
            target.scheme != "https"
            or target.hostname not in allowed_targets
            or target.port not in {None, 443}
            or target.username is not None
            or target.password is not None
        ):
            raise PublicFinancialEvidenceError("Public-data redirect left its exact allowlisted origin.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_artifact(spec: ArtifactSpec) -> tuple[bytes, dict[str, object]]:
    parsed = urlsplit(spec.url)
    if parsed.hostname not in PUBLIC_DATA_HOSTS:
        raise PublicFinancialEvidenceError("Public-data host is not allowlisted.")
    request = Request(
        spec.url,
        headers={
            "Accept": ", ".join(spec.allowed_content_types),
            "Accept-Encoding": "identity",
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    opener = build_opener(ProxyHandler({}), _SameOriginRedirectHandler())
    try:
        with opener.open(request, timeout=120) as response:  # noqa: S310 - exact HTTPS allowlist above
            final = urlsplit(response.geturl())
            allowed_final_hosts = {parsed.hostname, *_REDIRECT_HOSTS.get(str(parsed.hostname), ())}
            if final.scheme != "https" or final.hostname not in allowed_final_hosts or final.port not in {None, 443}:
                raise PublicFinancialEvidenceError("Public-data response left its exact allowlisted origin.")
            status = int(getattr(response, "status", 0))
            if status != 200:
                raise PublicFinancialEvidenceError("Public-data endpoint returned a non-success status.")
            content_type = response.headers.get_content_type().lower()
            if content_type not in spec.allowed_content_types:
                raise PublicFinancialEvidenceError(f"Artifact {spec.id} returned an unsupported content type.")
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise PublicFinancialEvidenceError("Public-data content length is malformed.") from exc
                if declared_length < 1 or declared_length > spec.max_bytes:
                    raise PublicFinancialEvidenceError(f"Artifact {spec.id} violates its declared size boundary.")
            content = response.read(spec.max_bytes + 1)
    except PublicFinancialEvidenceError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} could not be fetched safely.") from exc
    if not content or len(content) > spec.max_bytes:
        raise PublicFinancialEvidenceError(f"Artifact {spec.id} violates its bounded response size.")
    return content, {"id": spec.id, "status": status, "content_type": content_type, "bytes": len(content)}


def fetch_public_artifacts(
    manifest: PublicFinancialEvidenceManifest,
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    """Perform explicit bounded GETs for every manifest artifact."""

    contents: dict[str, bytes] = {}
    receipts: list[dict[str, object]] = []
    for spec in manifest.artifacts:
        content, receipt = _fetch_artifact(spec)
        contents[spec.id] = content
        receipts.append(receipt)
    return contents, receipts


def load_artifact_directory(
    manifest: PublicFinancialEvidenceManifest,
    directory: Path,
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    """Load an exact offline response set named ``<artifact-id>.<format>``."""

    expected_paths = {directory / f"{spec.id}.{spec.format}": spec for spec in manifest.artifacts}
    actual_paths = {path for path in directory.iterdir() if path.is_file()}
    if actual_paths != set(expected_paths):
        raise PublicFinancialEvidenceError("Offline artifact directory does not exactly match the manifest.")
    contents: dict[str, bytes] = {}
    receipts: list[dict[str, object]] = []
    for path, spec in expected_paths.items():
        content = path.read_bytes()
        contents[spec.id] = content
        receipts.append({"id": spec.id, "status": "offline", "content_type": "not-observed", "bytes": len(content)})
    return contents, receipts


def _source_revision(root: Path) -> str:
    completed = subprocess.run(  # nosec B603
        ("git", "rev-parse", "--verify", "HEAD"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    revision = completed.stdout.strip().lower()
    if completed.returncode != 0 or _COMMIT.fullmatch(revision) is None:
        raise PublicFinancialEvidenceError("Unable to bind the report to an exact source revision.")
    status = subprocess.run(  # nosec B603
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise PublicFinancialEvidenceError("Public evidence must run from a clean source revision.")
    return revision


def build_report(
    *,
    manifest: PublicFinancialEvidenceManifest,
    contents: dict[str, bytes],
    fetch_receipts: list[dict[str, object]],
    source_revision: str,
    execution_scope: ExecutionScope,
) -> dict[str, object]:
    """Run pure verification and add non-sensitive runtime provenance."""

    report = run_public_financial_evidence(manifest, contents)
    report["execution"] = {
        "executed_at": datetime.now(UTC).isoformat(),
        "scope": execution_scope,
        "source_revision": source_revision,
        "python": platform.python_version(),
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "machine": platform.machine(),
        "network_calls": len(fetch_receipts) if execution_scope != "offline-replay" else 0,
        "fetch_receipts": fetch_receipts,
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/validation/public-financial-evidence-manifest.v1.yaml"),
    )
    parser.add_argument("--output", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--allow-network", action="store_true")
    source.add_argument("--artifact-dir", type=Path)
    parser.add_argument(
        "--execution-scope",
        choices=("maintainer-local", "external-operator-candidate", "offline-replay"),
        default="maintainer-local",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_public_financial_manifest(args.manifest)
        root = Path(__file__).resolve().parents[2]
        if args.allow_network:
            if args.execution_scope == "offline-replay":
                raise PublicFinancialEvidenceError("Offline scope cannot enable network access.")
            contents, receipts = fetch_public_artifacts(manifest)
        else:
            if args.execution_scope != "offline-replay":
                raise PublicFinancialEvidenceError("Artifact-directory runs must use offline-replay scope.")
            contents, receipts = load_artifact_directory(manifest, args.artifact_dir)
        report = build_report(
            manifest=manifest,
            contents=contents,
            fetch_receipts=receipts,
            source_revision=_source_revision(root),
            execution_scope=args.execution_scope,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        args.output.write_bytes(serialized.encode("utf-8"))
    except (OSError, PublicFinancialEvidenceError) as exc:
        print(f"public financial evidence failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output), "status": "passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
