"""Encrypted PostgreSQL native-tool backup and isolated restore adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import struct
import subprocess  # nosec B404
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reconforge.application.backup_restore import BackupArtifact, RestoreOutcome
from reconforge.db.exporter import resolve_input_file, resolve_local_path
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, parse_json_document

# Native tools use prevalidated absolute paths and a closed argv without a shell.

POSTGRES_BACKUP_FORMAT = "reconforge-postgres-backup-v1"
_MAGIC = b"RFPGBAK1\n"
_TAG_BYTES = 16
_MAX_HEADER_BYTES = 4096
_MAX_BACKUP_BYTES = 8 * 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_HEADER_POLICY = StructuredDocumentPolicy(
    max_file_bytes=_MAX_HEADER_BYTES,
    max_nodes=16,
    max_depth=2,
    max_collection_items=8,
    max_scalar_characters=256,
    max_yaml_aliases=1,
)


class PostgresBackupError(RuntimeError):
    """Safe operational PostgreSQL backup or restore error."""


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> int: ...


class NativeCommandRunner:
    """Execute a closed argv without a shell or captured unbounded output."""

    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> int:
        try:
            with tempfile.TemporaryFile() as output:
                # The argv executable is a prevalidated absolute ordinary file.
                completed = subprocess.run(  # nosec B603
                    tuple(argv),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    shell=False,
                    check=False,
                    timeout=timeout_seconds,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PostgresBackupError("PostgreSQL native backup tool execution failed.") from exc
        return int(completed.returncode)


def _ordinary_absolute_tool(path: Path | str, name: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise PostgresBackupError(f"{name} path must be absolute.")
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise PostgresBackupError(f"{name} executable is unavailable.") from exc
    if not stat.S_ISREG(metadata.st_mode) or candidate.is_symlink():
        raise PostgresBackupError(f"{name} executable path is unsafe.")
    return str(candidate.resolve(strict=True))


def _service(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not _SERVICE.fullmatch(normalized):
        raise PostgresBackupError(f"{field} is invalid.")
    return normalized


def _database(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _NAME.fullmatch(normalized):
        raise PostgresBackupError("Restore database name is invalid.")
    return normalized


@dataclass(frozen=True)
class PostgresNativeTools:
    pg_dump: Path
    pg_restore: Path
    createdb: Path
    dropdb: Path
    psql: Path

    def validated(self) -> tuple[str, str, str, str, str]:
        return (
            _ordinary_absolute_tool(self.pg_dump, "pg_dump"),
            _ordinary_absolute_tool(self.pg_restore, "pg_restore"),
            _ordinary_absolute_tool(self.createdb, "createdb"),
            _ordinary_absolute_tool(self.dropdb, "dropdb"),
            _ordinary_absolute_tool(self.psql, "psql"),
        )


@dataclass(frozen=True)
class PostgresBackupSettings:
    source_service: str
    maintenance_service: str
    restore_database: str
    tools: PostgresNativeTools
    timeout_seconds: int = 1800

    def __post_init__(self) -> None:
        _service(self.source_service, "Source PostgreSQL service")
        _service(self.maintenance_service, "Maintenance PostgreSQL service")
        _database(self.restore_database)
        if self.timeout_seconds < 1 or self.timeout_seconds > 86_400:
            raise PostgresBackupError("PostgreSQL backup timeout is outside the supported range.")


def _cipher_parts(key: bytes, nonce: bytes, *, tag: bytes | None = None) -> object:
    if not isinstance(key, bytes) or len(key) != 32:
        raise PostgresBackupError("PostgreSQL encrypted backup requires an exact 32-byte operator key.")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise PostgresBackupError("Install ReconForge with the backup extra for encrypted backups.") from exc
    mode = modes.GCM(nonce) if tag is None else modes.GCM(nonce, tag)
    return Cipher(algorithms.AES(key), mode)


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise PostgresBackupError("PostgreSQL encrypted backup requires an exact 32-byte operator key.")


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            size += len(chunk)
            if size > _MAX_BACKUP_BYTES:
                raise PostgresBackupError("PostgreSQL backup exceeds the supported size limit.")
            digest.update(chunk)
    return digest.hexdigest(), size


def _header(*, nonce: bytes, key: bytes, plaintext_sha256: str, plaintext_bytes: int) -> bytes:
    document = {
        "algorithm": "AES-256-GCM",
        "format": POSTGRES_BACKUP_FORMAT,
        "key_fingerprint": hashlib.sha256(key).hexdigest()[:16],
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "plaintext_bytes": plaintext_bytes,
        "plaintext_sha256": plaintext_sha256,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(encoded) > _MAX_HEADER_BYTES:
        raise PostgresBackupError("PostgreSQL backup header exceeds the supported size limit.")
    return encoded


def _encrypt_dump(source: Path, target: Path, key: bytes) -> BackupArtifact:
    _validate_key(key)
    plaintext_sha256, plaintext_bytes = _file_digest(source)
    nonce = os.urandom(12)
    header = _header(nonce=nonce, key=key, plaintext_sha256=plaintext_sha256, plaintext_bytes=plaintext_bytes)
    prefix = _MAGIC + struct.pack(">I", len(header)) + header
    staging = target.with_name(f".{target.name}.staging-{os.getpid()}")
    digest = hashlib.sha256()
    try:
        cipher = _cipher_parts(key, nonce)
        encryptor = cipher.encryptor()  # type: ignore[attr-defined]
        encryptor.authenticate_additional_data(prefix)
        with source.open("rb") as reader, staging.open("xb") as writer:
            writer.write(prefix)
            digest.update(prefix)
            for chunk in iter(lambda: reader.read(_CHUNK_BYTES), b""):
                encrypted = encryptor.update(chunk)
                writer.write(encrypted)
                digest.update(encrypted)
            final = encryptor.finalize()
            writer.write(final)
            digest.update(final)
            writer.write(encryptor.tag)
            digest.update(encryptor.tag)
            writer.flush()
            os.fsync(writer.fileno())
        staging.replace(target)
    except (OSError, ValueError, TypeError) as exc:
        if staging.exists():
            staging.unlink()
        raise PostgresBackupError("Unable to publish encrypted PostgreSQL backup.") from exc
    return BackupArtifact(
        path=target,
        sha256=digest.hexdigest(),
        bytes_written=target.stat().st_size,
        backend="postgresql",
        format_version=POSTGRES_BACKUP_FORMAT,
    )


def _read_prefix(source: Path, key: bytes) -> tuple[bytes, bytes, bytes, int, str]:
    _validate_key(key)
    try:
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_BACKUP_BYTES + _MAX_HEADER_BYTES + 64:
            raise PostgresBackupError("Encrypted PostgreSQL backup is invalid.")
        with source.open("rb") as handle:
            magic = handle.read(len(_MAGIC))
            encoded_length = handle.read(4)
            if magic != _MAGIC or len(encoded_length) != 4:
                raise PostgresBackupError("Encrypted PostgreSQL backup is invalid.")
            header_length = struct.unpack(">I", encoded_length)[0]
            if header_length < 2 or header_length > _MAX_HEADER_BYTES:
                raise PostgresBackupError("Encrypted PostgreSQL backup is invalid.")
            encoded = handle.read(header_length)
            if len(encoded) != header_length:
                raise PostgresBackupError("Encrypted PostgreSQL backup is invalid.")
    except PostgresBackupError:
        raise
    except OSError as exc:
        raise PostgresBackupError("Unable to read encrypted PostgreSQL backup.") from exc

    try:
        document = parse_json_document(encoded.decode("ascii"), policy=_HEADER_POLICY)
        if not isinstance(document, dict) or set(document) != {
            "algorithm",
            "format",
            "key_fingerprint",
            "nonce",
            "plaintext_bytes",
            "plaintext_sha256",
        }:
            raise ValueError
        if (
            not isinstance(document["nonce"], str)
            or not isinstance(document["plaintext_bytes"], int)
            or isinstance(document["plaintext_bytes"], bool)
            or not isinstance(document["plaintext_sha256"], str)
        ):
            raise ValueError
        nonce = base64.b64decode(document["nonce"], validate=True)
        plaintext_bytes = document["plaintext_bytes"]
        plaintext_sha256 = document["plaintext_sha256"]
    except (UnicodeDecodeError, StructuredDocumentError, ValueError, TypeError, KeyError) as exc:
        raise PostgresBackupError("Encrypted PostgreSQL backup header is invalid.") from exc
    if (
        document["format"] != POSTGRES_BACKUP_FORMAT
        or document["algorithm"] != "AES-256-GCM"
        or document["key_fingerprint"] != hashlib.sha256(key).hexdigest()[:16]
        or len(nonce) != 12
        or plaintext_bytes < 0
        or plaintext_bytes > _MAX_BACKUP_BYTES
        or not re.fullmatch(r"[0-9a-f]{64}", plaintext_sha256)
    ):
        raise PostgresBackupError("Encrypted PostgreSQL backup integrity verification failed.")
    return magic + encoded_length + encoded, nonce, encoded, plaintext_bytes, plaintext_sha256


def _decrypt_dump(source: Path, target: Path, key: bytes) -> tuple[str, str]:
    prefix, nonce, _header_bytes, expected_bytes, expected_sha256 = _read_prefix(source, key)
    metadata = source.stat()
    ciphertext_offset = len(prefix)
    ciphertext_bytes = metadata.st_size - ciphertext_offset - _TAG_BYTES
    if ciphertext_bytes < 0 or ciphertext_bytes != expected_bytes:
        raise PostgresBackupError("Encrypted PostgreSQL backup integrity verification failed.")
    try:
        from cryptography.exceptions import InvalidTag

        with source.open("rb") as reader:
            reader.seek(-_TAG_BYTES, os.SEEK_END)
            tag = reader.read(_TAG_BYTES)
            reader.seek(ciphertext_offset)
            cipher = _cipher_parts(key, nonce, tag=tag)
            decryptor = cipher.decryptor()  # type: ignore[attr-defined]
            decryptor.authenticate_additional_data(prefix)
            plaintext_digest = hashlib.sha256()
            artifact_digest = hashlib.sha256(prefix)
            remaining = ciphertext_bytes
            with target.open("xb") as writer:
                while remaining:
                    chunk = reader.read(min(_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise PostgresBackupError("Encrypted PostgreSQL backup changed during restore.")
                    remaining -= len(chunk)
                    artifact_digest.update(chunk)
                    plaintext = decryptor.update(chunk)
                    writer.write(plaintext)
                    plaintext_digest.update(plaintext)
                artifact_digest.update(tag)
                final = decryptor.finalize()
                writer.write(final)
                plaintext_digest.update(final)
                writer.flush()
                os.fsync(writer.fileno())
    except InvalidTag as exc:
        if target.exists():
            target.unlink()
        raise PostgresBackupError("Encrypted PostgreSQL backup authentication failed.") from exc
    except PostgresBackupError:
        if target.exists():
            target.unlink()
        raise
    except (OSError, ValueError, TypeError) as exc:
        if target.exists():
            target.unlink()
        raise PostgresBackupError("Unable to decrypt PostgreSQL backup safely.") from exc
    if target.stat().st_size != expected_bytes or plaintext_digest.hexdigest() != expected_sha256:
        target.unlink()
        raise PostgresBackupError("Encrypted PostgreSQL backup integrity verification failed.")
    return expected_sha256, artifact_digest.hexdigest()


class PostgresNativeBackupAdapter:
    """Create encrypted dumps and restore only into a newly created database."""

    def __init__(self, settings: PostgresBackupSettings, *, runner: CommandRunner | None = None) -> None:
        self._settings = settings
        self._runner = runner or NativeCommandRunner()
        self._pg_dump, self._pg_restore, self._createdb, self._dropdb, self._psql = settings.tools.validated()

    def _run(self, argv: Sequence[str], *, action: str) -> None:
        if self._runner.run(argv, timeout_seconds=self._settings.timeout_seconds) != 0:
            raise PostgresBackupError(f"PostgreSQL {action} failed; review protected service and tool configuration.")

    def create_backup(self, output_path: Path, *, key: bytes) -> BackupArtifact:
        target = resolve_local_path(output_path)
        if target.exists():
            raise PostgresBackupError("PostgreSQL backup target already exists.")
        target.parent.mkdir(parents=True, exist_ok=True)
        source_service = _service(self._settings.source_service, "Source PostgreSQL service")
        with tempfile.TemporaryDirectory(prefix="reconforge-postgres-backup-") as directory:
            dump_path = Path(directory) / "database.dump"
            self._run(
                (
                    self._pg_dump,
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(dump_path),
                    "--dbname",
                    f"service={source_service}",
                ),
                action="backup",
            )
            if not dump_path.is_file() or dump_path.stat().st_size == 0:
                # A few client wrappers accept the equals form more reliably
                # than the POSIX-style two-argument form.  Retry once only
                # after a successful command produced no usable artifact;
                # pg_dump is read-only, and the retry remains inside the
                # disposable temporary directory.
                dump_path.unlink(missing_ok=True)
                self._run(
                    (
                        self._pg_dump,
                        "--format=custom",
                        "--no-owner",
                        "--no-privileges",
                        f"--file={dump_path}",
                        "--dbname",
                        f"service={source_service}",
                    ),
                    action="backup retry",
                )
            if not dump_path.is_file() or dump_path.stat().st_size == 0:
                raise PostgresBackupError("PostgreSQL backup tool produced no usable dump after retry.")
            return _encrypt_dump(dump_path, target, key)

    def restore_backup(self, input_path: Path, *, key: bytes) -> RestoreOutcome:
        source = resolve_input_file(input_path)
        maintenance = _service(self._settings.maintenance_service, "Maintenance PostgreSQL service")
        database = _database(self._settings.restore_database)
        with tempfile.TemporaryDirectory(prefix="reconforge-postgres-restore-") as directory:
            dump_path = Path(directory) / "database.dump"
            _plaintext_sha256, artifact_sha256 = _decrypt_dump(source, dump_path, key)
            self._run((self._pg_restore, "--list", str(dump_path)), action="restore validation")
            self._run(
                (self._createdb, f"--maintenance-db=service={maintenance}", database),
                action="restore database creation",
            )
            try:
                self._run(
                    (
                        self._pg_restore,
                        "--exit-on-error",
                        "--no-owner",
                        "--no-privileges",
                        "--dbname",
                        f"service={maintenance} dbname={database}",
                        str(dump_path),
                    ),
                    action="restore",
                )
                self._run(
                    (
                        self._psql,
                        "--no-psqlrc",
                        "--set",
                        "ON_ERROR_STOP=1",
                        "--dbname",
                        f"service={maintenance} dbname={database}",
                        "--command",
                        "SELECT 1 / ((to_regclass('reconforge.tenants') IS NOT NULL "
                        "AND to_regclass('public.alembic_version') IS NOT NULL)::int);",
                    ),
                    action="restore verification",
                )
            except PostgresBackupError:
                try:
                    rollback = self._runner.run(
                        (
                            self._dropdb,
                            "--if-exists",
                            f"--maintenance-db=service={maintenance}",
                            database,
                        ),
                        timeout_seconds=self._settings.timeout_seconds,
                    )
                except PostgresBackupError:
                    rollback = 1
                if rollback != 0:
                    raise PostgresBackupError(
                        "PostgreSQL restore and automatic rollback failed; isolate the target database."
                    ) from None
                raise
        return RestoreOutcome(
            backend="postgresql",
            target=database,
            artifact_sha256=artifact_sha256,
            rollback_performed=False,
        )

    def drop_restored_database(self) -> None:
        """Remove only the configured isolated restore target."""

        maintenance = _service(self._settings.maintenance_service, "Maintenance PostgreSQL service")
        database = _database(self._settings.restore_database)
        self._run(
            (self._dropdb, "--if-exists", f"--maintenance-db=service={maintenance}", database),
            action="restore database cleanup",
        )
