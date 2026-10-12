"""Disposable synthetic SQLite HTTPS fixture for populated budget browser acceptance.

The API, identity, permissions, persisted ledger and audit are real. No API route
is replaced. The isolated harness imports the product component unchanged, so
agents can prove it before the lead registers its navigation in the application.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import uvicorn

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.platform.master_data import MasterDataService
from tests.https_runtime import create_localhost_certificate

PASSWORD = "Synthetic-Amr-Budget-Browser-2026!"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=24518)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reconforge-budget-ui-") as raw:
        directory = Path(raw)
        database = directory / "synthetic-budget.db"
        run_migrations(database)
        connection = connect(database)
        try:
            masters = MasterDataService(connection)
            organization = masters.upsert_organization(organization_code="SYN-UI", name="Synthetic budget UI")
            entity = masters.upsert_legal_entity(organization_code="SYN-UI", entity_code="EG", name="Synthetic entity", currency_code="EGP")
            period = masters.upsert_period(name="2026-10", start_date="2026-10-01", end_date="2026-10-31")
            auth = LocalAuthService(connection)
            for username in ("maker", "checker"):
                auth.create_user(username=username, password=PASSWORD, display_name=f"Synthetic {username}", role="controller")
            fixture = {"workspace_id": str(organization["workspace_id"]), "organization_id": str(organization["id"]), "legal_entity_id": str(entity["id"]), "period_id": str(period["id"])}
            (args.output / "fixture.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")
        finally:
            connection.close()
        certificate, key = create_localhost_certificate(directory)
        app = create_api_app(database, web_root=args.web_root, allowed_hosts=("localhost",), secure_transport=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, ssl_certfile=str(certificate), ssl_keyfile=str(key), log_level="warning")


if __name__ == "__main__":
    main()
