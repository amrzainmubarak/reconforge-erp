from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

import pandas as pd
import pytest

from reconforge.config import ReconForgeConfig
from reconforge.io.readers import read_required_datasets
from reconforge.schemas import DatasetName


@pytest.fixture()
def isolated_postgres_runtime_role(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Keep a live test's least-privilege assertions independent of prior grants."""
    import psycopg
    from psycopg import sql

    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", app_dsn)
    role = "reconforge_test_" + uuid4().hex
    password = token_urlsafe(32)
    with psycopg.connect(admin_dsn, autocommit=True) as control:
        control.execute(sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Identifier(role), sql.Literal(password)))
        try:
            monkeypatch.setenv("RECONFORGE_TEST_POSTGRES_APP_USER", role)
            monkeypatch.setenv("RECONFORGE_TEST_POSTGRES_DSN", psycopg.conninfo.make_conninfo(
                app_dsn, user=role, password=password,
            ))
            yield role
        finally:
            # The random, test-owned role receives grants only in this database.
            control.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            control.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.fixture()
def sample_dir() -> Path:
    return Path("examples/sample_data")


@pytest.fixture()
def config() -> ReconForgeConfig:
    return ReconForgeConfig()


@pytest.fixture()
def sample_datasets(sample_dir: Path) -> dict[DatasetName, pd.DataFrame]:
    return read_required_datasets(
        sample_dir,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.PRODUCTS,
            DatasetName.CUSTOMERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
