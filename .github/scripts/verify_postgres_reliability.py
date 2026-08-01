"""Run the live PostgreSQL reliability-source parity drill in disposable Docker."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess  # nosec B404
import time
import uuid
from pathlib import Path
from typing import Any

IMAGE = "postgres:17.10-alpine"


def _run(
    argv: list[str], *, env: dict[str, str] | None = None, check: bool = True, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        argv, cwd=Path(__file__).resolve().parents[2], env=env, check=check,
        input=input_text, capture_output=True, text=True, timeout=180,
    )


def run_drill() -> dict[str, Any]:
    name = "reconforge-reliability-" + uuid.uuid4().hex[:12]
    postgres_password = "rf" + secrets.token_hex(24)
    app_password = "rf" + secrets.token_hex(24)
    cleanup = False
    test_passed = False
    migration_head = ""
    try:
        _run([
            "docker", "run", "--rm", "-d", "--name", name,
            "-e", f"POSTGRES_PASSWORD={postgres_password}", "-p", "127.0.0.1::5432", IMAGE,
        ])
        for _ in range(120):
            probe = _run(
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres"],
                check=False,
            )
            if probe.returncode == 0 and "accepting connections" in probe.stdout:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("PostgreSQL readiness timeout")
        port = _run(["docker", "port", name, "5432/tcp"]).stdout.strip().rsplit(":", 1)[-1]
        _run([
            "docker", "exec", "-i", name, "psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-f", "-",
        ], input_text=f"CREATE ROLE reconforge_app LOGIN PASSWORD '{app_password}';\n")
        environment = os.environ.copy()
        environment["RECONFORGE_POSTGRES_DSN"] = (
            f"postgresql+psycopg://postgres:{postgres_password}@localhost:{port}/postgres"
        )
        _run(["uv", "run", "--locked", "alembic", "-c", "alembic.ini", "upgrade", "head"], env=environment)
        environment.update(
            RECONFORGE_TEST_POSTGRES_ADMIN_DSN=(
                f"postgresql://postgres:{postgres_password}@localhost:{port}/postgres"
            ),
            RECONFORGE_TEST_POSTGRES_DSN=(
                f"postgresql://reconforge_app:{app_password}@localhost:{port}/postgres"
            ),
            RECONFORGE_TEST_POSTGRES_APP_USER="reconforge_app",
        )
        test_result = _run([
            "uv", "run", "--locked", "pytest",
            "tests/test_reliability_sources.py::test_live_postgres_reliability_sources_are_rls_scoped", "-q",
        ], env=environment, check=False)
        if test_result.returncode != 0:
            diagnostic = (test_result.stdout + test_result.stderr).replace(postgres_password, "[redacted]").replace(
                app_password, "[redacted]"
            )
            raise RuntimeError("Live PostgreSQL reliability test failed:\n" + diagnostic)
        test_passed = True
        migration_head = _run([
            "docker", "exec", name, "psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres",
            "-At", "-c", "SELECT version_num FROM alembic_version",
        ]).stdout.strip()
        image_digest = _run(["docker", "image", "inspect", IMAGE, "--format", "{{index .RepoDigests 0}}"]).stdout.strip()
        docker_version = _run(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip()
    finally:
        removed = _run(["docker", "rm", "-f", name], check=False)
        cleanup = removed.returncode == 0 or "No such container" in removed.stderr
    return {
        "schema_version": 1,
        "profile": "disposable-postgresql-reliability-source-parity",
        "runtime": {"docker_server": docker_version, "image": image_digest, "migration_head": migration_head},
        "checks": {
            "fresh_migration_to_head": migration_head == "0053_audit_administration_acl",
            "non_superuser_forced_rls_test_passed": test_passed,
            "sibling_tenant_excluded": test_passed,
            "job_depth_and_age_exact": test_passed,
            "audit_verification_aggregate": test_passed,
            "cleanup_complete": cleanup,
        },
        "limitations": [
            "single_postgresql_node",
            "synthetic_data_and_credentials_only",
            "no_repeated_load_or_capacity_measurement",
            "no_production_slo_or_ha_claim",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_drill()
    if not all(report["checks"].values()):
        raise SystemExit("PostgreSQL reliability drill failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
