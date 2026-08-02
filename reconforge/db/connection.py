"""SQLite connection helpers with conservative local path validation."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_ALLOWED_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
# Durable partition workers may briefly contend on BEGIN IMMEDIATE.  A
# bounded one-minute wait prevents transient lock storms from becoming lost
# work while still surfacing a genuinely wedged local database.
SQLITE_BUSY_TIMEOUT_MS = 60_000


class DatabaseError(ValueError):
    """Raised for safe, user-facing local database errors."""


class DatabasePathError(DatabaseError):
    """Raised when a database path is not acceptable for local DB commands."""


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def resolve_db_path(db_path: Path | str) -> Path:
    """Resolve a local SQLite database path after rejecting traversal tricks."""

    raw = str(db_path)
    if not raw.strip():
        raise DatabasePathError("Unsafe database path. Use a local .db/.sqlite path without traversal segments.")
    path = Path(db_path).expanduser()
    if _has_control_character(raw):
        raise DatabasePathError("Unsafe database path. Use a local .db/.sqlite path without traversal segments.")
    if not path.drive and ("\\" in raw or _WINDOWS_DRIVE_PREFIX.match(raw)):
        raise DatabasePathError("Unsafe database path. Use a local .db/.sqlite path without traversal segments.")
    if any(part == ".." for part in path.parts):
        raise DatabasePathError("Unsafe database path. Use a local .db/.sqlite path without traversal segments.")
    if path.name in {"", ".", ".."} or path.suffix.lower() not in _ALLOWED_DB_SUFFIXES:
        raise DatabasePathError("Database path must end in .db, .sqlite, or .sqlite3.")
    if path.exists() and path.is_dir():
        raise DatabasePathError("Database path points to a directory, not a SQLite file.")
    if path.exists() and path.is_symlink():
        raise DatabasePathError("Database path must not be a symlink.")
    if path.parent.exists() and not path.parent.is_dir():
        raise DatabasePathError("Database parent path is not a directory.")

    return path.resolve(strict=False)


def connect(
    db_path: Path | str,
    *,
    create_parent: bool = False,
    require_exists: bool = False,
) -> sqlite3.Connection:
    """Open a SQLite connection with row dictionaries and foreign keys enabled."""

    resolved = resolve_db_path(db_path)
    if require_exists and not resolved.exists():
        raise DatabaseError("ReconForge database not found. Run 'reconforge db init' first.")
    if create_parent:
        resolved.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(resolved, timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error as exc:
        raise DatabaseError("Unable to read ReconForge database. Choose a valid local SQLite .db file.") from exc
    return connection
