from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import reconforge.db.migrations as migration_module
from reconforge.api import create_api_app
from reconforge.audit import list_audit_events, verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import export_database
from reconforge.platform import PlatformError
from reconforge.platform.common import ensure_account, ensure_workspace
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.platform.master_data import MasterDataService

runner = CliRunner()


def _database(tmp_path: Path, name: str = "finance_core.db") -> Path:
    path = tmp_path / name
    run_migrations(path)
    return path


def _seed_references(connection: sqlite3.Connection) -> tuple[MasterDataService, dict[str, object]]:
    masters = MasterDataService(connection)
    masters.upsert_organization(organization_code="SYN", name="Synthetic Group")
    masters.upsert_legal_entity(
        organization_code="SYN",
        entity_code="EG01",
        name="Synthetic Egypt",
        currency_code="EGP",
    )
    period = masters.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")
    return masters, period


def _seed_finance_model(connection: sqlite3.Connection) -> tuple[FinanceCoreService, dict[str, object]]:
    _, period = _seed_references(connection)
    finance = FinanceCoreService(connection)
    finance.upsert_account(
        account_code="1000",
        name="Cash and cash equivalents",
        account_type="Asset",
        normal_balance="Debit",
        allow_posting=False,
    )
    finance.upsert_account(
        account_code="1010",
        name="Cash at bank",
        parent_account_code="1000",
        account_type="Asset",
        normal_balance="Debit",
    )
    finance.upsert_account(
        account_code="3000",
        name="Opening equity",
        account_type="Equity",
        normal_balance="Credit",
    )
    finance.upsert_dimension(
        dimension_code="CC",
        name="Cost Center",
        dimension_type="Cost Center",
        required_on_entries=True,
    )
    finance.upsert_dimension_value(dimension_code="CC", value_code="HQ", name="Head Office")
    finance.upsert_journal(
        journal_code="GJ",
        name="General Journal",
        organization_code="SYN",
        currency_code="EGP",
    )
    return finance, period


def _balanced_lines(amount: str = "1000.00") -> list[dict[str, object]]:
    return [
        {"account_code": "1010", "debit": amount, "dimensions": {"CC": "HQ"}},
        {"account_code": "3000", "credit": amount, "dimensions": {"CC": "HQ"}},
    ]


def _create_entry(
    finance: FinanceCoreService,
    period: dict[str, object],
    *,
    number: str = "JE/2026/0001",
    actor: str = "local-cli",
) -> dict[str, object]:
    return finance.create_entry(
        entry_number=number,
        organization_code="SYN",
        entity_code="EG01",
        period_id=str(period["id"]),
        journal_code="GJ",
        posting_date="2026-07-05",
        description="Synthetic balanced control entry",
        external_reference="SYN-REF-001",
        lines=_balanced_lines(),
        actor_label=actor,
    )


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_finance_core_balanced_lifecycle_trial_balance_and_immutability(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        finance, period = _seed_finance_model(connection)
        draft = _create_entry(finance, period)
        validated = finance.validate_entry(str(draft["id"]), reason="Independent synthetic review")
        trial = finance.trial_balance(
            period_id=str(period["id"]), organization_code="SYN", entity_code="EG01"
        )
        summary = finance.summary()
        snapshot = finance.snapshot()

        assert draft["balanced"] is True
        assert draft["total_debit_minor"] == draft["total_credit_minor"] == 100_000
        assert draft["lines"][0]["dimensions"] == {"CC": "HQ"}
        assert validated["status"] == "Validated"
        assert trial["totals"] == {
            "debit_minor": 100_000,
            "credit_minor": 100_000,
            "balanced": True,
            "debit": "1000.00",
            "credit": "1000.00",
        }
        assert {row["account_code"] for row in trial["accounts"]} == {"1010", "3000"}
        assert summary.to_dict() == {
            "workspace": "default",
            "charts": 1,
            "accounts": 3,
            "dimensions": 1,
            "dimension_values": 1,
            "journals": 1,
            "draft_entries": 0,
            "validated_entries": 1,
            "voided_entries": 0,
        }
        assert snapshot["schema_version"] == 1
        assert snapshot["source"] == {
            "kind": "local-finance-core",
            "local_first": True,
            "external_calls": False,
        }
        assert "source_path" not in json.dumps(snapshot)

        line_id = str(validated["lines"][0]["id"])
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("UPDATE ledger_lines SET debit_minor = 1 WHERE id = ?", (line_id,))
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="headers are immutable"):
            connection.execute(
                "UPDATE ledger_entries SET description = 'Changed' WHERE id = ?", (validated["id"],)
            )
        connection.rollback()
        voided = finance.void_entry(str(draft["id"]), reason="Synthetic reversal requested")
        assert voided["status"] == "Voided"
        assert voided["void_reason"] == "Synthetic reversal requested"
        with pytest.raises(sqlite3.DatabaseError, match="void metadata is immutable"):
            connection.execute(
                "UPDATE ledger_entries SET void_reason = 'Changed' WHERE id = ?", (validated["id"],)
            )
        connection.rollback()

        actions = {event.action for event in list_audit_events(connection)}
        assert {
            "financial_account_upserted",
            "accounting_dimension_upserted",
            "accounting_dimension_value_upserted",
            "finance_journal_upserted",
            "ledger_entry_draft_saved",
            "ledger_entry_validated",
            "ledger_entry_voided",
        } <= actions
        assert verify_audit_events(connection).ok is True
    finally:
        connection.close()


def test_finance_core_rejects_precision_imbalance_missing_dimensions_and_cycles(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        finance, period = _seed_finance_model(connection)
        with pytest.raises(PlatformError, match="balance"):
            finance.create_entry(
                entry_number="JE/BAD/BALANCE",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                journal_code="GJ",
                posting_date="2026-07-05",
                description="Unbalanced",
                lines=[
                    {"account_code": "1010", "debit": "10.00", "dimensions": {"CC": "HQ"}},
                    {"account_code": "3000", "credit": "9.00", "dimensions": {"CC": "HQ"}},
                ],
            )
        with pytest.raises(PlatformError, match="2-decimal precision"):
            finance.create_entry(
                entry_number="JE/BAD/PRECISION",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                journal_code="GJ",
                posting_date="2026-07-05",
                description="Precision",
                lines=_balanced_lines("1.001"),
            )
        with pytest.raises(PlatformError, match="missing required dimensions"):
            finance.create_entry(
                entry_number="JE/BAD/DIMENSION",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                journal_code="GJ",
                posting_date="2026-07-05",
                description="Missing dimensions",
                lines=[
                    {"account_code": "1010", "debit": "10.00"},
                    {"account_code": "3000", "credit": "10.00"},
                ],
            )
        with pytest.raises(PlatformError, match="acyclic"):
            finance.upsert_account(
                account_code="1000",
                name="Cash and cash equivalents",
                parent_account_code="1010",
                account_type="Asset",
                normal_balance="Debit",
                allow_posting=False,
            )
        with pytest.raises(PlatformError, match="exact decimal string"):
            finance.create_entry(
                entry_number="JE/BAD/FLOAT",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                journal_code="GJ",
                posting_date="2026-07-05",
                description="Float rejected",
                lines=[
                    {"account_code": "1010", "debit": 10.5, "dimensions": {"CC": "HQ"}},
                    {"account_code": "3000", "credit": 10.5, "dimensions": {"CC": "HQ"}},
                ],
            )
        with pytest.raises(PlatformError, match="valid non-negative decimal"):
            finance.create_entry(
                entry_number="JE/BAD/EXPONENT",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                journal_code="GJ",
                posting_date="2026-07-05",
                description="Exponent rejected",
                lines=_balanced_lines("1e1000000"),
            )

        draft = _create_entry(finance, period, number="JE/2026/REFERENCE")
        with pytest.raises(PlatformError, match="cannot change its chart or currency"):
            finance.upsert_journal(
                journal_code="GJ",
                name="General Journal",
                organization_code="SYN",
                currency_code="USD",
            )
        with pytest.raises(PlatformError, match="cannot change organization scope"):
            finance.upsert_chart(
                chart_code="DEFAULT",
                name="Default chart of accounts",
                organization_code="SYN",
            )

        connection.execute("UPDATE finance_journals SET active = 0 WHERE journal_code = 'GJ'")
        connection.commit()
        with pytest.raises(PlatformError, match="inactive or inconsistent"):
            finance.validate_entry(str(draft["id"]), reason="Reference must be rechecked")
        connection.execute("UPDATE finance_journals SET active = 1 WHERE journal_code = 'GJ'")
        connection.commit()

        direct = _create_entry(finance, period, number="JE/2026/DIRECT")
        with pytest.raises(sqlite3.DatabaseError, match="balanced non-zero lines"):
            connection.execute(
                "UPDATE ledger_entries SET status = 'Validated' WHERE id = ?", (direct["id"],)
            )
        connection.rollback()
    finally:
        connection.close()


def test_finance_core_entry_writes_hold_one_atomic_database_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    peer = sqlite3.connect(path, timeout=0.01)
    try:
        finance, period = _seed_finance_model(connection)
        draft = _create_entry(finance, period, number="JE/2026/ATOMIC")
        original_validate = finance._validate_entry_integrity
        lock_observed = False

        def verify_while_locked(entry: dict[str, object]) -> None:
            nonlocal lock_observed
            original_validate(entry)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                peer.execute("UPDATE finance_journals SET active = 0 WHERE journal_code = 'GJ'")
            peer.rollback()
            lock_observed = True

        monkeypatch.setattr(finance, "_validate_entry_integrity", verify_while_locked)
        assert finance.validate_entry(str(draft["id"]), reason="Atomic reference review")["status"] == "Validated"
        assert lock_observed is True

        def reject_recheck(entry: dict[str, object]) -> None:
            raise PlatformError("Synthetic integrity recheck failure.")

        monkeypatch.setattr(finance, "_validate_entry_integrity", reject_recheck)
        with pytest.raises(PlatformError, match="integrity recheck failure"):
            _create_entry(finance, period, number="JE/2026/ROLLBACK")
        assert connection.execute(
            "SELECT 1 FROM ledger_entries WHERE entry_number = 'JE/2026/ROLLBACK'"
        ).fetchone() is None
    finally:
        peer.close()
        connection.close()


def test_finance_core_seeded_rbac_and_sod(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        finance, period = _seed_finance_model(connection)
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="preparer", password="Secret-123", role="preparer")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        auth.create_user(username="auditor", password="Secret-123", role="auditor-readonly")

        entry = _create_entry(finance, period, number="JE/2026/SOD", actor="controller")
        with pytest.raises(PlatformError, match="Segregation of duties"):
            finance.validate_entry(str(entry["id"]), reason="Self review", actor_label="controller")
        validated = finance.validate_entry(
            str(entry["id"]), reason="Independent reviewer", actor_label="reviewer"
        )
        assert validated["validated_by"] == "reviewer"
        assert finance.list_entries(actor_label="auditor")[0]["status"] == "Validated"
        with pytest.raises(PlatformError, match="Permission denied"):
            finance.upsert_account(
                account_code="9999",
                name="Denied",
                account_type="Asset",
                normal_balance="Debit",
                actor_label="reviewer",
            )
    finally:
        connection.close()


def test_finance_core_api_is_strict_paginated_rbac_and_sod_protected(tmp_path: Path) -> None:
    path = _database(tmp_path, "finance_api.db")
    connection = connect(path, require_exists=True)
    try:
        _, period = _seed_references(connection)
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    client = TestClient(create_api_app(path))
    controller = {"Authorization": f"Bearer {_token(client, 'controller')}"}
    reviewer = {"Authorization": f"Bearer {_token(client, 'reviewer')}"}

    for payload in (
        {
            "account_code": "1010",
            "name": "Cash at bank",
            "account_type": "Asset",
            "normal_balance": "Debit",
        },
        {
            "account_code": "3000",
            "name": "Opening equity",
            "account_type": "Equity",
            "normal_balance": "Credit",
        },
    ):
        assert client.post("/api/v1/finance-core/accounts", headers=controller, json=payload).status_code == 200
    assert client.post(
        "/api/v1/finance-core/dimensions",
        headers=controller,
        json={"dimension_code": "CC", "name": "Cost Center", "required_on_entries": True},
    ).status_code == 200
    assert client.post(
        "/api/v1/finance-core/dimension-values",
        headers=controller,
        json={"dimension_code": "CC", "value_code": "HQ", "name": "Head Office"},
    ).status_code == 200
    assert client.post(
        "/api/v1/finance-core/journals",
        headers=controller,
        json={
            "journal_code": "GJ",
            "name": "General Journal",
            "organization_code": "SYN",
            "currency_code": "EGP",
        },
    ).status_code == 200
    created = client.post(
        "/api/v1/finance-core/entries",
        headers=controller,
        json={
            "entry_number": "JE/2026/API",
            "organization_code": "SYN",
            "entity_code": "EG01",
            "period_id": period["id"],
            "journal_code": "GJ",
            "posting_date": "2026-07-06",
            "description": "Synthetic API entry",
            "lines": _balanced_lines("25.50"),
        },
    )
    assert created.status_code == 200
    entry_id = str(created.json()["entry"]["id"])
    own_review = client.post(
        f"/api/v1/finance-core/entries/{entry_id}/validate",
        headers=controller,
        json={"reason": "Self review"},
    )
    validated = client.post(
        f"/api/v1/finance-core/entries/{entry_id}/validate",
        headers=reviewer,
        json={"reason": "Independent API review"},
    )
    listed = client.get("/api/v1/finance-core/entries?limit=1", headers=reviewer)
    trial = client.get(
        "/api/v1/finance-core/trial-balance",
        headers=reviewer,
        params={"period_id": period["id"], "organization": "SYN", "entity": "EG01"},
    )
    denied = client.post(
        "/api/v1/finance-core/accounts",
        headers=reviewer,
        json={"account_code": "9999", "name": "Denied"},
    )
    strict = client.post(
        "/api/v1/finance-core/accounts",
        headers=controller,
        json={"account_code": "9999", "name": "Strict", "unexpected": True},
    )
    bad_page = client.get("/api/v1/finance-core/accounts?limit=1001", headers=reviewer)
    unauthenticated = client.get("/api/v1/finance-core/summary")

    assert own_review.status_code == 400
    assert validated.status_code == 200
    assert validated.json()["entry"]["status"] == "Validated"
    assert listed.json()["pagination"] == {"limit": 1, "offset": 0, "returned": 1}
    assert trial.json()["totals"]["balanced"] is True
    assert denied.status_code == 403
    assert strict.status_code == 422
    assert bad_page.status_code == 422
    assert unauthenticated.status_code == 401
    combined = own_review.text + denied.text + strict.text + bad_page.text + unauthenticated.text
    assert "Traceback" not in combined
    assert "sqlite" not in combined.lower()


def test_finance_core_cli_workflow_and_safe_json_failure(tmp_path: Path) -> None:
    path = tmp_path / "finance_cli.db"
    lines_path = tmp_path / "ledger-lines.json"
    lines_path.write_text(json.dumps({"lines": _balanced_lines("75.25")}), encoding="utf-8")
    invalid_path = tmp_path / "invalid-lines.json"
    invalid_path.write_text(json.dumps({"lines": [{"account_code": "1010", "secret": "bad"}]}), encoding="utf-8")

    commands = [
        ["db", "init", "--db", str(path)],
        ["master-data", "organization-upsert", "--code", "SYN", "--name", "Synthetic Group", "--db", str(path)],
        [
            "master-data", "entity-upsert", "--organization", "SYN", "--code", "EG01",
            "--name", "Synthetic Egypt", "--currency", "EGP", "--db", str(path),
        ],
        [
            "master-data", "period-upsert", "--name", "2026-07", "--start", "2026-07-01",
            "--end", "2026-07-31", "--db", str(path),
        ],
        [
            "finance-core", "account-upsert", "--code", "1010", "--name", "Cash at bank",
            "--type", "Asset", "--normal-balance", "Debit", "--db", str(path),
        ],
        [
            "finance-core", "account-upsert", "--code", "3000", "--name", "Opening equity",
            "--type", "Equity", "--normal-balance", "Credit", "--db", str(path),
        ],
        [
            "finance-core", "dimension-upsert", "--code", "CC", "--name", "Cost Center",
            "--type", "Cost Center", "--required", "--db", str(path),
        ],
        [
            "finance-core", "dimension-value-upsert", "--dimension", "CC", "--code", "HQ",
            "--name", "Head Office", "--db", str(path),
        ],
        [
            "finance-core", "journal-upsert", "--code", "GJ", "--name", "General Journal",
            "--organization", "SYN", "--currency", "EGP", "--db", str(path),
        ],
    ]
    results = [runner.invoke(app, command) for command in commands]
    assert all(result.exit_code == 0 for result in results), [result.output for result in results]

    connection = connect(path, require_exists=True)
    try:
        period_id = str(connection.execute("SELECT id FROM periods WHERE name = '2026-07'").fetchone()["id"])
    finally:
        connection.close()
    created = runner.invoke(
        app,
        [
            "finance-core", "entry-create", "--number", "JE/2026/CLI", "--organization", "SYN",
            "--entity", "EG01", "--period-id", period_id, "--journal", "GJ", "--date", "2026-07-07",
            "--description", "Synthetic CLI entry", "--lines", str(lines_path), "--db", str(path),
        ],
    )
    connection = connect(path, require_exists=True)
    try:
        entry_id = str(connection.execute("SELECT id FROM ledger_entries WHERE entry_number = 'JE/2026/CLI'").fetchone()["id"])
    finally:
        connection.close()
    validated = runner.invoke(
        app,
        [
            "finance-core", "entry-validate", "--entry-id", entry_id,
            "--reason", "Synthetic CLI review", "--db", str(path),
        ],
    )
    trial = runner.invoke(
        app,
        [
            "finance-core", "trial-balance", "--period-id", period_id,
            "--organization", "SYN", "--entity", "EG01", "--db", str(path),
        ],
    )
    snapshot = runner.invoke(app, ["finance-core", "snapshot", "--db", str(path)])
    rejected = runner.invoke(
        app,
        [
            "finance-core", "entry-create", "--number", "JE/BAD", "--organization", "SYN",
            "--entity", "EG01", "--period-id", period_id, "--journal", "GJ", "--date", "2026-07-07",
            "--description", "Rejected", "--lines", str(invalid_path), "--db", str(path),
        ],
    )

    assert created.exit_code == validated.exit_code == trial.exit_code == snapshot.exit_code == 0
    assert "Validated" in validated.output
    assert json.loads(trial.output)["totals"]["balanced"] is True
    assert json.loads(snapshot.output)["summary"]["validated_entries"] == 1
    assert rejected.exit_code == 1
    assert "unsupported fields" in rejected.output
    assert "Traceback" not in rejected.output


def test_migration_eight_preserves_accounts_and_assigns_default_chart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "upgrade-v8.db"
    full_migrations = migration_module.MIGRATIONS
    monkeypatch.setattr(migration_module, "MIGRATIONS", full_migrations[:7])
    first = migration_module.run_migrations(path)
    assert first.current_version == 7
    connection = connect(path, require_exists=True)
    try:
        workspace_id = ensure_workspace(connection, "legacy-finance")
        connection.execute(
            "INSERT INTO accounts (id, workspace_id, account_code, account_name, created_at) VALUES (?, ?, ?, ?, ?)",
            ("ACC-old", workspace_id, "1000", "Legacy Cash", "2026-01-01T00:00:00Z"),
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(migration_module, "MIGRATIONS", full_migrations)
    upgraded = migration_module.run_migrations(path)
    assert upgraded.applied_versions == list(range(8, migration_module.MIGRATIONS[-1].version + 1))
    connection = connect(path, require_exists=True)
    try:
        account = connection.execute("SELECT * FROM accounts WHERE id = 'ACC-old'").fetchone()
        chart = connection.execute("SELECT * FROM charts_of_accounts WHERE workspace_id = ?", (workspace_id,)).fetchone()
        permissions = connection.execute(
            "SELECT COUNT(*) AS count FROM permissions WHERE name LIKE 'finance_core.%'"
        ).fetchone()
        assert account is not None and chart is not None
        assert account["account_name"] == "Legacy Cash"
        assert account["chart_id"] == chart["id"]
        assert permissions["count"] == 3
        new_account_id = ensure_account(
            connection, workspace_id=workspace_id, account_code="2000", account_name="Legacy Payable"
        )
        assert connection.execute("SELECT chart_id FROM accounts WHERE id = ?", (new_account_id,)).fetchone()[
            "chart_id"
        ] == chart["id"]
    finally:
        connection.close()


def test_finance_core_backup_restore_and_public_export_preserve_validated_entry(tmp_path: Path) -> None:
    path = _database(tmp_path, "finance_backup.db")
    connection = connect(path, require_exists=True)
    try:
        finance, period = _seed_finance_model(connection)
        draft = _create_entry(finance, period, number="JE/2026/BACKUP")
        finance.validate_entry(str(draft["id"]), reason="Synthetic backup review")
        entry_id = str(draft["id"])
    finally:
        connection.close()

    backup = create_backup(path, tmp_path / "backup")
    restored_path = tmp_path / "restored.db"
    restore_backup(restored_path, backup.backup_path)
    connection = connect(restored_path, require_exists=True)
    try:
        restored = FinanceCoreService(connection).get_entry(entry_id)
        assert restored["status"] == "Validated"
        assert restored["balanced"] is True
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("DELETE FROM ledger_lines WHERE entry_id = ?", (entry_id,))
        connection.rollback()
    finally:
        connection.close()

    exported = export_database(restored_path, tmp_path / "export")
    finance_payload = json.loads((exported.output_dir / "finance_workflows.json").read_text(encoding="utf-8"))
    domain_payload = json.loads((exported.output_dir / "domain.json").read_text(encoding="utf-8"))
    assert finance_payload["ledger_entries"][0]["entry_number"] == "JE/2026/BACKUP"
    assert len(finance_payload["ledger_lines"]) == 2
    assert domain_payload["charts_of_accounts"][0]["chart_code"] == "DEFAULT"
