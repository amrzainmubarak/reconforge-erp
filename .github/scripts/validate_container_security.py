#!/usr/bin/env python3
"""Build subject-bound, fail-closed container security evidence.

The release path deliberately scans Syft's native JSON rather than a converted
SBOM. The native document retains distro, package, and image identities needed
by Grype. CycloneDX remains the portable release SBOM, but is not treated as a
lossless vulnerability-scanner interchange format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from itertools import chain
from pathlib import Path
from typing import Any

from validate_supply_chain_policy import SupplyChainPolicyError, validate_project

IMAGE_REPOSITORY = "ghcr.io/amrzainmubarak/reconforge-erp"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
DB_SCHEMA = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
CVE = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
MAX_INPUT_BYTES = 256 * 1024 * 1024
SEVERITIES = ("Critical", "High", "Medium", "Low", "Negligible", "Unknown")


class ContainerSecurityError(ValueError):
    """Raised when scanner evidence is incomplete, ambiguous, or unsafe."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContainerSecurityError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ContainerSecurityError(f"{label} must be one regular non-link file")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_INPUT_BYTES:
        raise ContainerSecurityError(f"{label} size is outside the closed input bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContainerSecurityError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContainerSecurityError(f"{label} root must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContainerSecurityError(f"{label} must be a non-empty RFC 3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ContainerSecurityError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContainerSecurityError(f"{label} must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            temporary.unlink(missing_ok=True)


def _matching_exception(
    active: list[dict[str, Any]], *, subject: str, identifiers: set[str]
) -> str | None:
    normalized = subject.casefold().replace("_", "-")
    for item in active:
        candidate = str(item.get("subject", "")).casefold().replace("_", "-")
        if (
            item.get("ecosystem") == "container"
            and item.get("kind") == "vulnerability"
            and candidate == normalized
            and identifiers.intersection(str(value) for value in item.get("identifiers", []))
        ):
            return str(item["id"])
    return None


def _license_inventory(
    artifacts: list[Any], *, minimum_percent: int
) -> tuple[dict[str, Any], list[str]]:
    if not artifacts:
        raise ContainerSecurityError("Syft inventory must contain at least one package artifact")
    licensed = 0
    missing: list[str] = []
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ContainerSecurityError("Syft package artifact is malformed")
        identity = item.get("id")
        name = item.get("name")
        version = item.get("version")
        package_type = item.get("type")
        purl = item.get("purl")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in seen
            or not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or not isinstance(package_type, str)
            or not package_type
            or not isinstance(purl, str)
            or not purl.startswith("pkg:")
        ):
            raise ContainerSecurityError("Syft package identity is incomplete or duplicated")
        seen.add(identity)
        licenses = item.get("licenses")
        if not isinstance(licenses, list):
            raise ContainerSecurityError(f"Syft licenses are malformed for {name}")
        valid = bool(licenses)
        for license_record in licenses:
            if not isinstance(license_record, dict) or not any(
                isinstance(license_record.get(field), str) and license_record[field].strip()
                for field in ("spdxExpression", "value")
            ):
                raise ContainerSecurityError(f"Syft license record is malformed for {name}")
        if valid:
            licensed += 1
        else:
            missing.append(f"{name}@{version}")
    coverage_basis_points = licensed * 10_000 // len(artifacts)
    minimum_basis_points = minimum_percent * 100
    blockers = []
    if coverage_basis_points < minimum_basis_points:
        blockers.append(
            f"license inventory coverage {coverage_basis_points}bp is below {minimum_basis_points}bp"
        )
    return (
        {
            "coverage_basis_points": coverage_basis_points,
            "legal_compatibility_assessed": False,
            "licensed_packages": licensed,
            "minimum_coverage_basis_points": minimum_basis_points,
            "missing_license_packages": sorted(missing),
            "total_packages": len(artifacts),
        },
        blockers,
    )


def _validate_syft(
    document: dict[str, Any],
    *,
    policy: dict[str, Any],
    image_config_digest: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    sbom_policy = policy["container_audits"]["sbom"]
    descriptor = document.get("descriptor")
    source = document.get("source")
    distro = document.get("distro")
    schema = document.get("schema")
    artifacts = document.get("artifacts")
    if not isinstance(descriptor, dict) or (
        descriptor.get("name"), descriptor.get("version")
    ) != (sbom_policy["tool"], sbom_policy["version"]):
        raise ContainerSecurityError("Syft descriptor does not match the pinned tool")
    configuration = descriptor.get("configuration")
    if (
        not isinstance(configuration, dict)
        or configuration.get("search", {}).get("scope") != sbom_policy["scan_scope"]
        or configuration.get("licenses", {}).get("coverage") != sbom_policy["license_content_coverage"]
    ):
        raise ContainerSecurityError("Syft scan scope or license-content coverage drifted")
    if (
        not isinstance(schema, dict)
        or schema.get("version") != sbom_policy["native_schema_version"]
        or not isinstance(source, dict)
        or source.get("type") != "image"
        or source.get("name") != IMAGE_REPOSITORY
    ):
        raise ContainerSecurityError("Syft native schema or image source identity drifted")
    metadata = source.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("imageID") != image_config_digest
        or not isinstance(metadata.get("manifestDigest"), str)
        or SHA256.fullmatch(metadata["manifestDigest"]) is None
        or metadata.get("architecture") != "amd64"
        or metadata.get("os") != "linux"
    ):
        raise ContainerSecurityError("Syft image configuration, manifest, or platform identity drifted")
    if not isinstance(distro, dict) or not isinstance(distro.get("id"), str) or not distro["id"]:
        raise ContainerSecurityError("Syft inventory must retain a distro identity")
    if not isinstance(artifacts, list):
        raise ContainerSecurityError("Syft artifacts must be an array")
    licenses, blockers = _license_inventory(
        artifacts, minimum_percent=sbom_policy["minimum_license_coverage_percent"]
    )
    return (
        {
            "config_digest": image_config_digest,
            "distro": {"id": distro["id"], "version": str(distro.get("versionID", ""))},
            "local_manifest_digest": metadata["manifestDigest"],
            "platform": "linux/amd64",
            "source_name": source["name"],
            "source_version": str(source.get("version", "")),
        },
        licenses,
        blockers,
    )


def _validate_vex(
    document: dict[str, Any],
    *,
    policy: dict[str, Any],
    artifact_purls: set[str],
    document_sha256: str,
    as_of: date,
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, Any]]:
    audit_policy = policy["container_audits"]["vulnerability"]
    if document_sha256 != audit_policy["vex_document_sha256"]:
        raise ContainerSecurityError("OpenVEX document hash does not match the reviewed policy")
    required_root = {
        "@context",
        "@id",
        "author",
        "last_updated",
        "role",
        "statements",
        "timestamp",
        "version",
    }
    if set(document) != required_root:
        raise ContainerSecurityError("OpenVEX root must match the closed reviewed contract")
    document_id = document.get("@id")
    author = document.get("author")
    if (
        document.get("@context") != audit_policy["vex_context"]
        or not isinstance(document_id, str)
        or not document_id.startswith("https://reconforge.local/security/vex/")
        or not isinstance(author, str)
        or len(author) < 10
        or document.get("role") != "Document Creator"
        or document.get("version") != 1
    ):
        raise ContainerSecurityError("OpenVEX identity or version is outside policy")
    created_at = _timestamp(document.get("timestamp"), label="OpenVEX timestamp")
    updated_at = _timestamp(document.get("last_updated"), label="OpenVEX last_updated")
    if updated_at < created_at or updated_at.date() > as_of:
        raise ContainerSecurityError("OpenVEX review timestamps are inconsistent or in the future")
    review_age_days = (as_of - updated_at.date()).days
    if review_age_days > audit_policy["vex_max_review_age_days"]:
        raise ContainerSecurityError("OpenVEX review is older than the closed policy permits")
    statements = document.get("statements")
    if not isinstance(statements, list) or not statements:
        raise ContainerSecurityError("OpenVEX must contain at least one reviewed statement")
    decisions: dict[tuple[str, str], dict[str, str]] = {}
    for index, statement in enumerate(statements):
        if not isinstance(statement, dict) or set(statement) != {
            "impact_statement",
            "products",
            "status",
            "vulnerability",
        }:
            raise ContainerSecurityError(f"OpenVEX statement {index} has unreviewed fields")
        vulnerability = statement.get("vulnerability")
        products = statement.get("products")
        status = statement.get("status")
        impact = statement.get("impact_statement")
        if (
            not isinstance(vulnerability, dict)
            or set(vulnerability) != {"name"}
            or not isinstance(vulnerability.get("name"), str)
            or CVE.fullmatch(vulnerability["name"]) is None
            or not isinstance(status, str)
            or status not in audit_policy["vex_allowed_statuses"]
            or not isinstance(impact, str)
            or len(impact) < 80
            or not isinstance(products, list)
            or not products
        ):
            raise ContainerSecurityError(f"OpenVEX statement {index} is incomplete")
        for product in products:
            if not isinstance(product, dict) or set(product) != {"@id"}:
                raise ContainerSecurityError(f"OpenVEX statement {index} product is not exact")
            purl = product.get("@id")
            if not isinstance(purl, str) or purl not in artifact_purls:
                raise ContainerSecurityError(
                    f"OpenVEX statement {index} product is absent from the exact image inventory"
                )
            key = (vulnerability["name"], purl)
            if key in decisions:
                raise ContainerSecurityError("OpenVEX contains a duplicate vulnerability/product decision")
            decisions[key] = {
                "document_id": document_id,
                "status": status,
            }
    return (
        decisions,
        {
            "applied_fixed_findings": 0,
            "author": author,
            "document_id": document_id,
            "document_sha256": document_sha256,
            "last_updated": _canonical_timestamp(updated_at),
            "review_age_days": review_age_days,
            "reviewed_fixed_statements": len(decisions),
        },
    )


def _validate_grype(
    document: dict[str, Any],
    *,
    policy: dict[str, Any],
    active: list[dict[str, Any]],
    expected_image: dict[str, Any],
    vex_decisions: dict[tuple[str, str], dict[str, str]],
    vex_summary: dict[str, Any],
    scanner_exit_code: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], datetime]:
    audit_policy = policy["container_audits"]["vulnerability"]
    if scanner_exit_code != 0:
        raise ContainerSecurityError(f"Grype failed operationally with exit code {scanner_exit_code}")
    descriptor = document.get("descriptor")
    if not isinstance(descriptor, dict) or (
        descriptor.get("name"), descriptor.get("version")
    ) != (audit_policy["tool"], audit_policy["version"]):
        raise ContainerSecurityError("Grype descriptor does not match the pinned tool")
    configuration = descriptor.get("configuration")
    if (
        not isinstance(configuration, dict)
        or configuration.get("output") != ["json"]
        or configuration.get("exclude") != []
        or configuration.get("externalSources", {}).get("enable") is not False
        or configuration.get("search", {}).get("scope") != "squashed"
        or configuration.get("vex-documents") != [audit_policy["vex_document"]]
    ):
        raise ContainerSecurityError("Grype scan configuration drifted from the closed policy")
    source = document.get("source")
    target = source.get("target") if isinstance(source, dict) else None
    if (
        not isinstance(source, dict)
        or source.get("type") != "image"
        or not isinstance(target, dict)
        or target.get("imageID") != expected_image["config_digest"]
        or target.get("manifestDigest") != expected_image["local_manifest_digest"]
        or target.get("architecture") != "amd64"
        or target.get("os") != "linux"
    ):
        raise ContainerSecurityError("Grype report is not bound to the Syft image subject")
    scanned_at = _timestamp(descriptor.get("timestamp"), label="Grype scan timestamp")
    db = descriptor.get("db")
    status = db.get("status") if isinstance(db, dict) else None
    if (
        not isinstance(status, dict)
        or status.get("valid") is not True
        or not isinstance(status.get("schemaVersion"), str)
        or DB_SCHEMA.fullmatch(status["schemaVersion"]) is None
        or not status["schemaVersion"].startswith(f"v{audit_policy['supported_db_schema']}.")
    ):
        raise ContainerSecurityError("Grype database is absent, invalid, or uses an unreviewed schema")
    built_at = _timestamp(status.get("built"), label="Grype database build timestamp")
    age_seconds = int((scanned_at - built_at).total_seconds())
    if age_seconds < 0 or age_seconds > audit_policy["max_database_age_hours"] * 3600:
        raise ContainerSecurityError("Grype database age is outside the closed policy bound")
    ignored = document.get("ignoredMatches")
    if ignored is None:
        ignored = []
    if not isinstance(ignored, list):
        raise ContainerSecurityError("Grype ignored matches must be an array")
    matches = document.get("matches")
    if not isinstance(matches, list):
        raise ContainerSecurityError("Grype matches must be an array")
    counts = {severity: 0 for severity in SEVERITIES}
    high_records: list[dict[str, Any]] = []
    blockers: list[str] = []
    for match, suppressed in chain(
        ((item, False) for item in matches),
        ((item, True) for item in ignored),
    ):
        if not isinstance(match, dict):
            raise ContainerSecurityError("Grype match is malformed")
        vulnerability = match.get("vulnerability")
        artifact = match.get("artifact")
        details = match.get("matchDetails")
        if not isinstance(vulnerability, dict) or not isinstance(artifact, dict) or not isinstance(details, list):
            raise ContainerSecurityError("Grype vulnerability or artifact record is malformed")
        severity = vulnerability.get("severity")
        identifier = vulnerability.get("id")
        package = artifact.get("name")
        version = artifact.get("version")
        purl = artifact.get("purl")
        if (
            severity not in SEVERITIES
            or not isinstance(identifier, str)
            or not identifier
            or not isinstance(package, str)
            or not package
            or not isinstance(version, str)
            or not isinstance(purl, str)
            or not purl.startswith("pkg:")
        ):
            raise ContainerSecurityError("Grype finding identity is incomplete")
        counts[severity] += 1
        if suppressed and severity not in audit_policy["fail_severities"]:
            raise ContainerSecurityError("OpenVEX may suppress only configured release-blocking severities")
        if severity == "Unknown" and audit_policy["unknown_severity_policy"] == "fail":
            blockers.append(f"unknown-severity finding {identifier} for {package}@{version}")
        if severity not in audit_policy["fail_severities"]:
            continue
        aliases = match.get("relatedVulnerabilities", [])
        identifiers = {identifier}
        if isinstance(aliases, list):
            identifiers.update(
                str(item.get("id")) for item in aliases if isinstance(item, dict) and item.get("id")
            )
        exception_id = _matching_exception(active, subject=package, identifiers=identifiers)
        vex_decision = next(
            (
                vex_decisions[(identifier_value, purl)]
                for identifier_value in sorted(identifiers)
                if (identifier_value, purl) in vex_decisions
            ),
            None,
        )
        vex_document_id: str | None = None
        vex_status: str | None = None
        if suppressed:
            rules = match.get("appliedIgnoreRules")
            if (
                severity != "High"
                or vex_decision is None
                or rules != [{"namespace": "vex", "vex-status": vex_decision["status"]}]
            ):
                raise ContainerSecurityError("Grype suppressed a finding outside the governed VEX path")
            exception_id = None
            vex_document_id = vex_decision["document_id"]
            vex_status = vex_decision["status"]
            vex_summary["applied_fixed_findings"] += 1
        elif vex_decision is not None:
            raise ContainerSecurityError("Grype failed to apply a reviewed OpenVEX decision")
        match_types = sorted(
            {
                str(item.get("type"))
                for item in details
                if isinstance(item, dict) and isinstance(item.get("type"), str)
            }
        )
        record = {
            "exception_id": exception_id,
            "fix_state": str(vulnerability.get("fix", {}).get("state", "")),
            "id": identifier,
            "match_types": match_types,
            "namespace": str(vulnerability.get("namespace", "")),
            "package": package,
            "severity": severity,
            "version": version,
            "vex_document_id": vex_document_id,
            "vex_status": vex_status,
        }
        high_records.append(record)
        if suppressed:
            continue
        if severity == "Critical":
            blockers.append(f"critical finding {identifier} for {package}@{version} cannot be excepted")
        elif exception_id is None:
            blockers.append(f"unexcepted high finding {identifier} for {package}@{version}")
    high_records.sort(key=lambda item: (item["severity"], item["package"], item["id"], item["version"]))
    return (
        {
            "age_seconds_at_scan": age_seconds,
            "built_at": _canonical_timestamp(built_at),
            "schema_version": status["schemaVersion"],
        },
        high_records,
        blockers,
        scanned_at,
    )


def build_evidence(
    *,
    project_root: Path,
    syft_json: Path,
    grype_report: Path,
    scanner_exit_code: int,
    image_config_digest: str,
    as_of: date,
) -> tuple[dict[str, Any], bool]:
    if SHA256.fullmatch(image_config_digest) is None:
        raise ContainerSecurityError("image configuration subject must be one lowercase SHA-256 digest")
    policy, active, *_ = validate_project(project_root, as_of)
    syft_document = _load_json(syft_json, label="Syft native SBOM")
    grype_document = _load_json(grype_report, label="Grype report")
    image, licenses, license_blockers = _validate_syft(
        syft_document, policy=policy, image_config_digest=image_config_digest
    )
    vex_policy = policy["container_audits"]["vulnerability"]
    vex_path = (project_root.resolve(strict=True) / vex_policy["vex_document"]).resolve(strict=True)
    expected_vex_path = project_root.resolve(strict=True) / vex_policy["vex_document"]
    if vex_path != expected_vex_path:
        raise ContainerSecurityError("OpenVEX path escapes or aliases the reviewed project file")
    vex_document = _load_json(vex_path, label="OpenVEX document")
    artifact_purls = {
        str(item["purl"])
        for item in syft_document["artifacts"]
        if isinstance(item, dict) and isinstance(item.get("purl"), str)
    }
    vex_decisions, vex_summary = _validate_vex(
        vex_document,
        policy=policy,
        artifact_purls=artifact_purls,
        document_sha256=_sha256(vex_path),
        as_of=as_of,
    )
    database, findings, vulnerability_blockers, scanned_at = _validate_grype(
        grype_document,
        policy=policy,
        active=active,
        expected_image=image,
        vex_decisions=vex_decisions,
        vex_summary=vex_summary,
        scanner_exit_code=scanner_exit_code,
    )
    counts = {severity.lower(): 0 for severity in SEVERITIES}
    for match in [
        *grype_document["matches"],
        *(grype_document.get("ignoredMatches") or []),
    ]:
        counts[str(match["vulnerability"]["severity"]).lower()] += 1
    blockers = sorted({*license_blockers, *vulnerability_blockers})
    evidence = {
        "$schema": "../schemas/container_security_evidence.schema.json",
        "active_exception_count": sum(
            item.get("ecosystem") == "container" and item.get("kind") == "vulnerability"
            for item in active
        ),
        "blockers": blockers,
        "database": database,
        "evaluated_at": _canonical_timestamp(scanned_at),
        "image": image,
        "license_inventory": licenses,
        "policy_id": policy["policy_id"],
        "schema_version": 2,
        "status": "blocked" if blockers else "passed",
        "tools": {
            "grype": f"grype@{policy['container_audits']['vulnerability']['version']}",
            "syft": f"syft@{policy['container_audits']['sbom']['version']}",
        },
        "vex": vex_summary,
        "vulnerabilities": {
            "counts": counts,
            "critical_or_high_findings": findings,
            "grype_report_sha256": _sha256(grype_report),
            "syft_inventory_sha256": _sha256(syft_json),
        },
    }
    return evidence, bool(blockers)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--syft-json", type=Path, required=True)
    parser.add_argument("--grype-report", type=Path, required=True)
    parser.add_argument("--grype-exit-code", type=int, required=True)
    parser.add_argument("--image-config-digest", required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        evidence, blocked = build_evidence(
            project_root=args.project_root,
            syft_json=args.syft_json,
            grype_report=args.grype_report,
            scanner_exit_code=args.grype_exit_code,
            image_config_digest=args.image_config_digest,
            as_of=args.as_of,
        )
        _atomic_write(args.output, evidence)
    except (
        AttributeError,
        ContainerSecurityError,
        SupplyChainPolicyError,
        OSError,
        KeyError,
        TypeError,
    ) as exc:
        print(f"container security evidence rejected: {exc}", file=sys.stderr)
        return 2
    if blocked:
        print(
            f"container security gate blocked release with {len(evidence['blockers'])} policy blocker(s)",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"output": str(args.output), "status": "passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
