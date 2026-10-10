"""Owned pinned PostgreSQL gate; credentials remain in child memory only."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from defusedxml.ElementTree import fromstring
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"


def require_native_acceptance(document: str | None) -> dict[str, int]:
    """Require actual passing cases; exit zero with skipped cases is insufficient."""
    if document is None:
        raise ValueError("Mandatory native JUnit evidence is missing")
    root = fromstring(document)
    suites = list(root.iter("testsuite"))
    if not suites:
        raise ValueError("Mandatory native test suites are missing")
    counts = {name: sum(int(suite.attrib[name]) for suite in suites)
              for name in ("tests", "failures", "errors", "skipped")}
    cases = list(root.iter("testcase"))
    if counts["tests"] < 1 or counts["tests"] != len(cases):
        raise ValueError("Mandatory native case execution is incomplete")
    if any(counts[name] for name in ("failures", "errors", "skipped")) or any(
        case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")
    ):
        raise ValueError("Mandatory native cases must pass without skips")
    return counts


def run(args: list[str], *, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(args, cwd=ROOT, env=env, text=True, timeout=60).strip()  # nosec B603


def source_digest() -> str:
    names = run(["git", "ls-files", "-z"]).split("\0")
    digest = hashlib.sha256()
    for name in sorted(filter(None, names)):
        digest.update(name.encode())
        digest.update(hashlib.sha256((ROOT / name).read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    source_commit = run(["git", "rev-parse", "HEAD"])
    source_before = source_digest()
    status_before = run(["git", "status", "--porcelain", "--untracked-files=no"])
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
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", *groups,
            "--junitxml=" + str(output / "native-gate.xml")], cwd=ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            check=False, timeout=900)  # nosec B603
        diagnostic = result.stdout
        xml_path = output / "native-gate.xml"
        xml = xml_path.read_text(encoding="utf-8") if xml_path.exists() else None
        for secret in (admin_dsn, app_dsn, admin_password, app_password):
            diagnostic = diagnostic.replace(secret, "[redacted]")
            if xml is not None:
                xml = xml.replace(secret, "[redacted]")
        (output / "native-gate.log").write_text(diagnostic, encoding="utf-8")
        if xml is not None:
            xml_path.write_text(xml, encoding="utf-8")
        accepted = False
        counts = None
        acceptance_error = None
        try:
            counts = require_native_acceptance(xml)
            accepted = result.returncode == 0
        except Exception as exc:
            # Retain the type only: malformed external evidence can contain
            # credentials or source financial data in parser diagnostics.
            acceptance_error = type(exc).__name__
        status_after = run(["git", "status", "--porcelain", "--untracked-files=no"])
        source_after = source_digest()
        unchanged = source_before == source_after and source_commit == run(["git", "rev-parse", "HEAD"])
        cases_passed = accepted
        accepted = cases_passed and unchanged and not status_before and not status_after
        report = {"schema_version": "native-gate-v1", "source_commit": source_commit,
                  "source_sha256_before": source_before, "source_sha256_after": source_after,
                  "source_unchanged": unchanged, "tracked_status_before": status_before, "tracked_status_after": status_after,
                  "started_at": started_at, "duration_seconds": time.perf_counter() - started,
                  "python_version": sys.version, "postgres_image": IMAGE, "targets": groups,
                  "pytest_exit_code": result.returncode, "counts": counts, "native_cases_passed": cases_passed,
                  "accepted": accepted, "acceptance_error_type": acceptance_error}
        (output / "native-gate.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(diagnostic[-10000:])
        print(json.dumps({"accepted": accepted, "counts": counts, "evidence": str(output)}))
        return result.returncode if result.returncode else (0 if accepted else 2)
    finally:
        run(["docker", "rm", "--force", container])


if __name__ == "__main__":
    raise SystemExit(main())
