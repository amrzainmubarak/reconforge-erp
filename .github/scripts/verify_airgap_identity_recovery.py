"""Exercise local identity, encrypted backup, and isolated recovery without egress."""

from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from pathlib import Path

from reconforge.api.security import authenticate_token, create_session
from reconforge.audit import verify_audit_events
from reconforge.auth.service import LocalAuthService
from reconforge.db.connection import connect
from reconforge.db.encrypted_backup import create_encrypted_backup, restore_encrypted_backup
from reconforge.db.exporter import DBBridgeError
from reconforge.db.migrations import MIGRATIONS, run_migrations


def run_drill(workspace: Path) -> dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "identity-source.db"
    restored = workspace / "identity-restored.db"
    envelope = workspace / "identity-backup.enc.json"
    admin_password = secrets.token_urlsafe(48)
    reviewer_password = secrets.token_urlsafe(48)
    invalid_password = secrets.token_urlsafe(48)
    key = secrets.token_bytes(32)

    run_migrations(source)
    connection = connect(source, require_exists=True)
    try:
        service = LocalAuthService(connection)
        admin = service.init_admin(
            username="airgap-admin", password=admin_password, actor_label="airgap-bootstrap"
        )
        service.create_user(
            username="airgap-reviewer",
            password=reviewer_password,
            role="reviewer",
            actor_label=admin.username,
        )
        session = create_session(connection, user=admin)
        if authenticate_token(connection, token=session.token) is None:
            raise RuntimeError("airgap_local_session_creation_failed")
        if service.authenticate_user(username="airgap-admin", password=invalid_password) is not None:
            raise RuntimeError("airgap_invalid_password_accepted")
        if not verify_audit_events(connection).ok:
            raise RuntimeError("airgap_source_audit_chain_invalid")
        audit_text = "\n".join(
            str(tuple(row)) for row in connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        )
        if any(secret in audit_text for secret in (admin_password, reviewer_password, invalid_password, session.token)):
            raise RuntimeError("airgap_credential_material_in_audit")
    finally:
        connection.close()

    backup = create_encrypted_backup(source, envelope, key=key, actor_label="airgap-admin")
    wrong_key_rejected = False
    try:
        restore_encrypted_backup(restored, envelope, key=secrets.token_bytes(32))
    except DBBridgeError:
        wrong_key_rejected = True
    if not wrong_key_rejected or restored.exists():
        raise RuntimeError("airgap_wrong_key_restore_not_atomic")
    restore = restore_encrypted_backup(restored, envelope, key=key, actor_label="airgap-recovery")

    connection = connect(restored, require_exists=True)
    try:
        service = LocalAuthService(connection)
        restored_admin = service.authenticate_user(username="airgap-admin", password=admin_password)
        restored_reviewer = service.authenticate_user(username="airgap-reviewer", password=reviewer_password)
        if restored_admin is None or restored_reviewer is None:
            raise RuntimeError("airgap_local_identity_restore_failed")
        if not service.user_has_permission(username="airgap-admin", permission="users.manage"):
            raise RuntimeError("airgap_local_admin_permission_restore_failed")
        if authenticate_token(connection, token=session.token) is not None:
            raise RuntimeError("airgap_session_survived_restore")
        if not verify_audit_events(connection).ok:
            raise RuntimeError("airgap_restored_audit_chain_invalid")
        user_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        session_count = int(connection.execute("SELECT COUNT(*) FROM api_sessions").fetchone()[0])
    finally:
        connection.close()

    return {
        "audit_chain_valid": True,
        "backup_ciphertext_sha256": backup.ciphertext_sha256,
        "credential_material_in_audit": False,
        "local_users_restored": user_count,
        "old_sessions_restored": session_count,
        "operator_key_fingerprint": hashlib.sha256(key).hexdigest()[:16],
        "restored_schema_version": restore.schema_version,
        "runtime_schema_version": MIGRATIONS[-1].version,
        "wrong_key_rejected": wrong_key_rejected,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="reconforge-airgap-identity-") as directory:
        print(json.dumps(run_drill(Path(directory)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
