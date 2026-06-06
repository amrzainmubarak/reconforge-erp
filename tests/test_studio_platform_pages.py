from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.db import connect, run_migrations
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.metrics import MetricsService
from reconforge.studio.app import create_studio_app


def test_studio_db_pages_render_and_escape_values(tmp_path: Path) -> None:
    db_path = tmp_path / "studio_platform.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        AccountReconciliationService(connection).create_reconciliation(
            period_name="2026-05",
            entity_code="US01",
            account_code="1000",
            account_name="<script>alert(1)</script>",
        )
        MetricsService(connection).compute()
    finally:
        connection.close()

    client = TestClient(create_studio_app("examples/sample_data", tmp_path, db_path=db_path))

    accounts = client.get("/db/accounts")
    metrics = client.get("/db/metrics")

    assert accounts.status_code == 200
    assert metrics.status_code == 200
    assert "DB Account Reconciliations" in accounts.text
    assert "<script>alert(1)</script>" not in accounts.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in accounts.text
    assert "DB Metrics" in metrics.text
    assert "password_hash" not in accounts.text + metrics.text
    assert "token_hash" not in accounts.text + metrics.text
