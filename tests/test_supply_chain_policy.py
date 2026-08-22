from __future__ import annotations

import importlib.util
import json
import re
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "security" / "supply-chain-policy.v1.json"
EXCEPTIONS_PATH = ROOT / "docs" / "security" / "supply-chain-exceptions.v1.json"
POLICY_SCHEMA_PATH = ROOT / "docs" / "schemas" / "supply_chain_policy.schema.json"
EXCEPTIONS_SCHEMA_PATH = ROOT / "docs" / "schemas" / "supply_chain_exceptions.schema.json"
SCRIPT_PATH = ROOT / ".github" / "scripts" / "validate_supply_chain_policy.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_supply_chain_policy", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY_MODULE = _load_module()
SupplyChainPolicyError = POLICY_MODULE.SupplyChainPolicyError


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _copy_policy_project(tmp_path: Path) -> Path:
    relative_paths = (
        ".github/dependabot.yml",
        ".github/scripts/run_locked_python_audit.py",
        ".github/scripts/validate_container_security.py",
        ".github/scripts/verify_airgap_install.py",
        ".github/scripts/verify_postgres_ha_dr.py",
        ".github/scripts/verify_postgres_writeback_identity_migration.py",
        ".github/scripts/verify_postgres_writeback_identity_migration_matrix.py",
        ".github/scripts/verify_postgres_writeback_receiver_idempotency_matrix.py",
        ".github/scripts/verify_postgres_writeback_receiver_failover_matrix.py",
        ".github/scripts/verify_postgres_reliability.py",
        ".github/scripts/verify_postgres_upgrade.py",
        ".github/workflows/release.yml",
        ".github/workflows/security.yml",
        ".dockerignore",
        ".gitleaksignore",
        ".gitleaks.toml",
        "Dockerfile",
        "apps/web/package-lock.json",
        "apps/web/package.json",
        "docs/security/supply-chain-exceptions.v1.json",
        "docs/security/supply-chain-policy.v1.json",
        "docs/security/container-runtime.openvex.json",
        "pyproject.toml",
        "uv.lock",
    )
    for relative in relative_paths:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _active_exception(*, ecosystem: str, subject: str, identifier: str) -> dict[str, Any]:
    return {
        "id": "SC-EXC-0001",
        "status": "active",
        "ecosystem": ecosystem,
        "kind": "vulnerability",
        "subject": subject,
        "identifiers": [identifier],
        "owner": "dependency-owner",
        "approved_by": ["security-reviewer", "product-reviewer"],
        "issue_url": "https://github.com/amrzainmubarak/reconforge-erp/issues/123",
        "justification": "A bounded temporary exception while the exact upgrade is validated.",
        "compensating_controls": ["The affected feature remains disabled by default."],
        "created_on": "2026-07-01",
        "expires_on": "2026-07-30",
    }


def test_supply_chain_documents_match_closed_schemas() -> None:
    for schema_path, document_path in (
        (POLICY_SCHEMA_PATH, POLICY_PATH),
        (EXCEPTIONS_SCHEMA_PATH, EXCEPTIONS_PATH),
    ):
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(_json(document_path)), key=lambda error: list(error.path))
        assert not errors, "\n".join(error.message for error in errors)


def test_repository_policy_closes_resolution_and_exception_inputs() -> None:
    policy, active, python_packages, npm_packages, npm_gap = POLICY_MODULE.validate_project(
        ROOT, date(2026, 7, 26)
    )

    assert policy["python_resolution"]["manager_version"] == "0.11.32"
    assert policy["secret_scanning"]["version"] == "8.30.1"
    assert policy["container_audits"]["sbom"]["version"] == "1.51.0"
    assert policy["container_audits"]["vulnerability"]["version"] == "0.117.0"
    assert policy["container_audits"]["vulnerability"]["vex_allowed_statuses"] == ["fixed"]
    assert policy["container_resolution"]["service_images"]["postgres_16_ci"].startswith("postgres:16-alpine@sha256:")
    assert active == []
    assert python_packages == 128
    assert npm_packages == 211
    assert npm_gap == 0


def _mutate_pyproject(root: Path) -> None:
    path = root / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8").replace('required-version = "==0.11.32"', 'required-version = ">=0.11"'), encoding="utf-8")


def _mutate_uv_source(root: Path) -> None:
    path = root / "uv.lock"
    path.write_text(path.read_text(encoding="utf-8").replace("https://pypi.org/simple", "http://pypi.org/simple", 1), encoding="utf-8")


def _mutate_docker_base(root: Path) -> None:
    path = root / "Dockerfile"
    path.write_text(re.sub(r"@sha256:[0-9a-f]{64}", "", path.read_text(encoding="utf-8"), count=1), encoding="utf-8")


def _mutate_docker_context(root: Path) -> None:
    path = root / ".dockerignore"
    path.write_text(path.read_text(encoding="utf-8").replace("*\n", "", 1), encoding="utf-8")


def _mutate_service_image(root: Path) -> None:
    path = root / ".github" / "scripts" / "verify_postgres_upgrade.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193",
            "0" * 64,
        ),
        encoding="utf-8",
    )


def _mutate_vex(root: Path) -> None:
    path = root / "docs" / "security" / "container-runtime.openvex.json"
    path.write_text(path.read_text(encoding="utf-8").replace("fixed", "not_affected", 1), encoding="utf-8")


def test_docker_uv_version_check_accepts_only_the_pinned_version_with_optional_build_metadata() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "uv --version | grep -Eq '^uv 0\\.11\\.32( |$)'" in dockerfile
    assert 'test "$(uv --version)" = "uv 0.11.32"' not in dockerfile


def test_docker_runtime_is_multistage_and_non_root() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert " AS builder" in dockerfile
    assert " AS runtime" in dockerfile
    assert "COPY --from=builder /app/.venv /app/.venv" in dockerfile
    assert "/app/docs" not in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "chown 10001:10001 /app/output" in dockerfile
    assert dockerfile.index("USER 10001:10001") < dockerfile.index('CMD ["reconforge", "doctor"]')


def test_docker_context_is_deny_by_default() -> None:
    rules = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert rules[0] == "*"
    assert {
        "!.dockerignore",
        "!Dockerfile",
        "!LICENSE",
        "!README.md",
        "!alembic.ini",
        "!pyproject.toml",
        "!setup.py",
        "!uv.lock",
        "!alembic/**",
        "!config/**",
        "!control-packs/**",
        "!examples/**",
        "!reconforge/**",
    } <= set(rules)
    assert not any(rule.startswith("!.git") or "venv" in rule or "output" in rule for rule in rules)


def test_disposable_drill_images_execute_by_reviewed_digest() -> None:
    postgres_digest = "742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
    python_digest = "b823ded4377ebb5ff1af5926702df2284e53cecbc6e3549e93a19d8632a1897e"
    postgres_scripts = (
        "verify_postgres_ha_dr.py",
        "verify_postgres_upgrade.py",
        "verify_postgres_reliability.py",
    )
    for name in postgres_scripts:
        text = (ROOT / ".github" / "scripts" / name).read_text(encoding="utf-8")
        assert f'IMAGE_REFERENCE = f"{{IMAGE}}@sha256:{postgres_digest}"' in text
        assert re.search(r"docker.{0,500}IMAGE_REFERENCE", text, re.DOTALL)

    observation_runner = (
        ROOT / ".github" / "scripts" / "verify_postgres_writeback_identity_migration.py"
    ).read_text(encoding="utf-8")
    assert f'IMAGE_REFERENCE = f"{{IMAGE}}@sha256:{postgres_digest}"' in observation_runner
    assert "image_reference=IMAGE_REFERENCE" in observation_runner
    assert re.search(r'"docker".{0,500}image_reference', observation_runner, re.DOTALL)

    matrix = (ROOT / ".github" / "scripts" / "verify_postgres_writeback_identity_migration_matrix.py").read_text(
        encoding="utf-8"
    )
    assert "POSTGRES_16_IMAGE_REFERENCE" in matrix
    assert (
        "{POSTGRES_16_IMAGE}@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
        in matrix
    )
    assert "POSTGRES_17_IMAGE_REFERENCE" in matrix
    assert f"POSTGRES_17_IMAGE}}@sha256:{postgres_digest}" in matrix

    for receiver_matrix_name in (
        "verify_postgres_writeback_receiver_idempotency_matrix.py",
        "verify_postgres_writeback_receiver_failover_matrix.py",
    ):
        receiver_matrix = (ROOT / ".github" / "scripts" / receiver_matrix_name).read_text(
            encoding="utf-8"
        )
        assert "POSTGRES_16_IMAGE_REFERENCE" in receiver_matrix
        assert (
            "{POSTGRES_16_IMAGE}@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
            in receiver_matrix
        )
        assert "POSTGRES_17_IMAGE_REFERENCE" in receiver_matrix
        assert f"POSTGRES_17_IMAGE}}@sha256:{postgres_digest}" in receiver_matrix

    airgap = (ROOT / ".github" / "scripts" / "verify_airgap_install.py").read_text(
        encoding="utf-8"
    )
    assert f'IMAGE_REFERENCE = f"{{IMAGE}}@sha256:{python_digest}"' in airgap
    assert "docker_argv.extend((IMAGE_REFERENCE" in airgap


def _mutate_dependabot(root: Path) -> None:
    path = root / ".github" / "dependabot.yml"
    text = path.read_text(encoding="utf-8")
    start = text.index('  - package-ecosystem: "npm"')
    end = text.index('  - package-ecosystem: "docker"')
    path.write_text(text[:start] + text[end:], encoding="utf-8")


def _mutate_gitleaks(root: Path) -> None:
    path = root / ".gitleaks.toml"
    path.write_text(path.read_text(encoding="utf-8") + '\ncommits = ["deadbeef"]\n', encoding="utf-8")


def _mutate_gitleaks_ignore(root: Path) -> None:
    path = root / ".gitleaksignore"
    path.write_text(path.read_text(encoding="utf-8") + "\ntests/**\n", encoding="utf-8")


def _mutate_npm_root(root: Path) -> None:
    path = root / "apps" / "web" / "package-lock.json"
    document = _json(path)
    document["packages"][""]["dependencies"]["react"] = "^18.0.0"
    _write_json(path, document)


def _mutate_release_fail_open(root: Path) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    path.write_text(path.read_text(encoding="utf-8") + "\ncontinue-on-error: true\n", encoding="utf-8")


def _mutate_locked_audit_runner(root: Path) -> None:
    path = root / ".github" / "scripts" / "run_locked_python_audit.py"
    path.write_text(path.read_text(encoding="utf-8").replace('"--require-hashes",', ""), encoding="utf-8")


def _mutate_container_gate_runner(root: Path) -> None:
    path = root / ".github" / "scripts" / "validate_container_security.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace("ignoredMatches", "suppressedMatches"),
        encoding="utf-8",
    )


def _mutate_release_unlocked_audit_environment(root: Path) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "uv sync --locked --extra dev --no-editable --python",
            "uv sync --extra dev --no-editable --python",
        ),
        encoding="utf-8",
    )


def _mutate_release_container_scanner(root: Path) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('SYFT_VERSION: "1.51.0"', 'SYFT_VERSION: "latest"'),
        encoding="utf-8",
    )


def _mutate_release_container_gate_order(root: Path) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    text = path.read_text(encoding="utf-8")
    gate = "Build and enforce the local container security gate"
    path.write_text(text.replace(gate, "Container evidence policy step", 1), encoding="utf-8")


def _mutate_release_post_push_binding(root: Path) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "published manifest bytes do not match the registry digest",
            "registry digest check unavailable",
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "mutator",
    [
        _mutate_pyproject,
        _mutate_uv_source,
        _mutate_docker_base,
        _mutate_docker_context,
        _mutate_service_image,
        _mutate_vex,
        _mutate_dependabot,
        _mutate_gitleaks,
        _mutate_gitleaks_ignore,
        _mutate_npm_root,
        _mutate_release_fail_open,
        _mutate_locked_audit_runner,
        _mutate_container_gate_runner,
        _mutate_release_unlocked_audit_environment,
        _mutate_release_container_scanner,
        _mutate_release_container_gate_order,
        _mutate_release_post_push_binding,
    ],
)
def test_policy_validator_rejects_resolution_or_gate_drift(
    tmp_path: Path, mutator: Callable[[Path], None]
) -> None:
    project = _copy_policy_project(tmp_path)
    mutator(project)

    with pytest.raises(SupplyChainPolicyError):
        POLICY_MODULE.validate_project(project, date(2026, 7, 26))


def test_exception_requires_separation_expiry_and_bounded_lifetime(tmp_path: Path) -> None:
    project = _copy_policy_project(tmp_path)
    registry_path = project / "docs" / "security" / "supply-chain-exceptions.v1.json"
    registry = _json(registry_path)
    valid = _active_exception(ecosystem="python", subject="urllib3", identifier="PYSEC-2026-1")
    registry["exceptions"] = [valid]
    _write_json(registry_path, registry)

    _, active, *_ = POLICY_MODULE.validate_project(project, date(2026, 7, 26))
    assert [item["id"] for item in active] == ["SC-EXC-0001"]

    with pytest.raises(SupplyChainPolicyError, match="expired"):
        POLICY_MODULE.validate_project(project, date(2026, 7, 31))

    valid["approved_by"] = ["dependency-owner", "security-reviewer"]
    _write_json(registry_path, registry)
    with pytest.raises(SupplyChainPolicyError, match="own exception"):
        POLICY_MODULE.validate_project(project, date(2026, 7, 26))

    valid["approved_by"] = ["security-reviewer", "product-reviewer"]
    valid["expires_on"] = "2026-08-15"
    _write_json(registry_path, registry)
    with pytest.raises(SupplyChainPolicyError, match="maximum exception lifetime"):
        POLICY_MODULE.validate_project(project, date(2026, 7, 26))


def test_pip_audit_is_fail_closed_and_exact_exception_is_bounded(tmp_path: Path) -> None:
    report_path = tmp_path / "pip-audit.json"
    clean = {"dependencies": [{"name": "urllib3", "version": "2.7.0", "vulns": []}], "fixes": []}
    _write_json(report_path, clean)
    assert POLICY_MODULE.enforce_pip_audit(report_path, 0, []) == 0

    vulnerable = {
        "dependencies": [
            {
                "name": "urllib3",
                "version": "2.7.0",
                "vulns": [{"id": "PYSEC-2026-1", "aliases": ["CVE-2026-1234"]}],
            }
        ],
        "fixes": [],
    }
    _write_json(report_path, vulnerable)
    with pytest.raises(SupplyChainPolicyError, match="unexcepted Python advisory"):
        POLICY_MODULE.enforce_pip_audit(report_path, 1, [])

    exception = _active_exception(ecosystem="python", subject="urllib3", identifier="CVE-2026-1234")
    assert POLICY_MODULE.enforce_pip_audit(report_path, 1, [exception]) == 1

    with pytest.raises(SupplyChainPolicyError, match="operationally"):
        POLICY_MODULE.enforce_pip_audit(report_path, 2, [exception])
    with pytest.raises(SupplyChainPolicyError, match="disagree"):
        POLICY_MODULE.enforce_pip_audit(report_path, 0, [exception])


def test_npm_audit_fails_high_and_critical_without_exact_exception(tmp_path: Path) -> None:
    report_path = tmp_path / "npm-audit.json"
    clean = {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {}}
    _write_json(report_path, clean)
    assert POLICY_MODULE.enforce_npm_audit(report_path, 0, []) == 0

    high = {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "vite": {
                "severity": "high",
                "via": [
                    {
                        "source": 123456,
                        "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
                    }
                ],
            }
        },
        "metadata": {},
    }
    _write_json(report_path, high)
    with pytest.raises(SupplyChainPolicyError, match="unexcepted high-severity npm advisory"):
        POLICY_MODULE.enforce_npm_audit(report_path, 1, [])

    exception = _active_exception(
        ecosystem="npm",
        subject="vite",
        identifier="https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
    )
    assert POLICY_MODULE.enforce_npm_audit(report_path, 1, [exception]) == 1

    high["vulnerabilities"]["vite"]["severity"] = "critical"
    _write_json(report_path, high)
    with pytest.raises(SupplyChainPolicyError, match="critical npm advisory cannot be excepted"):
        POLICY_MODULE.enforce_npm_audit(report_path, 1, [exception])

    high["vulnerabilities"]["vite"]["severity"] = "high"
    high["vulnerabilities"]["vite"]["via"] = ["transitive-only"]
    _write_json(report_path, high)
    with pytest.raises(SupplyChainPolicyError, match="lacks an exact advisory ID"):
        POLICY_MODULE.enforce_npm_audit(report_path, 1, [exception])


def test_security_and_release_workflows_pin_tools_and_fail_before_registry_write() -> None:
    policy = _json(POLICY_PATH)
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    security = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    audit_runner = SCRIPT_PATH.with_name("run_locked_python_audit.py").read_text(encoding="utf-8")

    for workflow in (release, security):
        assert "continue-on-error" not in workflow
        assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in workflow
        assert f'version: "{policy["python_resolution"]["manager_version"]}"' in workflow
        assert policy["secret_scanning"]["linux_x86_64_archive_sha256"] in workflow
        assert "--redact=100" in workflow
        assert ".github/scripts/run_locked_python_audit.py" in workflow
        assert "--npm-audit-exit-code" in workflow
        assert f'SYFT_VERSION: "{policy["container_audits"]["sbom"]["version"]}"' in workflow
        assert f'GRYPE_VERSION: "{policy["container_audits"]["vulnerability"]["version"]}"' in workflow
        assert ".github/scripts/validate_container_security.py" in workflow

    assert '"--require-hashes"' in audit_runner
    assert '"--disable-pip"' in audit_runner
    assert '"--pip-audit-exit-code"' in audit_runner

    assert "required-security-context:" in security
    assert "name: python-security" in security
    assert "needs: [python-security, repository-security, container-security]" in security
    assert "if: ${{ always() }}" in security
    assert "needs.python-security.result" in security
    assert "needs.repository-security.result" in security

    registry_login = release.index("docker/login-action@")
    for gate in (
        "Validate closed supply-chain policy and current lock",
        "Audit the hash-locked Python and server resolution",
        "Scan full Git history with redacted output",
        "Scan checked-out tree with redacted output",
        "Audit the npm lock",
        "Generate exact-image SBOM and vulnerability inputs",
        "Build and enforce the local container security gate",
    ):
        assert 0 <= release.index(gate) < registry_login

    assert "name: Exact-image SBOM, vulnerability, and license gate" in security
    assert "needs: [python-security, repository-security, container-security]" in security
    assert "needs.container-security.result" in security

    for workflow in ROOT.joinpath(".github", "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for action in re.findall(r"uses:\s+[^\s]+@([^\s#]+)", text):
            assert re.fullmatch(r"[0-9a-f]{40}", action), f"floating action in {workflow.name}: {action}"
