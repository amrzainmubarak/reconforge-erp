#!/usr/bin/env python3
"""Fail-closed validation for ReconForge dependency and secret policy inputs."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class SupplyChainPolicyError(ValueError):
    """Raised when a policy, lock, exception, or audit result is unsafe."""


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXACT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]*$")
_ISSUE_URL = re.compile(r"^https://github\.com/amrzainmubarak/reconforge-erp/issues/[1-9][0-9]*$")
_GITLEAKS_FINGERPRINT = re.compile(
    r"^(?:[0-9a-f]{40}:)?[A-Za-z0-9_.\-/]+:[a-z0-9-]+:[1-9][0-9]*$"
)
_ALLOWED_GITLEAKS_PATHS = {
    "'''(^|[\\\\/])\\.git[\\\\/]'''",
    "'''(^|[\\\\/])\\.venv[\\\\/]'''",
    "'''(^|[\\\\/])\\.venv-windows[\\\\/]'''",
    "'''(^|[\\\\/])\\.codex-test-tmp[\\\\/]'''",
    "'''(^|[\\\\/])\\.tmp[\\\\/]'''",
    "'''(^|[\\\\/])node_modules[\\\\/]'''",
    "'''(^|[\\\\/])__pycache__[\\\\/]'''",
    "'''(^|[\\\\/])\\.mypy_cache[\\\\/]'''",
    "'''(^|[\\\\/])\\.pytest_cache[\\\\/]'''",
    "'''(^|[\\\\/])\\.pytest-tmp-goal[\\\\/]'''",
    "'''(^|[\\\\/])\\.ruff_cache[\\\\/]'''",
    "'''(^|[\\\\/])(build|dist|output)[\\\\/]'''",
}
_DOCKER_CONTEXT_ALLOWLIST = {
    "!.dockerignore",
    "!Dockerfile",
    "!LICENSE",
    "!README.md",
    "!alembic.ini",
    "!pyproject.toml",
    "!setup.py",
    "!uv.lock",
    "!alembic/",
    "!alembic/**",
    "!config/",
    "!config/**",
    "!control-packs/",
    "!control-packs/**",
    "!examples/",
    "!examples/**",
    "!reconforge/",
    "!reconforge/**",
}


def _require_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise SupplyChainPolicyError(f"{label} must match the closed v1 field set")
    return value


def _validate_policy_document(policy: dict[str, Any]) -> None:
    _require_keys(
        policy,
        {
            "$schema",
            "container_audits",
            "container_resolution",
            "dependency_audits",
            "effective_on",
            "exceptions",
            "javascript_resolution",
            "limitations",
            "owner",
            "policy_id",
            "python_resolution",
            "release_gate",
            "review_cadence_days",
            "schema_version",
            "secret_scanning",
            "updates",
        },
        "supply-chain policy",
    )
    if (
        policy.get("$schema") != "../schemas/supply_chain_policy.schema.json"
        or policy.get("schema_version") != 1
        or policy.get("policy_id") != "reconforge-supply-chain"
        or not isinstance(policy.get("owner"), str)
        or not isinstance(policy.get("review_cadence_days"), int)
        or not 1 <= policy["review_cadence_days"] <= 90
    ):
        raise SupplyChainPolicyError("supply-chain policy identity or review cadence is invalid")
    _parse_date(policy.get("effective_on"), "policy effective_on")

    python_policy = _require_keys(
        policy["python_resolution"],
        {
            "exclude_newer",
            "linux_x86_64_archive_sha256",
            "lock",
            "manager",
            "manager_commit",
            "manager_version",
            "manifest",
            "required_profiles",
            "supported_python",
            "windows_x86_64_archive_sha256",
        },
        "python resolution",
    )
    if (
        python_policy["manifest"] != "pyproject.toml"
        or python_policy["lock"] != "uv.lock"
        or python_policy["manager"] != "uv"
        or python_policy["supported_python"] != ["3.11", "3.12"]
        or python_policy["required_profiles"]
        != ["runtime", "backup", "dev", "docs", "duckdb", "federation", "mfa", "observability", "server"]
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python_policy["manager_version"]) is None
        or re.fullmatch(r"[0-9a-f]{40}", python_policy["manager_commit"]) is None
    ):
        raise SupplyChainPolicyError("Python resolution policy drifted")
    for field in ("linux_x86_64_archive_sha256", "windows_x86_64_archive_sha256"):
        _validate_hash(f"sha256:{python_policy[field]}", f"python resolution {field}")

    javascript = _require_keys(
        policy["javascript_resolution"],
        {"audit_threshold", "install_command", "known_integrity_gap_entries", "lock", "manifest"},
        "JavaScript resolution",
    )
    if (
        javascript["manifest"] != "apps/web/package.json"
        or javascript["lock"] != "apps/web/package-lock.json"
        or javascript["install_command"] != "npm --prefix apps/web ci"
        or javascript["audit_threshold"] != "high"
        or not isinstance(javascript["known_integrity_gap_entries"], int)
        or javascript["known_integrity_gap_entries"] < 0
    ):
        raise SupplyChainPolicyError("JavaScript resolution policy drifted")

    container = _require_keys(
        policy["container_resolution"],
        {"base_image", "dependency_command", "dockerfile", "service_images"},
        "container resolution",
    )
    if container["dockerfile"] != "Dockerfile" or "@sha256:" not in container["base_image"]:
        raise SupplyChainPolicyError("container resolution policy drifted")
    service_images = _require_keys(
        container["service_images"], {"airgap_python", "postgres_16_ci", "postgres_drills"}, "service images"
    )
    if service_images != {
        "airgap_python": "python:3.14.1-slim@sha256:b823ded4377ebb5ff1af5926702df2284e53cecbc6e3549e93a19d8632a1897e",
        "postgres_16_ci": "postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777",
        "postgres_drills": "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193",
    }:
        raise SupplyChainPolicyError("service-image resolution policy drifted")

    container_audits = _require_keys(
        policy["container_audits"], {"sbom", "vulnerability"}, "container audits"
    )
    sbom = _require_keys(
        container_audits["sbom"],
        {
            "commit",
            "license_content_coverage",
            "linux_x86_64_archive_sha256",
            "minimum_license_coverage_percent",
            "native_schema_version",
            "scan_scope",
            "tool",
            "version",
            "windows_x86_64_archive_sha256",
        },
        "container SBOM audit",
    )
    vulnerability = _require_keys(
        container_audits["vulnerability"],
        {
            "commit",
            "fail_severities",
            "linux_x86_64_archive_sha256",
            "max_database_age_hours",
            "scan_input_format",
            "supported_db_schema",
            "tool",
            "unknown_severity_policy",
            "version",
            "vex_allowed_statuses",
            "vex_context",
            "vex_document",
            "vex_document_sha256",
            "vex_max_review_age_days",
            "windows_x86_64_archive_sha256",
        },
        "container vulnerability audit",
    )
    if (
        sbom["tool"] != "syft"
        or sbom["scan_scope"] != "squashed"
        or sbom["license_content_coverage"] != 75
        or not 90 <= sbom["minimum_license_coverage_percent"] <= 100
        or vulnerability["tool"] != "grype"
        or vulnerability["scan_input_format"] != "syft-json"
        or vulnerability["fail_severities"] != ["Critical", "High"]
        or vulnerability["unknown_severity_policy"] != "fail"
        or vulnerability["supported_db_schema"] != 6
        or not 1 <= vulnerability["max_database_age_hours"] <= 168
        or vulnerability["vex_document"] != "docs/security/container-runtime.openvex.json"
        or vulnerability["vex_context"] != "https://openvex.dev/ns/v0.2.0"
        or vulnerability["vex_allowed_statuses"] != ["fixed"]
        or not 1 <= vulnerability["vex_max_review_age_days"] <= 30
        or re.fullmatch(r"[0-9a-f]{64}", vulnerability["vex_document_sha256"]) is None
    ):
        raise SupplyChainPolicyError("container scanner policy drifted")
    for label, scanner in (("Syft", sbom), ("Grype", vulnerability)):
        if (
            re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", scanner["version"]) is None
            or re.fullmatch(r"[0-9a-f]{40}", scanner["commit"]) is None
        ):
            raise SupplyChainPolicyError(f"{label} identity is invalid")
        for field in ("linux_x86_64_archive_sha256", "windows_x86_64_archive_sha256"):
            _validate_hash(f"sha256:{scanner[field]}", f"{label} {field}")

    secret = _require_keys(
        policy["secret_scanning"],
        {
            "commit",
            "config",
            "linux_x86_64_archive_sha256",
            "redaction_percent",
            "required_scopes",
            "tool",
            "version",
            "windows_x86_64_archive_sha256",
        },
        "secret scanning",
    )
    if (
        secret["config"] != ".gitleaks.toml"
        or secret["tool"] != "gitleaks"
        or secret["required_scopes"] != ["full-git-history", "checked-out-tree"]
        or secret["redaction_percent"] != 100
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", secret["version"]) is None
        or re.fullmatch(r"[0-9a-f]{40}", secret["commit"]) is None
    ):
        raise SupplyChainPolicyError("secret-scanning policy drifted")
    for field in ("linux_x86_64_archive_sha256", "windows_x86_64_archive_sha256"):
        _validate_hash(f"sha256:{secret[field]}", f"secret scanning {field}")

    audits = _require_keys(
        policy["dependency_audits"], {"javascript", "python", "scanner_error_policy"}, "dependency audits"
    )
    if audits["scanner_error_policy"] != "fail-closed":
        raise SupplyChainPolicyError("dependency scanner errors must fail closed")
    _require_keys(audits["python"], {"locked_extra", "policy", "tool"}, "Python dependency audit")
    _require_keys(audits["javascript"], {"policy", "tool"}, "JavaScript dependency audit")
    if audits["python"] != {
        "tool": "pip-audit",
        "locked_extra": "dev",
        "policy": "fail-on-every-known-advisory-without-an-active-exact-exception",
    } or audits["javascript"] != {
        "tool": "npm-audit",
        "policy": "fail-on-high-or-critical-without-an-active-exact-exception",
    }:
        raise SupplyChainPolicyError("dependency audit policy drifted")

    updates = _require_keys(
        policy["updates"],
        {"automated_cadence", "automated_ecosystems", "emergency_review_trigger", "lock_review_cadence_days"},
        "dependency updates",
    )
    if (
        updates["automated_ecosystems"] != ["pip", "npm", "docker", "github-actions"]
        or updates["automated_cadence"] != "weekly"
        or not isinstance(updates["lock_review_cadence_days"], int)
        or not 1 <= updates["lock_review_cadence_days"] <= 90
    ):
        raise SupplyChainPolicyError("dependency update policy drifted")

    exceptions = _require_keys(
        policy["exceptions"],
        {
            "critical_release_exception_allowed",
            "expired_or_revoked_entries_exempt",
            "max_active_days",
            "minimum_distinct_approvers",
            "registry",
        },
        "exception policy",
    )
    if (
        exceptions["registry"] != "docs/security/supply-chain-exceptions.v1.json"
        or not isinstance(exceptions["max_active_days"], int)
        or not 1 <= exceptions["max_active_days"] <= 30
        or not isinstance(exceptions["minimum_distinct_approvers"], int)
        or exceptions["minimum_distinct_approvers"] < 2
        or exceptions["critical_release_exception_allowed"] is not False
        or exceptions["expired_or_revoked_entries_exempt"] is not False
    ):
        raise SupplyChainPolicyError("exception policy drifted")

    release_gate = _require_keys(
        policy["release_gate"], {"must_run_before_external_write", "required_checks", "workflow"}, "release gate"
    )
    if (
        release_gate["workflow"] != ".github/workflows/release.yml"
        or release_gate["must_run_before_external_write"] is not True
        or release_gate["required_checks"]
        != [
            "policy-validation",
            "lock-current",
            "python-audit",
            "javascript-audit",
            "git-secret-scan",
            "tree-secret-scan",
            "container-sbom",
            "container-vulnerability-audit",
            "container-license-inventory",
        ]
    ):
        raise SupplyChainPolicyError("release-gate policy drifted")
    limitations = policy.get("limitations")
    if not isinstance(limitations, list) or len(limitations) < 3 or any(not isinstance(item, str) for item in limitations):
        raise SupplyChainPolicyError("policy limitations must remain explicit")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SupplyChainPolicyError(f"cannot read valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SupplyChainPolicyError(f"JSON root must be an object: {path}")
    return value


def _required_path(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink():
        raise SupplyChainPolicyError(f"policy input must not be a symlink: {relative}")
    if not path.is_file():
        raise SupplyChainPolicyError(f"required policy input is missing: {relative}")
    return path


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise SupplyChainPolicyError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SupplyChainPolicyError(f"{field} must be an ISO date") from exc


def _validate_https_url(value: object, expected_host: str, field: str) -> None:
    if not isinstance(value, str):
        raise SupplyChainPolicyError(f"{field} must be an HTTPS URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SupplyChainPolicyError(f"{field} is not an approved credential-free HTTPS URL")


def _validate_hash(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SupplyChainPolicyError(f"{field} must be a lowercase SHA-256")


def _validate_uv_lock(lock: dict[str, Any], policy: dict[str, Any]) -> int:
    python_policy = policy["python_resolution"]
    if lock.get("version") != 1 or lock.get("revision") != 3:
        raise SupplyChainPolicyError("uv.lock format must remain version 1 revision 3")
    if lock.get("requires-python") != ">=3.11":
        raise SupplyChainPolicyError("uv.lock Python range drifted")
    if lock.get("options") != {"exclude-newer": python_policy["exclude_newer"]}:
        raise SupplyChainPolicyError("uv.lock cutoff drifted from policy")

    packages = lock.get("package")
    if not isinstance(packages, list) or not packages:
        raise SupplyChainPolicyError("uv.lock must contain packages")
    roots = [item for item in packages if item.get("source") == {"editable": "."}]
    if len(roots) != 1 or roots[0].get("name") != "reconforge-erp":
        raise SupplyChainPolicyError("uv.lock must have exactly one local ReconForge root")

    identities: set[tuple[str, str]] = set()
    for package in packages:
        if package is roots[0]:
            continue
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str) or not _EXACT_VERSION.fullmatch(version):
            raise SupplyChainPolicyError("every registry package must have a safe exact name and version")
        identity = (name, version)
        if identity in identities:
            raise SupplyChainPolicyError(f"duplicate uv.lock package identity: {name}=={version}")
        identities.add(identity)
        if package.get("source") != {"registry": "https://pypi.org/simple"}:
            raise SupplyChainPolicyError(f"unapproved uv.lock source for {name}=={version}")

        artifacts: list[dict[str, Any]] = []
        sdist = package.get("sdist")
        if sdist is not None:
            if not isinstance(sdist, dict):
                raise SupplyChainPolicyError(f"invalid sdist record for {name}=={version}")
            artifacts.append(sdist)
        wheels = package.get("wheels", [])
        if not isinstance(wheels, list) or any(not isinstance(item, dict) for item in wheels):
            raise SupplyChainPolicyError(f"invalid wheel records for {name}=={version}")
        artifacts.extend(wheels)
        if not artifacts:
            raise SupplyChainPolicyError(f"no hashed distribution exists for {name}=={version}")
        for index, artifact in enumerate(artifacts):
            prefix = f"{name}=={version} artifact {index}"
            _validate_https_url(artifact.get("url"), "files.pythonhosted.org", f"{prefix} URL")
            _validate_hash(artifact.get("hash"), f"{prefix} hash")
            if not isinstance(artifact.get("size"), int) or artifact["size"] <= 0:
                raise SupplyChainPolicyError(f"{prefix} size must be positive")
            if not isinstance(artifact.get("upload-time"), str):
                raise SupplyChainPolicyError(f"{prefix} upload time is missing")
    return len(packages) - 1


def _validate_package_lock(root: Path, policy: dict[str, Any]) -> tuple[int, int]:
    javascript = policy["javascript_resolution"]
    package_json = _load_json(_required_path(root, javascript["manifest"]))
    package_lock = _load_json(_required_path(root, javascript["lock"]))
    if package_lock.get("lockfileVersion") != 3:
        raise SupplyChainPolicyError("npm lockfileVersion must be 3")
    packages = package_lock.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise SupplyChainPolicyError("npm lock must contain a root package")
    npm_root = packages[""]
    for field in ("name", "version", "dependencies", "devDependencies", "engines"):
        if npm_root.get(field) != package_json.get(field):
            raise SupplyChainPolicyError(f"npm root {field} drifted from package.json")

    missing_integrity = 0
    for location, package in packages.items():
        if location == "":
            continue
        if not isinstance(location, str) or not location.startswith("node_modules/"):
            raise SupplyChainPolicyError("npm lock contains an unsafe package location")
        if not isinstance(package, dict) or package.get("link") is True:
            raise SupplyChainPolicyError(f"npm lock link or malformed record: {location}")
        if not isinstance(package.get("version"), str) or not _EXACT_VERSION.fullmatch(package["version"]):
            raise SupplyChainPolicyError(f"npm lock lacks an exact version: {location}")
        resolved = package.get("resolved")
        integrity = package.get("integrity")
        if (resolved is None) != (integrity is None):
            raise SupplyChainPolicyError(f"npm resolved/integrity pair is incomplete: {location}")
        if resolved is None:
            missing_integrity += 1
            continue
        _validate_https_url(resolved, "registry.npmjs.org", f"{location} resolved URL")
        if not isinstance(integrity, str) or "-" not in integrity:
            raise SupplyChainPolicyError(f"invalid npm integrity: {location}")
        algorithm, encoded = integrity.split("-", 1)
        if algorithm not in {"sha256", "sha384", "sha512"}:
            raise SupplyChainPolicyError(f"weak npm integrity algorithm: {location}")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise SupplyChainPolicyError(f"invalid npm integrity encoding: {location}") from exc
        if len(decoded) * 8 != int(algorithm[3:]):
            raise SupplyChainPolicyError(f"invalid npm integrity length: {location}")

    expected_gap = javascript["known_integrity_gap_entries"]
    if missing_integrity != expected_gap:
        raise SupplyChainPolicyError(
            f"npm integrity gap changed without policy review: expected {expected_gap}, got {missing_integrity}"
        )
    return len(packages) - 1, missing_integrity


def _validate_exceptions(data: dict[str, Any], policy: dict[str, Any], as_of: date) -> list[dict[str, Any]]:
    if data.get("schema_version") != 1 or not isinstance(data.get("exceptions"), list):
        raise SupplyChainPolicyError("exception registry format is invalid")
    _parse_date(data.get("as_of"), "exception registry as_of")
    maximum_days = policy["exceptions"]["max_active_days"]
    minimum_approvers = policy["exceptions"]["minimum_distinct_approvers"]
    identifiers: set[str] = set()
    active: list[dict[str, Any]] = []
    expected_fields = {
        "approved_by",
        "compensating_controls",
        "created_on",
        "ecosystem",
        "expires_on",
        "id",
        "identifiers",
        "issue_url",
        "justification",
        "kind",
        "owner",
        "status",
        "subject",
    }
    for item in data["exceptions"]:
        if not isinstance(item, dict):
            raise SupplyChainPolicyError("every exception must be an object")
        if set(item) != expected_fields:
            raise SupplyChainPolicyError("exception fields must match the closed v1 contract")
        exception_id = item.get("id")
        if not isinstance(exception_id, str) or not re.fullmatch(r"SC-EXC-[0-9]{4}", exception_id):
            raise SupplyChainPolicyError("exception ID is invalid")
        if exception_id in identifiers:
            raise SupplyChainPolicyError(f"duplicate exception ID: {exception_id}")
        identifiers.add(exception_id)
        if item.get("ecosystem") not in {"python", "npm", "container", "github-actions", "secret-scan"}:
            raise SupplyChainPolicyError(f"{exception_id} ecosystem is invalid")
        if item.get("kind") not in {"vulnerability", "secret-false-positive", "temporary-resolution"}:
            raise SupplyChainPolicyError(f"{exception_id} kind is invalid")
        if not isinstance(item.get("subject"), str) or not item["subject"]:
            raise SupplyChainPolicyError(f"{exception_id} subject is invalid")
        created = _parse_date(item.get("created_on"), f"{exception_id} created_on")
        expires = _parse_date(item.get("expires_on"), f"{exception_id} expires_on")
        if expires < created or (expires - created).days > maximum_days:
            raise SupplyChainPolicyError(f"{exception_id} exceeds the maximum exception lifetime")
        approvers = item.get("approved_by")
        if (
            not isinstance(approvers, list)
            or any(not isinstance(approver, str) or len(approver) < 3 for approver in approvers)
            or len(set(approvers)) < minimum_approvers
        ):
            raise SupplyChainPolicyError(f"{exception_id} lacks distinct approvals")
        if item.get("owner") in approvers:
            raise SupplyChainPolicyError(f"{exception_id} owner cannot approve their own exception")
        if not isinstance(item.get("issue_url"), str) or _ISSUE_URL.fullmatch(item["issue_url"]) is None:
            raise SupplyChainPolicyError(f"{exception_id} must link to a repository issue")
        exception_identifiers = item.get("identifiers")
        if (
            not isinstance(exception_identifiers, list)
            or not exception_identifiers
            or any(not isinstance(identifier, str) or len(identifier) < 3 for identifier in exception_identifiers)
            or len(set(exception_identifiers)) != len(exception_identifiers)
        ):
            raise SupplyChainPolicyError(f"{exception_id} must identify exact findings")
        if not isinstance(item.get("justification"), str) or len(item["justification"]) < 20:
            raise SupplyChainPolicyError(f"{exception_id} justification is too short")
        controls = item.get("compensating_controls")
        if (
            not isinstance(controls, list)
            or not controls
            or any(not isinstance(control, str) or len(control) < 10 for control in controls)
            or len(set(controls)) != len(controls)
        ):
            raise SupplyChainPolicyError(f"{exception_id} compensating controls are invalid")
        if item.get("status") == "active":
            if as_of > expires:
                raise SupplyChainPolicyError(f"active exception expired: {exception_id}")
            active.append(item)
        elif item.get("status") not in {"expired", "revoked"}:
            raise SupplyChainPolicyError(f"invalid exception status: {exception_id}")
    return active


def _validate_dependabot(root: Path, policy: dict[str, Any]) -> None:
    text = _required_path(root, ".github/dependabot.yml").read_text(encoding="utf-8")
    ecosystems = policy["updates"]["automated_ecosystems"]
    for index, ecosystem in enumerate(ecosystems):
        start = text.find(f'package-ecosystem: "{ecosystem}"')
        if start < 0:
            raise SupplyChainPolicyError(f"Dependabot is missing {ecosystem}")
        end_positions = [
            text.find('package-ecosystem: "', start + 1),
            len(text),
        ]
        end = min(position for position in end_positions if position >= 0)
        block = text[start:end]
        expected_directory = "/apps/web" if ecosystem == "npm" else "/"
        if f'directory: "{expected_directory}"' not in block or 'interval: "weekly"' not in block:
            raise SupplyChainPolicyError(f"Dependabot {ecosystem} cadence or directory drifted")
        if text.count(f'package-ecosystem: "{ecosystem}"') != 1:
            raise SupplyChainPolicyError(f"Dependabot {ecosystem} must be unique")
        if index == 0 and "version: 2" not in text:
            raise SupplyChainPolicyError("Dependabot schema version must be 2")


def _validate_gitleaks_config(root: Path) -> None:
    text = _required_path(root, ".gitleaks.toml").read_text(encoding="utf-8")
    if text.count("useDefault = true") != 1:
        raise SupplyChainPolicyError("Gitleaks must extend its pinned binary's default rules")
    if "commits =" in text or "regexes =" in text or "stopwords =" in text or "disabledRules" in text:
        raise SupplyChainPolicyError("broad Gitleaks finding allowlists are forbidden")
    configured = {line.strip().rstrip(",") for line in text.splitlines() if line.strip().startswith("'''")}
    if configured != _ALLOWED_GITLEAKS_PATHS:
        raise SupplyChainPolicyError("Gitleaks path exclusions drifted from the bounded generated-directory set")
    ignore_lines = [
        line.strip()
        for line in _required_path(root, ".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not ignore_lines or len(ignore_lines) != len(set(ignore_lines)):
        raise SupplyChainPolicyError("Gitleaks ignore fingerprints must be non-empty and unique")
    if any(_GITLEAKS_FINGERPRINT.fullmatch(line) is None for line in ignore_lines):
        raise SupplyChainPolicyError("Gitleaks ignores must be exact commit/path/rule/line fingerprints")


def _validate_dockerfile(root: Path, policy: dict[str, Any]) -> None:
    docker_policy = policy["container_resolution"]
    python_policy = policy["python_resolution"]
    text = _required_path(root, docker_policy["dockerfile"]).read_text(encoding="utf-8")
    stage_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
    if len(stage_lines) != 2 or any(line.split()[1] != docker_policy["base_image"] for line in stage_lines):
        raise SupplyChainPolicyError("both Docker stages must use the reviewed base-image digest")
    required = (
        f"ADD --checksum=sha256:{python_policy['linux_x86_64_archive_sha256']} ",
        f"/astral-sh/uv/releases/download/{python_policy['manager_version']}/",
        docker_policy["dependency_command"],
    )
    if any(fragment not in text for fragment in required):
        raise SupplyChainPolicyError("Docker locked uv installation contract drifted")
    for line in text.splitlines():
        if line.startswith("FROM "):
            image = line.split()[1]
            if re.search(r"@sha256:[0-9a-f]{64}$", image) is None:
                raise SupplyChainPolicyError("every Docker stage must use a digest-pinned image")
    context_rules = [
        line.strip()
        for line in _required_path(root, ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not context_rules or context_rules[0] != "*" or set(context_rules[1:]) != _DOCKER_CONTEXT_ALLOWLIST:
        raise SupplyChainPolicyError("Docker build context must match the closed deny-by-default allowlist")

    service_images = docker_policy["service_images"]
    expected = {
        ".github/scripts/verify_airgap_install.py": service_images["airgap_python"],
        ".github/scripts/verify_postgres_ha_dr.py": service_images["postgres_drills"],
        ".github/scripts/verify_postgres_writeback_identity_migration.py": service_images["postgres_drills"],
        ".github/scripts/verify_postgres_reliability.py": service_images["postgres_drills"],
        ".github/scripts/verify_postgres_upgrade.py": service_images["postgres_drills"],
    }
    for relative, image in expected.items():
        script = _required_path(root, relative).read_text(encoding="utf-8")
        tag, digest = image.rsplit("@", 1)
        if (
            f'IMAGE = "{tag}"' not in script
            or f'IMAGE_REFERENCE = f"{{IMAGE}}@{digest}"' not in script
            or script.count("IMAGE_REFERENCE") < 2
        ):
            raise SupplyChainPolicyError(f"digest-pinned service image drifted in {relative}")

    matrix_paths = (
        ".github/scripts/verify_postgres_writeback_identity_migration_matrix.py",
        ".github/scripts/verify_postgres_writeback_receiver_idempotency_matrix.py",
        ".github/scripts/verify_postgres_writeback_receiver_failover_matrix.py",
        ".github/scripts/verify_postgres_writeback_recovery_compensation_matrix.py",
    )
    for relative in matrix_paths:
        matrix_script = _required_path(root, relative).read_text(encoding="utf-8")
        for prefix, image in (
            ("POSTGRES_16", service_images["postgres_16_ci"]),
            ("POSTGRES_17", service_images["postgres_drills"]),
        ):
            tag, digest = image.rsplit("@", 1)
            if (
                f'{prefix}_IMAGE = "{tag}"' not in matrix_script
                or f'{prefix}_IMAGE_REFERENCE = (' not in matrix_script
                or f'f"{{{prefix}_IMAGE}}@{digest}"' not in matrix_script
                or matrix_script.count(f"{prefix}_IMAGE_REFERENCE") < 2
            ):
                raise SupplyChainPolicyError(f"PostgreSQL matrix image drifted in {relative}")


def _validate_workflows(root: Path, policy: dict[str, Any]) -> None:
    release = _required_path(root, policy["release_gate"]["workflow"]).read_text(encoding="utf-8")
    security = _required_path(root, ".github/workflows/security.yml").read_text(encoding="utf-8")
    audit_runner = _required_path(root, ".github/scripts/run_locked_python_audit.py").read_text(
        encoding="utf-8"
    )
    container_gate = _required_path(root, ".github/scripts/validate_container_security.py").read_text(
        encoding="utf-8"
    )
    python_policy = policy["python_resolution"]
    secret_policy = policy["secret_scanning"]
    sbom_policy = policy["container_audits"]["sbom"]
    vulnerability_policy = policy["container_audits"]["vulnerability"]
    shared_fragments = (
        "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9",
        f'version: "{python_policy["manager_version"]}"',
        f'GITLEAKS_VERSION: "{secret_policy["version"]}"',
        f"GITLEAKS_LINUX_X64_SHA256: {secret_policy['linux_x86_64_archive_sha256']}",
        "uv lock --check",
        "uv sync --locked --extra dev --no-editable --python",
        ".github/scripts/run_locked_python_audit.py",
        "gitleaks.toml --log-opts=\"--all\"",
        "gitleaks.toml",
        "npm --prefix apps/web audit --package-lock-only --audit-level=high",
        "--npm-audit-exit-code",
        f'SYFT_VERSION: "{sbom_policy["version"]}"',
        f"SYFT_COMMIT: {sbom_policy['commit']}",
        f"SYFT_LINUX_AMD64_SHA256: {sbom_policy['linux_x86_64_archive_sha256']}",
        f'GRYPE_VERSION: "{vulnerability_policy["version"]}"',
        f"GRYPE_COMMIT: {vulnerability_policy['commit']}",
        f"GRYPE_LINUX_AMD64_SHA256: {vulnerability_policy['linux_x86_64_archive_sha256']}",
        '"sbom:${RUNNER_TEMP}/image.syft.json"',
        "--vex docs/security/container-runtime.openvex.json",
        ".github/scripts/validate_container_security.py",
        "--image-config-digest",
    )
    for workflow_name, text in (("release", release), ("security", security)):
        if "continue-on-error" in text:
            raise SupplyChainPolicyError(f"{workflow_name} workflow must not continue after a failed gate")
        for fragment in shared_fragments:
            if fragment not in text:
                raise SupplyChainPolicyError(f"{workflow_name} workflow is missing policy gate: {fragment}")

    for fragment in (
        '"--all-extras"',
        '"--no-emit-project"',
        '"--require-hashes"',
        '"--disable-pip"',
        '"--pip-audit-exit-code"',
        '"--isolated"',
        '"--no-sync"',
    ):
        if fragment not in audit_runner:
            raise SupplyChainPolicyError(f"locked Python audit runner is missing policy gate: {fragment}")

    for fragment in (
        "ignoredMatches",
        'severity == "Critical"',
        "max_database_age_hours",
        "minimum_license_coverage_percent",
        "expected_image",
    ):
        if fragment not in container_gate:
            raise SupplyChainPolicyError(f"container audit runner is missing policy gate: {fragment}")

    external_write = release.find("docker/login-action@")
    if external_write < 0:
        raise SupplyChainPolicyError("release registry write boundary is missing")
    required_before_write = (
        "Validate closed supply-chain policy and current lock",
        "Audit the hash-locked Python and server resolution",
        "Scan full Git history with redacted output",
        "Scan checked-out tree with redacted output",
        "Audit the npm lock",
        "Generate exact-image SBOM and vulnerability inputs",
        "Build and enforce the local container security gate",
    )
    if any(release.find(step) < 0 or release.find(step) > external_write for step in required_before_write):
        raise SupplyChainPolicyError("release supply-chain gates must precede registry authentication")
    for fragment in (
        "docker buildx imagetools inspect --raw",
        "published manifest bytes do not match the registry digest",
        "published manifest is not bound to the scanned image configuration",
    ):
        if release.find(fragment) < external_write:
            raise SupplyChainPolicyError(f"release post-push binding is missing: {fragment}")


def validate_project(root: Path, as_of: date) -> tuple[dict[str, Any], list[dict[str, Any]], int, int, int]:
    root = root.resolve(strict=True)
    policy = _load_json(_required_path(root, "docs/security/supply-chain-policy.v1.json"))
    _validate_policy_document(policy)
    vex_policy = policy["container_audits"]["vulnerability"]
    vex_path = _required_path(root, vex_policy["vex_document"])
    if hashlib.sha256(vex_path.read_bytes()).hexdigest() != vex_policy["vex_document_sha256"]:
        raise SupplyChainPolicyError("reviewed OpenVEX document hash drifted")
    python_policy = policy["python_resolution"]
    pyproject = tomllib.loads(_required_path(root, python_policy["manifest"]).read_text(encoding="utf-8"))
    uv_config = pyproject.get("tool", {}).get("uv")
    expected_uv = {
        "required-version": f"=={python_policy['manager_version']}",
        "exclude-newer": python_policy["exclude_newer"],
    }
    if uv_config != expected_uv:
        raise SupplyChainPolicyError("pyproject uv policy drifted")
    lock = tomllib.loads(_required_path(root, python_policy["lock"]).read_text(encoding="utf-8"))
    python_packages = _validate_uv_lock(lock, policy)
    npm_packages, npm_gap = _validate_package_lock(root, policy)
    exceptions = _load_json(_required_path(root, policy["exceptions"]["registry"]))
    active = _validate_exceptions(exceptions, policy, as_of)
    _validate_dependabot(root, policy)
    _validate_gitleaks_config(root)
    _validate_dockerfile(root, policy)
    _validate_workflows(root, policy)
    return policy, active, python_packages, npm_packages, npm_gap


def _is_exempt(
    active: list[dict[str, Any]], ecosystem: str, subject: str, identifiers: set[str]
) -> bool:
    normalized_subject = subject.casefold().replace("_", "-")
    for item in active:
        candidate = str(item.get("subject", "")).casefold().replace("_", "-")
        if (
            item.get("ecosystem") == ecosystem
            and item.get("kind") == "vulnerability"
            and candidate == normalized_subject
            and identifiers.intersection(str(value) for value in item.get("identifiers", []))
        ):
            return True
    return False


def enforce_pip_audit(path: Path, exit_code: int, active: list[dict[str, Any]]) -> int:
    if exit_code not in {0, 1}:
        raise SupplyChainPolicyError(f"pip-audit failed operationally with exit code {exit_code}")
    report = _load_json(path)
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise SupplyChainPolicyError("pip-audit report has no dependency inventory")
    findings = 0
    for dependency in dependencies:
        if not isinstance(dependency, dict) or not isinstance(dependency.get("vulns"), list):
            raise SupplyChainPolicyError("pip-audit dependency record is malformed")
        name = str(dependency.get("name", ""))
        for vulnerability in dependency["vulns"]:
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                raise SupplyChainPolicyError("pip-audit vulnerability record is malformed")
            findings += 1
            advisory_ids = {vulnerability["id"]}
            aliases = vulnerability.get("aliases", [])
            if isinstance(aliases, list):
                advisory_ids.update(str(alias) for alias in aliases)
            if not _is_exempt(active, "python", name, advisory_ids):
                raise SupplyChainPolicyError(
                    f"unexcepted Python advisory for {name}: {sorted(advisory_ids)[0]}"
                )
    if (findings == 0) != (exit_code == 0):
        raise SupplyChainPolicyError("pip-audit exit code and report disagree")
    return findings


def enforce_npm_audit(path: Path, exit_code: int, active: list[dict[str, Any]]) -> int:
    if exit_code not in {0, 1}:
        raise SupplyChainPolicyError(f"npm audit failed operationally with exit code {exit_code}")
    report = _load_json(path)
    if report.get("auditReportVersion") != 2 or not isinstance(report.get("vulnerabilities"), dict):
        raise SupplyChainPolicyError("npm audit report format is invalid")
    findings = 0
    for package_name, vulnerability in report["vulnerabilities"].items():
        if not isinstance(vulnerability, dict):
            raise SupplyChainPolicyError("npm vulnerability record is malformed")
        severity = vulnerability.get("severity")
        if severity not in {"high", "critical"}:
            continue
        findings += 1
        advisory_ids: set[str] = set()
        for via in vulnerability.get("via", []):
            if isinstance(via, dict):
                for field in ("source", "url"):
                    if via.get(field) is not None:
                        advisory_ids.add(str(via[field]))
        if not advisory_ids:
            raise SupplyChainPolicyError(f"high-severity npm finding lacks an exact advisory ID: {package_name}")
        if severity == "critical":
            raise SupplyChainPolicyError(f"critical npm advisory cannot be excepted for release: {package_name}")
        if not _is_exempt(active, "npm", str(package_name), advisory_ids):
            raise SupplyChainPolicyError(
                f"unexcepted high-severity npm advisory for {package_name}: {sorted(advisory_ids)[0]}"
            )
    if findings == 0 and exit_code != 0:
        raise SupplyChainPolicyError("npm audit exit code and high-severity report disagree")
    return findings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--pip-audit-report", type=Path)
    parser.add_argument("--pip-audit-exit-code", type=int)
    parser.add_argument("--npm-audit-report", type=Path)
    parser.add_argument("--npm-audit-exit-code", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        _, active, python_packages, npm_packages, npm_gap = validate_project(args.project_root, args.as_of)
        pip_findings = None
        npm_findings = None
        if (args.pip_audit_report is None) != (args.pip_audit_exit_code is None):
            raise SupplyChainPolicyError("pip-audit report and exit code must be supplied together")
        if (args.npm_audit_report is None) != (args.npm_audit_exit_code is None):
            raise SupplyChainPolicyError("npm audit report and exit code must be supplied together")
        if args.pip_audit_report is not None:
            pip_findings = enforce_pip_audit(args.pip_audit_report, args.pip_audit_exit_code, active)
        if args.npm_audit_report is not None:
            npm_findings = enforce_npm_audit(args.npm_audit_report, args.npm_audit_exit_code, active)
    except (OSError, KeyError, TypeError, SupplyChainPolicyError, tomllib.TOMLDecodeError) as exc:
        print(f"supply-chain policy validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "active_exceptions": len(active),
                "npm_high_findings": npm_findings,
                "npm_integrity_gap_entries": npm_gap,
                "npm_packages": npm_packages,
                "pip_findings": pip_findings,
                "python_packages": python_packages,
                "status": "valid",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
