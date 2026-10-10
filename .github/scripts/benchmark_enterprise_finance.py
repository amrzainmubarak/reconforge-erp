"""Owned PostgreSQL benchmark of genuine three-human posting and verified reads.

Every entry is prepared, independently reviewed and posted through native
repositories. The generator inserts canonical synthetic masters only. No secrets
or DSNs enter the evidence packet. Resource caps are explicit and failures remain
failures. This is a single-entity USD financial profile, not a global ERP claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import subprocess  # nosec B404
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reconforge.benchmark.enterprise_financial import (  # noqa: E402
    amount_minor,
    expected_totals,
    measure_verified_reads,
    percentile,
)
from reconforge.benchmark.enterprise_posting_profile import PostingProfile  # noqa: E402
from reconforge.benchmark.resource_sampling import ResourceSampler  # noqa: E402
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository  # noqa: E402
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository  # noqa: E402
from tests.erp_expansion_browser_seed import seed_expansion_browser  # noqa: E402

IMAGE = "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=int, nargs="+", default=[100, 1000])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-seconds", type=int, default=1200)
    parser.add_argument("--seed", default="enterprise-native-v1")
    parser.add_argument("--profile-stages", action="store_true", help="Retain redacted client phase and SQL-template timings")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    counts = sorted(set(args.counts))
    if (not counts or counts[0] < 1 or counts[-1] > 10000 or not 1 <= args.workers <= 16
            or not 1 <= args.repetitions <= 10 or not 30 <= args.max_seconds <= 7200):
        parser.error("Use counts 1..10000, workers 1..16, repetitions 1..10 and a bounded 30..7200 second budget")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "result.json").exists():
        raise ValueError("Preserve prior evidence; choose a fresh output directory")
    secret_values: list[str] = []

    def run(argv: list[str], *, environment: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=600)  # nosec B603
        if check and result.returncode:
            diagnostic = result.stdout + result.stderr
            for value in secret_values:
                diagnostic = diagnostic.replace(value, "[redacted]")
            raise RuntimeError(diagnostic)
        return result

    status = run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout
    if status:
        raise ValueError("Benchmark requires a fixed committed tracked source")
    def tracked_source_sha256() -> str:
        names = filter(None, run(["git", "ls-files", "-z"]).stdout.split("\0"))
        source_digest = hashlib.sha256()
        for name in sorted(names):
            source_digest.update(name.encode())
            source_digest.update(hashlib.sha256((ROOT / name).read_bytes()).digest())
        return source_digest.hexdigest()

    report: dict[str, object] = {
        "schema_version": 2, "started_at": datetime.now(UTC).isoformat(), "status": "failed",
        "source_commit": run(["git", "rev-parse", "HEAD"]).stdout.strip(), "source_sha256": tracked_source_sha256(),
        "profile": "native-three-human-cash-equity-v1", "seed": args.seed, "counts": counts,
        "workers": args.workers, "repetitions": args.repetitions, "max_seconds": args.max_seconds,
        "image": IMAGE, "python": sys.version, "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "processor": platform.processor(), "architecture": platform.machine(),
        "docker_version": run(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip(),
        "limits": ["single entity and USD", "native repository latency includes synthetic identity authentication",
            "not HTTP latency", "no comparable competitor measurement", "no cost per transaction without a supplied resource cost model"],
        "cost_per_transaction": None,
        "runtime_root": str(ROOT), "launch_cwd": str(Path.cwd()), "command": [sys.executable, *sys.argv],
        "module_origins": {"posting": str(Path(sys.modules[PostgresFinancePostingRepository.__module__].__file__).resolve()),
                           "core": str(Path(sys.modules[PostgresFinanceCoreRepository.__module__].__file__).resolve())},
        "telemetry_policy": "read-only 10-second sampled resources on owned synthetic fixture; no production DSN or row content",
    }
    started = time.monotonic()
    deadline = started + args.max_seconds
    container = ""
    sampler: ResourceSampler | None = None
    posting_profile = PostingProfile(args.profile_stages)
    admin_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
    secret_values.extend([admin_password, app_password])
    try:
        engine = json.loads(run(["docker", "info", "--format", "{{json .}}"]).stdout)
        report["docker_engine_resources"] = {name: engine.get(name) for name in (
            "OperatingSystem", "OSType", "Architecture", "KernelVersion", "NCPU", "MemTotal", "Driver")}
        environment = os.environ.copy()
        environment["POSTGRES_PASSWORD"] = admin_password
        container = run(["docker", "run", "--detach", "--rm", "--name", "reconforge-enterprise-finance-" + uuid4().hex[:12],
            "--label", "reconforge.owner=enterprise-finance-benchmark", "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", IMAGE], environment=environment).stdout.strip()
        port = run(["docker", "port", container, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1]
        admin_dsn = f"postgresql://postgres:{admin_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        app_dsn = f"postgresql://enterprise_benchmark:{app_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        for attempt in range(300):
            try:
                with psycopg.connect(admin_dsn, autocommit=True) as admin:
                    admin.execute(sql.SQL("CREATE ROLE enterprise_benchmark LOGIN PASSWORD {}").format(sql.Literal(app_password)))
                    report["postgres_version"] = admin.execute("SHOW server_version").fetchone()[0]
                break
            except psycopg.OperationalError:
                if attempt == 299:
                    raise
                time.sleep(.2)
        environment["RECONFORGE_POSTGRES_DSN"] = admin_dsn
        migration = run([sys.executable, "-m", "alembic", "upgrade", "head"], environment=environment)
        (output / "migration.log").write_text(migration.stdout + migration.stderr, encoding="utf-8")
        with psycopg.connect(admin_dsn) as admin:
            admin.execute("GRANT USAGE ON SCHEMA reconforge TO enterprise_benchmark")
            admin.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO enterprise_benchmark")
            admin.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO enterprise_benchmark")
            report["revision"] = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            report["postgres_configuration"] = dict(admin.execute(
                "SELECT name,setting FROM pg_settings WHERE name=ANY(%s)",
                (["shared_buffers", "work_mem", "max_connections", "fsync", "synchronous_commit", "full_page_writes", "wal_level", "track_io_timing"],)).fetchall())
            report["postgres_io_timing_interpretation"] = (
                "blk_read_time_ms/blk_write_time_ms are cumulative pg_stat_database counters; "
                "zero milliseconds with track_io_timing=off do not prove zero I/O latency; no I/O peak is measured")
        with psycopg.connect(app_dsn) as connection:
            flags = list(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())
            if flags != [False, False]:
                raise AssertionError("Benchmark runtime must be a nonowner without RLS bypass")
            report["runtime_role_flags"] = flags
        runtime = seed_expansion_browser(admin_dsn, app_dsn)
        secret_values.append(runtime.password)

        def observe() -> dict[str, object]:
            # Separate diagnostic owner connection. Business operations remain on the nonowner role.
            with psycopg.connect(admin_dsn, autocommit=True) as diagnostic:
                diagnostic.execute("SET statement_timeout='5s'")
                database = diagnostic.execute("""SELECT xact_commit,xact_rollback,blks_read,blks_hit,
                    tup_returned,tup_fetched,tup_inserted,tup_updated,tup_deleted,conflicts,temp_files,temp_bytes,
                    deadlocks,blk_read_time,blk_write_time FROM pg_stat_database WHERE datname=current_database()""").fetchone()
                wal = diagnostic.execute("SELECT wal_records,wal_fpi,wal_bytes::text FROM pg_stat_wal").fetchone()
                waits = diagnostic.execute("""SELECT coalesce(wait_event_type,'none'),count(*)
                    FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
                    GROUP BY wait_event_type ORDER BY 1""").fetchall()
            resources = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container],
                cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)  # nosec B603
            raw = json.loads(resources.stdout)
            return {"postgres_database_counters": dict(zip(("xact_commit", "xact_rollback", "blks_read", "blks_hit",
                "tup_returned", "tup_fetched", "tup_inserted", "tup_updated", "tup_deleted", "conflicts",
                "temp_files", "temp_bytes", "deadlocks", "blk_read_time_ms", "blk_write_time_ms"), database, strict=True)),
                "postgres_wal_counters": dict(zip(("wal_records", "wal_fpi", "wal_bytes"), wal, strict=True)),
                "postgres_wait_event_type_sessions": dict(waits),
                "docker_raw_counters": {key: raw.get(key) for key in ("CPUPerc", "MemUsage", "MemPerc", "NetIO", "BlockIO", "PIDs")}}

        sampler = ResourceSampler(observe)
        sampler.start()
        with runtime.actor("browser-maker") as (connection, _, _actor):
            accounts = {row["account_code"]: row["id"] for row in connection.execute(
                "SELECT id,account_code FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id='work' AND account_code IN ('CASH','EQUITY')", (runtime.tenant,)).fetchall()}

        def post(index: int) -> tuple[str, float]:
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit native benchmark resource budget exhausted")
            value = amount_minor(args.seed, index)
            exact_amount = f"{value // 100}.{value % 100:02d}"
            begin = time.perf_counter()
            with posting_profile.actor(runtime, "browser-maker", index, "prepare") as (connection, _, actor):
                entry = PostgresFinanceCoreRepository(connection, runtime.tenant).create_entry(
                    entry_number=f"BENCH-{index:08d}", organization_code="ORG", entity_code="ENTITY", period_id="period",
                    journal_code="STOCK", posting_date="2026-10-08", description="Deterministic synthetic benchmark",
                    workspace="work", actor_label=actor.username,
                    lines=[{"account_code": "CASH", "debit": exact_amount}, {"account_code": "EQUITY", "credit": exact_amount}])
            with posting_profile.actor(runtime, "browser-checker", index, "review") as (connection, _, actor):
                PostgresFinanceCoreRepository(connection, runtime.tenant).validate_entry(entry["id"], reason="Independent benchmark review", actor_label=actor.username)
                preview = PostgresFinancePostingRepository(connection, runtime.tenant).preview(entry["id"], actor=actor)
            with posting_profile.actor(runtime, "browser-poster", index, "post") as (connection, _, actor):
                effect = PostgresFinancePostingRepository(connection, runtime.tenant).post(entry["id"],
                    command_id=f"benchmark-post-{index:08d}", expected_validation_digest=preview["validation_digest"],
                    reason="Explicit benchmark financial posting", actor=actor)
                actual = {(line["account_id"], int(line["debit_minor"]), int(line["credit_minor"])) for line in effect["snapshot"]["lines"]}
                if actual != {(accounts["CASH"], value, 0), (accounts["EQUITY"], 0, value)}:
                    raise AssertionError("Actual native posting differs from independent financial oracle")
            return str(effect["id"]), time.perf_counter() - begin

        posting_started = time.perf_counter()
        completed: dict[int, tuple[str, float]] = {}
        failures: list[dict[str, object]] = []
        admitted = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            pending = {}
            while admitted < counts[-1] or pending:
                # Bound queued work as well as workers. Stop admitting on the first actual failure.
                while not failures and admitted < counts[-1] and len(pending) < args.workers * 2:
                    pending[executor.submit(post, admitted)] = admitted
                    admitted += 1
                if not pending:
                    break
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    index = pending.pop(future)
                    try:
                        completed[index] = future.result()
                    except Exception as exc:
                        failures.append({"index": index, "exception_type": type(exc).__name__})
        posted = [completed[index] for index in sorted(completed)]
        posting_seconds = time.perf_counter() - posting_started
        report["posting"] = {"completed_cycles": len(posted), "concurrency": args.workers, "seconds": posting_seconds,
            "native_postings_per_second": len(posted) / posting_seconds, "error_count": 0,
            "requested_cycles": counts[-1], "admitted_cycles": admitted, "failed_cycles": failures,
            "not_admitted_cycles": counts[-1] - admitted, "completed_indices": sorted(completed),
            "cycle_latency_seconds": {key: percentile([row[1] for row in posted], fraction) for key, fraction in (("p50", .5), ("p95", .95), ("p99", .99))} if posted else None,
            "expected": expected_totals(args.seed, len(posted)) if not failures and posted else None}
        report["posting"]["error_count"] = len(failures)
        report["posting"]["raw_cycle_latency_seconds"] = [row[1] for row in posted]
        report["posting"]["ordered_effect_ids"] = [row[0] for row in posted]
        if failures:
            raise RuntimeError("Native posting profile failed; retained successful and failed admissions are not acceptance")
        profiles: list[dict[str, object]] = []
        report["verified_reads"] = profiles
        for count in counts:
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit native benchmark resource budget exhausted")
            profile = {"count": count, "expected": expected_totals(args.seed, count), "status": "running"}
            profiles.append(profile)
            try:
                with runtime.actor("browser-checker") as (connection, _, actor):
                    measured = measure_verified_reads(connection, runtime.tenant, [row[0] for row in posted[:count]], actor,
                        repetitions=args.repetitions, evidence_sink=profile)
                if measured["samples"]["bounded_batch"][0]["debit_minor"] != expected_totals(args.seed, count)["debit_minor"]:
                    raise AssertionError("Measured retained history differs from independent profile total")
                profile["status"] = "passed"
            except Exception as exc:
                profile.update(status="failed", failure={"exception_type": type(exc).__name__})
                raise
        with psycopg.connect(admin_dsn) as admin:
            report["database_bytes"] = int(admin.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        report["container_resources_final_sample"] = run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container]).stdout.strip()
        report["source_commit_after"] = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        report["source_sha256_after"] = tracked_source_sha256()
        report["source_unchanged"] = (report["source_commit"] == report["source_commit_after"]
            and report["source_sha256"] == report["source_sha256_after"])
        if run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout or not report["source_unchanged"]:
            raise AssertionError("Tracked source changed during benchmark")
        report["status"] = "passed"
    except Exception as exc:
        diagnostic = f"{type(exc).__name__}: {exc}"
        for value in secret_values:
            diagnostic = diagnostic.replace(value, "[redacted]")
        report["failure"] = diagnostic
    finally:
        report["posting_profile"] = posting_profile.report()
        if sampler is not None:
            report["resource_sampling"] = sampler.stop()
        if container:
            report["owned_container_removed"] = run(["docker", "rm", "--force", container], check=False).returncode == 0
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["wall_seconds"] = time.monotonic() - started
        (output / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "wall_seconds": report["wall_seconds"]}))
    return 0 if report["status"] == "passed" and report.get("owned_container_removed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
