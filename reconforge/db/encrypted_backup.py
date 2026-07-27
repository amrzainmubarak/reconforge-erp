"""AES-256-GCM envelope for local backup artifacts using operator-owned keys."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reconforge.db.backup import DBBackupResult, DBRestoreResult, create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, resolve_input_file, resolve_local_path
from reconforge.io.structured import (
    StructuredDocumentError,
    StructuredDocumentPolicy,
    parse_json_document,
)

ENCRYPTED_BACKUP_FORMAT = "reconforge-encrypted-backup-v1"
ENCRYPTED_BACKUP_ALGORITHM = "AES-256-GCM"
_ASSOCIATED_DATA = b"ReconForge encrypted local backup v1"
_MAX_ENVELOPE_BYTES = 128 * 1024 * 1024
_MAX_KEY_FILE_BYTES = 66
_ENVELOPE_POLICY = StructuredDocumentPolicy(
    max_file_bytes=_MAX_ENVELOPE_BYTES,
    max_nodes=16,
    max_depth=2,
    max_collection_items=8,
    max_scalar_characters=124 * 1024 * 1024,
    max_yaml_aliases=1,
)
_PAYLOAD_POLICY = StructuredDocumentPolicy(
    max_file_bytes=96 * 1024 * 1024,
    max_nodes=8,
    max_depth=2,
    max_collection_items=4,
    max_scalar_characters=90 * 1024 * 1024,
    max_yaml_aliases=1,
)


@dataclass(frozen=True)
class EncryptedBackupResult:
    path: Path
    ciphertext_sha256: str
    source_schema_version: int


class _AuthenticatedCipher(Protocol):
    def encrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes: ...

    def decrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes: ...


def read_operator_backup_key(path: Path | str) -> bytes:
    """Read an exact raw or hexadecimal AES-256 key from a protected local file."""

    source = resolve_input_file(path)
    try:
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_KEY_FILE_BYTES:
            raise DBBridgeError("Backup key file is invalid.")
        with source.open("rb") as handle:
            value = handle.read(_MAX_KEY_FILE_BYTES + 1)
            if len(value) != metadata.st_size or os.fstat(handle.fileno()).st_size != metadata.st_size:
                raise DBBridgeError("Backup key file changed during validation.")
    except DBBridgeError:
        raise
    except OSError as exc:
        raise DBBridgeError("Unable to read backup key file.") from exc
    if len(value) == 32:
        return value
    encoded = value.rstrip(b"\r\n")
    if len(encoded) != 64 or any(character not in b"0123456789abcdefABCDEF" for character in encoded):
        raise DBBridgeError("Backup key file must contain exactly 32 raw bytes or 64 hexadecimal characters.")
    try:
        return bytes.fromhex(encoded.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DBBridgeError("Backup key file is invalid.") from exc


def _aesgcm(key: bytes) -> _AuthenticatedCipher:
    if not isinstance(key, bytes) or len(key) != 32:
        raise DBBridgeError("Encrypted backup requires an exact 32-byte operator key.")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise DBBridgeError("Install ReconForge with the backup extra for encrypted backups.") from exc
    return AESGCM(key)


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: object) -> bytes:
    if not isinstance(value, str):
        raise DBBridgeError("Encrypted backup envelope is invalid.")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise DBBridgeError("Encrypted backup envelope is invalid.") from exc


def _payload(backup: DBBackupResult) -> bytes:
    document = {
        "backup_json": _b64encode(backup.backup_path.read_bytes()),
        "manifest_json": _b64encode(backup.manifest_path.read_bytes()),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def create_encrypted_backup(
    db_path: Path | str,
    output_path: Path | str,
    *,
    key: bytes,
    actor_label: str = "local-cli",
) -> EncryptedBackupResult:
    """Create one encrypted backup file without publishing plaintext artifacts."""

    target = resolve_local_path(output_path)
    if target.exists():
        raise DBBridgeError("Encrypted backup target already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reconforge-encrypted-backup-") as directory:
        backup = create_backup(db_path, Path(directory) / "plain", actor_label=actor_label)
        nonce = os.urandom(12)
        cipher = _aesgcm(key)
        ciphertext = cipher.encrypt(nonce, _payload(backup), _ASSOCIATED_DATA)
        digest = hashlib.sha256(ciphertext).hexdigest()
        envelope = {
            "algorithm": ENCRYPTED_BACKUP_ALGORITHM,
            "ciphertext": _b64encode(ciphertext),
            "ciphertext_sha256": digest,
            "format": ENCRYPTED_BACKUP_FORMAT,
            "key_fingerprint": hashlib.sha256(key).hexdigest()[:16],
            "nonce": _b64encode(nonce),
        }
        encoded = (json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
            "ascii"
        )
        if len(encoded) > _MAX_ENVELOPE_BYTES:
            raise DBBridgeError("Encrypted backup exceeds the supported size limit.")
        staging = target.with_name(f".{target.name}.staging-{os.getpid()}")
        try:
            with staging.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            staging.replace(target)
        except OSError as exc:
            if staging.exists():
                staging.unlink()
            raise DBBridgeError("Unable to publish encrypted backup.") from exc
        return EncryptedBackupResult(target, digest, backup.schema_version)


def _decrypt_envelope(path: Path, key: bytes) -> dict[str, bytes]:
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError as exc:
        raise DBBridgeError("Install ReconForge with the backup extra for encrypted backups.") from exc
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_ENVELOPE_BYTES:
            raise DBBridgeError("Encrypted backup envelope is invalid.")
        with path.open("rb") as handle:
            encoded = handle.read(_MAX_ENVELOPE_BYTES + 1)
            if len(encoded) != metadata.st_size or os.fstat(handle.fileno()).st_size != metadata.st_size:
                raise DBBridgeError("Encrypted backup envelope changed during validation.")
        document = parse_json_document(encoded.decode("utf-8", errors="strict"), policy=_ENVELOPE_POLICY)
    except DBBridgeError:
        raise
    except (OSError, StructuredDocumentError, UnicodeDecodeError) as exc:
        raise DBBridgeError("Encrypted backup envelope is invalid.") from exc
    if not isinstance(document, dict) or set(document) != {
        "algorithm",
        "ciphertext",
        "ciphertext_sha256",
        "format",
        "key_fingerprint",
        "nonce",
    }:
        raise DBBridgeError("Encrypted backup envelope is invalid.")
    if document["format"] != ENCRYPTED_BACKUP_FORMAT or document["algorithm"] != ENCRYPTED_BACKUP_ALGORITHM:
        raise DBBridgeError("Encrypted backup envelope is unsupported.")
    ciphertext = _b64decode(document["ciphertext"])
    nonce = _b64decode(document["nonce"])
    digest = hashlib.sha256(ciphertext).hexdigest()
    if document["ciphertext_sha256"] != digest or document["key_fingerprint"] != hashlib.sha256(key).hexdigest()[:16]:
        raise DBBridgeError("Encrypted backup integrity verification failed.")
    try:
        plaintext = _aesgcm(key).decrypt(nonce, ciphertext, _ASSOCIATED_DATA)
    except (InvalidTag, ValueError, TypeError) as exc:
        raise DBBridgeError("Encrypted backup authentication failed.") from exc
    try:
        payload = parse_json_document(plaintext.decode("utf-8", errors="strict"), policy=_PAYLOAD_POLICY)
    except (StructuredDocumentError, UnicodeDecodeError) as exc:
        raise DBBridgeError("Encrypted backup payload is invalid.") from exc
    if not isinstance(payload, dict) or set(payload) != {"backup_json", "manifest_json"}:
        raise DBBridgeError("Encrypted backup payload is invalid.")
    return {name: _b64decode(value) for name, value in payload.items()}


def restore_encrypted_backup(
    db_path: Path | str,
    input_path: Path | str,
    *,
    key: bytes,
    force: bool = False,
    dry_run: bool = False,
    actor_label: str = "local-cli",
) -> DBRestoreResult:
    """Authenticate/decrypt an envelope and reuse the versioned restore verifier."""

    source = resolve_input_file(input_path)
    payload = _decrypt_envelope(source, key)
    with tempfile.TemporaryDirectory(prefix="reconforge-decrypted-restore-") as directory:
        root = Path(directory)
        (root / "backup.json").write_bytes(payload["backup_json"])
        (root / "manifest.json").write_bytes(payload["manifest_json"])
        result = restore_backup(db_path, root, force=force, dry_run=dry_run, actor_label=actor_label)
        return DBRestoreResult(
            db_path=result.db_path,
            backup_path=source,
            schema_version=result.schema_version,
            restored_tables=result.restored_tables,
            dry_run=result.dry_run,
        )
