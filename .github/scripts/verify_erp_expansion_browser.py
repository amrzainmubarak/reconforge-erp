"""Owned PostgreSQL 17 + normal HTTPS expansion cycles and populated native recovery gate.

Requires a built apps/web/dist, installed web dev dependencies and Playwright
Chromium. Fixtures are synthetic; credentials stay in memory and child environment.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
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

from tests.erp_expansion_browser_restore import (  # noqa: E402
    EXPANSION_TABLES,
    verify_expansion_cycles,
    verify_expansion_native_restore,
)
from tests.erp_expansion_browser_seed import seed_expansion_browser  # noqa: E402

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


def tracked_status(directory: Path) -> str:
    """Retain dirty paths as evidence without exporting their file contents."""
    return subprocess.check_output(  # nosec B603 B607
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=directory, text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-native-restore", action="store_true")
    parser.add_argument("--scenario", choices=("expansion", "commerce", "procurement", "snapshots", "collections", "landed-cost", "fixed-assets"), default="expansion")
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "output/erp-expansion-20261009/browser")
    parser.add_argument("--web-root", type=Path, default=ROOT / "apps/web/dist")
    args = parser.parse_args()
    seed = seed_expansion_browser
    verify_cycles = verify_expansion_cycles
    configuration = "apps/web/live/erp-expansion.playwright.config.ts"
    extension_tables = EXPANSION_TABLES
    tamper_statements = (
        "UPDATE reconforge.stock_sales_orders SET total_minor=total_minor+1,row_version=row_version+1 WHERE tenant_id=%s",
        "UPDATE reconforge.financial_installment_links SET posted_actor_id='maker' WHERE tenant_id=%s",
        "UPDATE reconforge.financial_opening_links SET posted_actor_id='maker' WHERE tenant_id=%s",
    )
    if args.scenario == "commerce":
        from tests.stock_commerce_browser_seed import seed_stock_commerce_browser, verify_stock_commerce_browser
        seed, verify_cycles = seed_stock_commerce_browser, verify_stock_commerce_browser
        configuration = "apps/web/live/stock-commerce.playwright.config.ts"
        extension_tables = EXPANSION_TABLES + ("stock_commerce_orders", "stock_commerce_lines", "stock_commerce_tranches", "stock_commerce_commands")
        tamper_statements = (
            "UPDATE reconforge.stock_commerce_orders SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.stock_commerce_lines SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.stock_commerce_tranches SET stock_order_id='forged' WHERE tenant_id=%s",
        )
    elif args.scenario == "procurement":
        from tests.erp_procurement_enterprise_browser import (
            PROCUREMENT_ENTERPRISE_TABLES,
            seed_procurement_enterprise_browser,
            verify_procurement_enterprise_browser,
        )
        seed, verify_cycles = seed_procurement_enterprise_browser, verify_procurement_enterprise_browser
        configuration = "apps/web/live/erp-procurement-enterprise.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + PROCUREMENT_ENTERPRISE_TABLES))
        tamper_statements = (
            "UPDATE reconforge.procurement_partial_orders SET total_minor=total_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.procurement_partial_order_lines SET quantity=quantity+1 WHERE tenant_id=%s",
            "UPDATE reconforge.financial_installment_links SET posted_actor_id='maker' WHERE tenant_id=%s",
        )
    elif args.scenario == "snapshots":
        from tests.enterprise_financial_snapshot_browser import (
            seed_financial_snapshot_browser,
            verify_financial_snapshot_browser,
        )
        seed, verify_cycles = seed_financial_snapshot_browser, verify_financial_snapshot_browser
        configuration = "apps/web/live/financial-snapshots.playwright.config.ts"
        extension_tables = EXPANSION_TABLES + ("financial_report_captures", "financial_report_members", "financial_report_snapshots")
        tamper_statements = (
            "UPDATE reconforge.financial_report_captures SET membership_sealed=false WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_report_members WHERE tenant_id=%s",
            "UPDATE reconforge.financial_report_snapshots SET report_digest=repeat('0',64) WHERE tenant_id=%s",
        )
    elif args.scenario == "collections":
        from tests.commercial_collections_browser import (
            COLLECTION_TABLES,
            seed_commercial_collections_browser,
            verify_commercial_collections_browser,
        )
        seed, verify_cycles = seed_commercial_collections_browser, verify_commercial_collections_browser
        configuration = "apps/web/live/commercial-collections.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + COLLECTION_TABLES))
        tamper_statements = (
            "UPDATE reconforge.commercial_collection_plans SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.commercial_collection_links SET posted_actor_id='maker' WHERE tenant_id=%s",
            "DELETE FROM reconforge.commercial_collection_commands WHERE tenant_id=%s",
        )
    elif args.scenario == "landed-cost":
        from tests.erp_landed_cost_browser import (
            LANDED_COST_BROWSER_TABLES,
            seed_landed_cost_browser,
            verify_landed_cost_browser,
        )
        seed, verify_cycles = seed_landed_cost_browser, verify_landed_cost_browser
        configuration = "apps/web/live/erp-landed-cost.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + LANDED_COST_BROWSER_TABLES))
        tamper_statements = (
            "UPDATE reconforge.landed_cost_plans SET freight_minor=freight_minor+1 WHERE tenant_id=%s",
            "UPDATE reconforge.landed_cost_allocations SET freight_minor=freight_minor+1 WHERE tenant_id=%s",
            "DELETE FROM reconforge.landed_cost_commands WHERE tenant_id=%s",
        )
    elif args.scenario == "fixed-assets":
        from tests.fixed_assets_browser_seed import (
            FIXED_ASSET_TABLES,
            seed_fixed_assets_browser,
            verify_fixed_assets_browser,
        )
        seed, verify_cycles = seed_fixed_assets_browser, verify_fixed_assets_browser
        configuration = "apps/web/live/fixed-assets.playwright.config.ts"
        extension_tables = tuple(dict.fromkeys(EXPANSION_TABLES + FIXED_ASSET_TABLES))
        tamper_statements = (
            "UPDATE reconforge.fixed_assets SET payload=payload||jsonb_build_object('cost_minor',1) WHERE tenant_id=%s",
            "UPDATE reconforge.fixed_asset_links SET posted_actor_id='maker' WHERE tenant_id=%s",
            "DELETE FROM reconforge.fixed_asset_commands WHERE tenant_id=%s",
        )
    runtime_root = args.runtime_root.resolve()
    if runtime_root != ROOT.resolve():
        raise ValueError("Run the expansion harness from its exact integrated runtime checkout.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not (args.web_root / "index.html").is_file():
        raise ValueError("Build the integrated Studio before running browser acceptance.")
    name = "reconforge-erp-expansion-browser-" + uuid4().hex[:12]
    admin_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
    secret_values = [admin_password, app_password]
    container = ""
    server = None
    status_before = tracked_status(runtime_root)
    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(), "image": IMAGE,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=runtime_root, text=True).strip(),  # nosec B603 B607
        "source_sha256": source_digest(runtime_root), "runtime_root": str(runtime_root),
        "tooling_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "built_web_sha256": built_web_digest(args.web_root.resolve()), "status": "failed",
        "tracked_status_before": status_before,
        "tracked_clean_before": not status_before,
        "scenario": args.scenario, "configuration": configuration,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    module_origins = {}
    for module_name in (
        "reconforge.api.app", "reconforge.infrastructure.postgres_stock_sales",
        "reconforge.infrastructure.postgres_procurement_partial", "reconforge.infrastructure.postgres_financial_installments",
        "reconforge.infrastructure.postgres_financial_reporting", "tests.erp_expansion_browser_seed",
        "reconforge.infrastructure.postgres_commercial_collections", "reconforge.infrastructure.postgres_landed_cost",
        "reconforge.infrastructure.postgres_fixed_assets",
        "tests.erp_expansion_browser_restore",
    ):
        origin = Path(importlib.import_module(module_name).__file__).resolve()
        if not origin.is_relative_to(runtime_root):
            raise ValueError("Expansion module origin is outside the integrated runtime checkout.")
        module_origins[module_name] = {"path": str(origin), "sha256": hashlib.sha256(origin.read_bytes()).hexdigest()}
    report["module_origins"] = module_origins
    started = time.monotonic()
    def run(argv: list[str], *, environment: dict[str, str] | None = None, check: bool = True, directory: Path = ROOT) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(argv, cwd=directory, env=environment, capture_output=True, text=True, timeout=600)  # nosec B603
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
                         "--label", "reconforge.owner=erp-expansion-browser", "-e", "POSTGRES_PASSWORD",
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
        runtime = seed(admin_dsn, app_dsn)
        secret_values.append(runtime.password)
        # Chromium blocks several OS-assigned low ephemeral ports. Bind an
        # available dynamic/private port without relaxing browser port policy.
        for _ in range(64):
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", 49152 + secrets.randbelow(16383)))
                except OSError:
                    continue
                https_port = listener.getsockname()[1]
                break
        else:
            raise RuntimeError("No owned dynamic HTTPS port is available.")
        url = f"https://localhost:{https_port}"
        environment.update(RECONFORGE_ERP_LIVE_URL=url, RECONFORGE_ERP_TENANT=runtime.tenant,
            RECONFORGE_ERP_PASSWORD=runtime.password, RECONFORGE_ERP_BROWSER_REPORT=str(output / "playwright.json"),
            RECONFORGE_ERP_BROWSER_ARTIFACTS=str(output / "playwright-artifacts"),
            RECONFORGE_GFO_APP_DSN=app_dsn, RECONFORGE_GFO_WEB_ROOT=str(args.web_root.resolve()),
            RECONFORGE_GFO_HTTPS_PORT=str(https_port))
        if args.scenario == "snapshots":
            from tests.enterprise_financial_snapshot_browser import financial_snapshot_oracle
            oracle_path = output / "financial-snapshot-oracle.json"
            oracle_path.write_text(json.dumps(financial_snapshot_oracle(), indent=2) + "\n", encoding="utf-8")
            environment["RECONFORGE_FINANCIAL_SNAPSHOT_ORACLE"] = str(oracle_path)

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
            browser = run([executable, "--prefix", "apps/web", "playwright", "test", "--config", configuration], environment=environment, check=False)
            (output / "browser.log").write_text(browser.stdout + browser.stderr, encoding="utf-8")
            report["browser_exit_code"] = browser.returncode
        server.terminate()
        server.wait(timeout=15)
        report["owned_https_process_stopped"] = True
        if (output / "playwright.json").is_file():
            report["browser_counts"] = json.loads((output / "playwright.json").read_text(encoding="utf-8"))["stats"]
        if browser.returncode == 0:
            report["persisted_effects"] = verify_cycles(runtime)
            if args.verify_native_restore:
                report["native_restore"] = verify_expansion_native_restore(runtime, container,
                    verify_cycles=verify_cycles, extension_tables=extension_tables, tamper_statements=tamper_statements)
        report["built_web_unchanged"] = built_web_digest(args.web_root.resolve()) == report["built_web_sha256"]
        report["source_unchanged"] = source_digest(runtime_root) == report["source_sha256"]
        report["source_commit_after"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=runtime_root, text=True).strip()
        status_after = tracked_status(runtime_root)
        report["tracked_status_after"] = status_after
        report["tracked_clean_after"] = not status_after
        report["source_unchanged"] = report["source_unchanged"] and report["source_commit_after"] == report["source_commit"]
        report["status"] = "passed" if browser.returncode == 0 and report["source_unchanged"] and report["built_web_unchanged"] and report["tracked_clean_before"] and report["tracked_clean_after"] else "failed"
        if status_before or status_after:
            report["error"] = "Tracked checkout is dirty; inspect tracked_status_before and tracked_status_after."
    except Exception as exc:
        diagnostic = str(exc)
        for value in secret_values:
            diagnostic = diagnostic.replace(value, "[redacted]")
        report["error"] = diagnostic
    finally:
        if server is not None and server.poll() is None:
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
        print(json.dumps({key: report[key] for key in ("status", "source_commit", "wall_seconds", "browser_counts", "error", "source_unchanged", "owned_container_removed") if key in report}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
