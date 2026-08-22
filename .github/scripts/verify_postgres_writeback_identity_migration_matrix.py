"""Verify write-back identity migration refusal and restore across a closed PostgreSQL matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_RUNNER = ROOT / ".github/scripts/verify_postgres_writeback_identity_migration.py"
MIGRATION_PATH = ROOT / "alembic/versions/0089_postgres_writeback_proposal_identity.py"
SUPPLY_CHAIN_POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"

POSTGRES_16_IMAGE = "postgres:16-alpine"
POSTGRES_16_IMAGE_REFERENCE = (
    f"{POSTGRES_16_IMAGE}@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
POSTGRES_17_IMAGE = "postgres:17.10-alpine"
POSTGRES_17_IMAGE_REFERENCE = (
    f"{POSTGRES_17_IMAGE}@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)

RUNTIME_PROFILES = (
    {
        "postgresql": "16.14",
        "image": POSTGRES_16_IMAGE_REFERENCE,
        "container_prefix": "reconforge-writeback-matrix-pg16",
    },
    {
        "postgresql": "17.10",
        "image": POSTGRES_17_IMAGE_REFERENCE,
        "container_prefix": "reconforge-writeback-matrix-pg17",
    },
)


class MatrixError(RuntimeError):
    """Raised when the closed PostgreSQL migration matrix is not proven."""


def _canonical_digest(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    report["report_digest"] = _canonical_digest(report)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_observation_functions() -> tuple[Callable[..., dict[str, Any]], Callable[[], str]]:
    namespace = runpy.run_path(str(OBSERVATION_RUNNER), run_name="reconforge_e827_observation_runner")
    run_observation = cast(Callable[..., dict[str, Any]], namespace["run_observation"])
    migration_commit = cast(Callable[[], str], namespace["_migration_commit"])
    return run_observation, migration_commit


def run_matrix(output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    run_observation, migration_commit = _load_observation_functions()
    runs = [
        run_observation(
            image_reference=profile["image"],
            expected_postgresql=profile["postgresql"],
            container_prefix=profile["container_prefix"],
        )
        for profile in RUNTIME_PROFILES
    ]
    versions = [str(run["runtime"]["postgresql"]) for run in runs]
    if versions != ["16.14", "17.10"]:
        raise MatrixError("PostgreSQL migration matrix version order drifted")
    if len({str(run["runtime"]["docker_server"]) for run in runs}) != 1:
        raise MatrixError("PostgreSQL migration matrix did not use one disclosed Docker runtime")
    valid_digests = {str(run["history"]["valid_history_sha256"]) for run in runs}
    invalid_digests = {str(run["history"]["invalid_history_sha256"]) for run in runs}
    if len(valid_digests) != 1 or len(invalid_digests) != 1:
        raise MatrixError("PostgreSQL versions produced different canonical write-back histories")
    if any(not all(bool(value) for value in run["checks"].values()) for run in runs):
        raise MatrixError("PostgreSQL migration matrix contains a failed check")

    report = {
        "schema_version": "postgres-writeback-identity-migration-matrix-v1",
        "executed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "profile": "disposable-postgresql-writeback-identity-migration-matrix",
        "subject": {
            "migration_commit": migration_commit(),
            "migration_source_sha256": _source_digest(MIGRATION_PATH),
            "observation_runner_source_sha256": _source_digest(OBSERVATION_RUNNER),
            "matrix_runner_source_sha256": _source_digest(Path(__file__)),
            "supply_chain_policy_sha256": _source_digest(SUPPLY_CHAIN_POLICY_PATH),
        },
        "runs": runs,
        "parity": {
            "postgresql_versions": versions,
            "source_revision": str(runs[0]["runtime"]["source_revision"]),
            "target_revision": str(runs[0]["runtime"]["target_revision"]),
            "valid_history_sha256": valid_digests.pop(),
            "invalid_history_sha256": invalid_digests.pop(),
            "all_checks_passed": True,
            "all_cleanup_complete": all(bool(run["checks"]["cleanup_complete"]) for run in runs),
        },
        "limitations": [
            "single_docker_desktop_host",
            "two_postgresql_versions_only",
            "sequential_single_node_runs",
            "synthetic_data_and_credentials_only",
            "no_live_provider_or_accounting_posting",
            "no_cross_host_ha_dr_or_production_claim",
        ],
    }
    _write_report(output, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = run_matrix(arguments.output.resolve(strict=False))
    print(
        "postgres_writeback_identity_migration_matrix=passed "
        f"versions={','.join(report['parity']['postgresql_versions'])} "
        f"report_digest={report['report_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
