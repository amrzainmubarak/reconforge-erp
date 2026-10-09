"""Owned pinned PostgreSQL gate; credentials remain in child memory only."""
from __future__ import annotations

import os
import secrets
import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"


def run(args: list[str], *, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(args, cwd=ROOT, env=env, text=True, timeout=60).strip()  # nosec B603


def main() -> int:
    output = ROOT / "output/global-operating-platform-20261009/commercial"
    output = output / ("native-" + str(time.time_ns()))
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    admin_password, app_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    environment["POSTGRES_PASSWORD"] = admin_password
    container = run(["docker", "run", "--detach", "--rm", "--name", "reconforge-commercial-" + uuid4().hex[:10],
        "--label", "reconforge.owner=commercial-collections-gate", "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", IMAGE], env=environment)
    try:
        port = run(["docker", "port", container, "5432/tcp"]).rsplit(":", 1)[1]
        admin_dsn = f"postgresql://postgres:{admin_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        app_dsn = f"postgresql://commercial_gate:{app_password}@127.0.0.1:{port}/postgres?connect_timeout=5"
        for attempt in range(150):
            try:
                with psycopg.connect(admin_dsn, autocommit=True) as connection:
                    connection.execute(sql.SQL("CREATE ROLE commercial_gate LOGIN PASSWORD {}").format(sql.Literal(app_password)))
                break
            except psycopg.OperationalError:
                if attempt == 149:
                    raise
                time.sleep(.2)
        environment.update(RECONFORGE_TEST_POSTGRES_ADMIN_DSN=admin_dsn, RECONFORGE_TEST_POSTGRES_DSN=app_dsn)
        groups = sys.argv[1:] or ["tests/test_postgres_commercial_collections.py", "tests/test_postgres_stock_commerce.py", "tests/test_postgres_stock_sales.py"]
        with (output / "native-gate.log").open("w", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", *groups,
                "--junitxml=" + str(output / "native-gate.xml")], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                check=False, timeout=900)  # nosec B603
        print((output / "native-gate.log").read_text(encoding="utf-8")[-10000:])
        return result.returncode
    finally:
        run(["docker", "rm", "--force", container])


if __name__ == "__main__":
    raise SystemExit(main())
