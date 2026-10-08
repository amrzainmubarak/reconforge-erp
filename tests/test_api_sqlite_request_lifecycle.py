"""Request-owned SQLite connections survive synchronous worker handoffs."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from reconforge.api.dependencies import get_db
from reconforge.db import connect, run_migrations


def _request(database: Path) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                    "app": SimpleNamespace(state=SimpleNamespace(db_path=database, tenant_db_router=None))})


def test_request_dependency_can_enter_use_and_close_on_distinct_workers(tmp_path: Path) -> None:
    database = tmp_path / "request.db"
    run_migrations(database)
    dependency = get_db(_request(database))
    with ThreadPoolExecutor(max_workers=1) as enter, ThreadPoolExecutor(max_workers=1) as use:
        connection = enter.submit(next, dependency).result()
        assert use.submit(lambda: connection.execute("PRAGMA foreign_keys").fetchone()[0]).result() == 1
        # Closing on the other worker is required too: generator finalization
        # must not leave an open transaction or a database lock behind.
        use.submit(connection.execute, "CREATE TABLE lifecycle_probe (value INTEGER)").result()
        use.submit(connection.execute, "INSERT INTO lifecycle_probe VALUES (7)").result()
        use.submit(dependency.close).result()
    with connect(database) as independent:
        assert independent.execute("SELECT count(*) FROM lifecycle_probe").fetchone()[0] == 0


def test_concurrent_requests_keep_independent_transactions(tmp_path: Path) -> None:
    database = tmp_path / "independent.db"
    run_migrations(database)
    with connect(database) as setup:
        setup.execute("CREATE TABLE request_probe (value INTEGER)")
    first, second = get_db(_request(database)), get_db(_request(database))
    with ThreadPoolExecutor(max_workers=1) as worker_a, ThreadPoolExecutor(max_workers=1) as worker_b:
        a = worker_a.submit(next, first).result()
        b = worker_b.submit(next, second).result()
        assert a is not b
        worker_a.submit(a.execute, "INSERT INTO request_probe VALUES (1)").result()
        assert worker_b.submit(lambda: b.execute("SELECT count(*) FROM request_probe").fetchone()[0]).result() == 0
        worker_b.submit(first.close).result()
        worker_a.submit(second.close).result()
    with connect(database) as restored:
        assert restored.execute("SELECT count(*) FROM request_probe").fetchone()[0] == 0


def test_ordinary_database_connection_retains_thread_affinity(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "ordinary.db"
    run_migrations(database)
    connection = connect(database)
    try:
        with ThreadPoolExecutor(max_workers=1) as worker, pytest.raises(sqlite3.ProgrammingError):
            worker.submit(connection.execute, "SELECT 1").result()
    finally:
        connection.close()
