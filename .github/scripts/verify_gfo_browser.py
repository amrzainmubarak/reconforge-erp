"""Owned PostgreSQL 17 + integrated HTTPS Chrome receipt and job acceptance gate.

Requires a built apps/web/dist, installed web dev dependencies and Playwright
Chromium. Fixtures are synthetic; credentials stay in memory and child environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import ssl
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reconforge.infrastructure.postgres import PostgresTenantBoundary  # noqa: E402
from tests.gfo_browser_runtime import seed_browser_jobs  # noqa: E402
from tests.gfo_receipt_browser_seed import seed_receipt_browser  # noqa: E402
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime  # noqa: E402

IMAGE = "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"


def source_digest(directory: Path = ROOT) -> str:
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=directory).decode().split("\0")  # nosec B603 B607
    digest = hashlib.sha256()
    for name in sorted(filter(None, files)):
        digest.update(name.encode())
        digest.update(hashlib.sha256((directory / name).read_bytes()).digest())
    return digest.hexdigest()


def built_web_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_persisted_browser_effects(runtime: ReceiptRuntime) -> dict[str, object]:
    # Every read uses the same non-owner boundary as the actual HTTPS server.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work",
                                                             organization_id="org", legal_entity_id="entity") as connection:
        states = {row["id"]: row["status"] for row in connection.execute(
            "SELECT id,status FROM reconforge.durable_jobs WHERE tenant_id=%s", (runtime.tenant,))}
        assert states == {"GFO-job-failed": "queued", "GFO-job-queued": "cancelled"}
        plan_rows = connection.execute(
            "SELECT p.id,r.reviewer_actor_id,p.preparer_actor_id,l.posting_effect_id FROM reconforge.inventory_receipt_plans p "
            "JOIN reconforge.inventory_receipt_reviews r ON r.tenant_id=p.tenant_id AND r.plan_id=p.id "
            "JOIN reconforge.inventory_receipt_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id "
            "WHERE p.tenant_id=%s", (runtime.tenant,)).fetchall()
        assert len(plan_rows) == 2 and all(row["reviewer_actor_id"] != row["preparer_actor_id"] for row in plan_rows)
        effect_count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        assert effect_count == 2
        layers = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        assert len(layers) == 1 and dict(layers[0]) == {"remaining_quantity_scaled": 0, "remaining_value_minor": 0}
        transitions = connection.execute("SELECT count(*) n FROM reconforge.durable_job_transitions WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        assert transitions == 6
        return {"job_states": states, "job_transitions": transitions, "committed_receipt_plans": len(plan_rows),
                "retained_original_and_inverse_finance_effects": effect_count,
                "remaining_stock_quantity_scaled": 0, "remaining_stock_value_minor": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "output/gfo-browser")
    parser.add_argument("--web-root", type=Path, default=ROOT / "apps/web/dist")
    args = parser.parse_args()
    runtime_root = args.runtime_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not (args.web_root / "index.html").is_file():
        raise ValueError("Build the integrated Studio before running browser acceptance.")
    name = "reconforge-gfo-browser-" + uuid4().hex[:12]
    admin_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
    secret_values = [admin_password, app_password]
    container = ""
    server = None
    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(), "image": IMAGE,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=runtime_root, text=True).strip(),  # nosec B603 B607
        "source_sha256": source_digest(runtime_root), "runtime_root": str(runtime_root),
        "tooling_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "built_web_sha256": built_web_digest(args.web_root.resolve()), "status": "failed",
    }
    started = time.monotonic()
    def run(argv: list[str], *, environment: dict[str, str] | None = None, check: bool = True, directory: Path = ROOT) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(argv, cwd=directory, env=environment, capture_output=True, text=True, timeout=240)  # nosec B603
        if check and result.returncode:
            diagnostic = result.stdout + result.stderr
            for value in secret_values:
                diagnostic = diagnostic.replace(value, "[redacted]")
            raise RuntimeError(diagnostic)
        return result
    try:
        environment = os.environ.copy()
        environment["POSTGRES_PASSWORD"] = admin_password
        container = run(["docker", "run", "--detach", "--rm", "--name", name,
                         "--label", "reconforge.owner=gfo-browser", "-e", "POSTGRES_PASSWORD",
                         "-p", "127.0.0.1::5432", IMAGE], environment=environment).stdout.strip()
        port = run(["docker", "port", container, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1]
        admin_dsn = f"postgresql://postgres:{admin_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        app_dsn = f"postgresql://gfo_browser_app:{app_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(admin_dsn, autocommit=True) as admin:
                    admin.execute(sql.SQL("CREATE ROLE gfo_browser_app LOGIN PASSWORD {}").format(sql.Literal(app_password)))
                    report["postgres_version"] = admin.execute("SHOW server_version").fetchone()[0]
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
        environment["RECONFORGE_POSTGRES_DSN"] = admin_dsn
        migration = run([sys.executable, "-m", "alembic", "upgrade", "head"], environment=environment, directory=runtime_root)
        (output / "migration.log").write_text(migration.stdout + migration.stderr, encoding="utf-8")
        with psycopg.connect(admin_dsn) as admin:
            admin.execute("GRANT USAGE ON SCHEMA reconforge TO gfo_browser_app")
            admin.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO gfo_browser_app")
            admin.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO gfo_browser_app")
            report["revision"] = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        with psycopg.connect(app_dsn) as connection:
            role_flags = list(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())
            assert role_flags == [False, False]
            report["role_privileges"] = role_flags
        runtime = seed_receipt_browser(admin_dsn, app_dsn)
        secret_values.append(runtime.password)
        seed_browser_jobs(runtime)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            https_port = listener.getsockname()[1]
        url = f"https://localhost:{https_port}"
        environment.update(RECONFORGE_GFO_APP_DSN=app_dsn, RECONFORGE_GFO_WEB_ROOT=str(args.web_root.resolve()),
            RECONFORGE_GFO_HTTPS_PORT=str(https_port), RECONFORGE_GFO_LIVE_URL=url,
            RECONFORGE_GFO_RECEIPT_TENANT=runtime.tenant, RECONFORGE_GFO_RECEIPT_PASSWORD=runtime.password,
            RECONFORGE_GFO_JOB_TENANT=runtime.tenant, RECONFORGE_GFO_JOB_WORKSPACE="work",
            RECONFORGE_GFO_JOB_ORGANIZATION="org", RECONFORGE_GFO_JOB_ENTITY="entity",
            RECONFORGE_GFO_LIVE_PASSWORD=runtime.password, RECONFORGE_GFO_BROWSER_REPORT=str(output / "playwright.json"))
        with (output / "https-runtime.log").open("w", encoding="utf-8") as log:
            runtime_command = "import sys; sys.path.insert(0, sys.argv[1]); from tests.gfo_browser_runtime import main; main()"
            server = subprocess.Popen([sys.executable, "-c", runtime_command, str(runtime_root)], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)  # nosec B603
            # Only the generated, owned localhost certificate is trusted here.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            deadline = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Owned HTTPS runtime exited; inspect https-runtime.log")
                try:
                    with urllib.request.urlopen(url + "/api/v1/health", context=context, timeout=1) as response:  # nosec B310
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Owned HTTPS readiness timeout") from None
                    time.sleep(.2)
            executable = "npx.cmd" if os.name == "nt" else "npx"
            browser = run([executable, "--prefix", "apps/web", "playwright", "test", "--config", "apps/web/live/gfo.playwright.config.ts"], environment=environment, check=False)
            (output / "browser.log").write_text(browser.stdout + browser.stderr, encoding="utf-8")
            report["browser_exit_code"] = browser.returncode
        if (output / "playwright.json").is_file():
            report["browser_counts"] = json.loads((output / "playwright.json").read_text(encoding="utf-8"))["stats"]
        if browser.returncode == 0:
            report["persisted_effects"] = verify_persisted_browser_effects(runtime)
        report["built_web_unchanged"] = built_web_digest(args.web_root.resolve()) == report["built_web_sha256"]
        report["source_unchanged"] = source_digest(runtime_root) == report["source_sha256"]
        report["status"] = "passed" if browser.returncode == 0 and report["source_unchanged"] and report["built_web_unchanged"] else "failed"
    except Exception as exc:
        diagnostic = str(exc)
        for value in secret_values:
            diagnostic = diagnostic.replace(value, "[redacted]")
        report["error"] = diagnostic
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            report["owned_https_process_stopped"] = True
        if container:
            assert run(["docker", "inspect", "--format", "{{.Id}}", name]).stdout.strip() == container
            run(["docker", "stop", "--time", "5", container])
            for _ in range(50):
                if not run(["docker", "ps", "-aq", "--filter", f"id={container}"]).stdout.strip():
                    report["owned_container_removed"] = True
                    break
                time.sleep(.1)
        report["wall_seconds"] = round(time.monotonic() - started, 3)
        for filename in ("browser.log", "playwright.json", "https-runtime.log", "migration.log"):
            path = output / filename
            if path.exists():
                report[filename + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
