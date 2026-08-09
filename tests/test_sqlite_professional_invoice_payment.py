from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from reconforge.application.professional_invoice_payment_control import (
    run_professional_invoice_payment_control_files,
)
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.domain.professional_invoice_payment_control import ProfessionalInvoicePaymentRun
from reconforge.infrastructure.sqlite_professional_invoice_payment import (
    ProfessionalInvoicePaymentPersistenceError,
    SQLiteProfessionalInvoicePaymentRepository,
)

INVOICES = Path("examples/professional_invoice_payment/invoices.json")
PAYMENTS = Path("examples/professional_invoice_payment/payments.json")


def _run() -> ProfessionalInvoicePaymentRun:
    return run_professional_invoice_payment_control_files(INVOICES, PAYMENTS, currency="USD", tolerance="0.01")


def _database(tmp_path: Path, *, target_version: int | None = None) -> sqlite3.Connection:
    path = tmp_path / "professional.db"
    run_migrations(path, target_version=target_version)
    return connect(path, require_exists=True)


def test_professional_persistence_is_idempotent_workspace_scoped_and_replay_verified(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    try:
        repository = SQLiteProfessionalInvoicePaymentRepository(connection)
        run = _run()
        first = repository.put(run, workspace="firm-a", actor_label="local-cli")
        replay = repository.put(run, workspace="firm-a", actor_label="local-cli")
        assert replay == first
        assert repository.get(decision_digest=run.decision_digest, workspace="firm-a") == first
        assert repository.list(workspace="firm-a") == (first,)
        assert repository.list(workspace="firm-b") == ()
        assert first["report"]["decision_digest"] == run.decision_digest
    finally:
        connection.close()


def test_professional_persistence_rejects_tampered_payload_after_outer_rehash(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    try:
        repository = SQLiteProfessionalInvoicePaymentRepository(connection)
        run = _run()
        saved = repository.put(run, workspace="firm-a")
        connection.execute("DROP TRIGGER professional_invoice_payment_runs_no_update")
        payload = json.loads(
            str(connection.execute("SELECT payload_json FROM professional_invoice_payment_runs WHERE id=?", (saved["id"],)).fetchone()[0])
        )
        payload["decisions"][0]["reason_code"] = "TAMPERED"
        payload["artifact_digest"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in payload.items() if key != "artifact_digest"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        connection.execute(
            "UPDATE professional_invoice_payment_runs SET payload_json=?, artifact_digest=? WHERE id=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), payload["artifact_digest"], saved["id"]),
        )
        connection.commit()
        with pytest.raises(ProfessionalInvoicePaymentPersistenceError, match="replay verification"):
            repository.get(decision_digest=run.decision_digest, workspace="firm-a")
    finally:
        connection.close()


def test_professional_repository_requires_migration_36(tmp_path: Path) -> None:
    connection = _database(tmp_path, target_version=35)
    try:
        with pytest.raises(ProfessionalInvoicePaymentPersistenceError, match="migration is required"):
            SQLiteProfessionalInvoicePaymentRepository(connection)
    finally:
        connection.close()


def test_professional_persistence_survives_local_backup_restore(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    run_migrations(source)
    connection = connect(source, require_exists=True)
    try:
        saved = SQLiteProfessionalInvoicePaymentRepository(connection).put(_run(), workspace="firm-a")
    finally:
        connection.close()
    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    restored_connection = connect(restored, require_exists=True)
    try:
        replay = SQLiteProfessionalInvoicePaymentRepository(restored_connection).get(
            decision_digest=str(saved["decision_digest"]), workspace="firm-a"
        )
        assert replay == saved
    finally:
        restored_connection.close()


def test_professional_persistence_boundary_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/infrastructure/sqlite_professional_invoice_payment.py" in manifest
    assert "include tests/test_sqlite_professional_invoice_payment.py" in manifest
