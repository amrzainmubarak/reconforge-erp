"""Opt-in HTTPS browser fixture with real identity, RLS, AR and persisted evidence."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import psycopg
import uvicorn

from reconforge.api import create_api_app
from tests.https_runtime import create_localhost_certificate
from tests.receivables_cash_runtime import synthetic_cash_runtime


def main() -> None:
    output = Path(os.environ["RECONFORGE_CASH_UI_OUTPUT"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    def source_hashes() -> dict[str, str]:
        paths = [*root.joinpath("reconforge").rglob("*.py"), *root.joinpath("alembic").rglob("*.py"), *root.joinpath("apps/web/src").rglob("*.ts"), *root.joinpath("apps/web/src").rglob("*.tsx"), *root.joinpath("apps/web/src").rglob("*.css"), *[path for path in root.joinpath("apps/web/dist").rglob("*") if path.is_file()], Path(__file__), root / "tests/receivables_cash_runtime.py", root / "apps/web/e2e/receivables-cash-live.spec.ts"]
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    hashes = source_hashes()
    target = os.environ.get("RECONFORGE_CASH_TEST_MIGRATION", "head")
    report: dict[str, object] = {"synthetic_only": True, "migration_target": target, "source_hashes_before": hashes}
    (output / "source-before.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    stop = output / "stop-owned-runtime"
    if stop.exists():
        raise RuntimeError("Use a fresh output directory; an old shutdown marker exists.")
    try:
        with synthetic_cash_runtime(target=target, password=os.environ["RECONFORGE_CASH_UI_PASSWORD"]) as runtime, tempfile.TemporaryDirectory(prefix="reconforge-cash-https-") as directory:
            certificate, key = create_localhost_certificate(Path(directory))
            report.update(database=runtime.database, invoice_id=runtime.invoice_id, customer_id=runtime.customer_id)
            (output / "fixture.json").write_text(json.dumps({key: value for key, value in report.items() if key != "source_hashes_before"}, indent=2), encoding="utf-8")
            app = create_api_app(output / "unused.db", tenant_db_root=output / "unused-tenants", postgres_dsn=runtime.app_dsn, postgres_require_tls=False, web_root=root / "apps/web/dist", allowed_hosts=("localhost",), secure_transport=True)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ.get("RECONFORGE_CASH_UI_PORT", "24448")), ssl_certfile=str(certificate), ssl_keyfile=str(key), log_level="warning", timeout_graceful_shutdown=5))
            def monitor() -> None:
                while not server.should_exit:
                    if stop.exists():
                        server.should_exit = True
                        return
                    time.sleep(0.25)
            threading.Thread(target=monitor, daemon=True).start()
            server.run()
            with psycopg.connect(runtime.admin_dsn, row_factory=psycopg.rows.dict_row) as connection:
                report["receipts"] = connection.execute("SELECT receipt_number,customer_id,organization_id,legal_entity_id,amount_minor,row_version FROM reconforge.ar_receipts WHERE tenant_id='cash-a' ORDER BY receipt_number").fetchall()
                report["allocations"] = connection.execute("SELECT receipt_id,invoice_id,amount_minor FROM reconforge.ar_receipt_allocations WHERE tenant_id='cash-a' ORDER BY receipt_id,invoice_id").fetchall()
                report["invoices"] = connection.execute("SELECT invoice_number,status,row_version,total_minor FROM reconforge.ar_invoices WHERE tenant_id='cash-a' ORDER BY invoice_number").fetchall()
                report["audit"] = connection.execute("SELECT action,count(*) AS count FROM reconforge.domain_audit_events WHERE tenant_id='cash-a' AND action LIKE 'ar_receipt_%' GROUP BY action ORDER BY action").fetchall()
                report["outbox"] = connection.execute("SELECT event_type,count(*) AS count FROM reconforge.outbox_events WHERE tenant_id='cash-a' AND event_type LIKE 'ar_receipt_%' GROUP BY event_type ORDER BY event_type").fetchall()
        report["database_removed"] = True
    finally:
        after = source_hashes()
        report["source_changed"] = sorted(key for key in hashes.keys() | after.keys() if hashes.get(key) != after.get(key))
        report["source_hashes_after"] = after
        (output / "persistence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
