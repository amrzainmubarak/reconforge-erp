"""Local API session token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from reconforge.auth.models import LocalUser
from reconforge.auth.repositories import UserRepository
from reconforge.db.connection import DatabaseError
from reconforge.domain.models import utc_now_text

SESSION_TTL_HOURS = 8
SESSION_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)


class SessionError(ValueError):
    """Raised for safe local API session errors."""


@dataclass(frozen=True)
class CreatedSession:
    """Newly created API session with a raw token returned once."""

    id: str
    user_id: str
    token: str
    expires_at: str


def token_hash(token: str) -> str:
    """Hash a raw local API token for storage and lookup."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _expires_at() -> str:
    return (
        (datetime.now(UTC) + timedelta(hours=SESSION_TTL_HOURS))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_session_schema(connection: sqlite3.Connection) -> None:
    """Ensure the local API sessions table exists."""

    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'api_sessions'",
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise DatabaseError("Unable to read ReconForge database. Run 'reconforge db init' first.") from exc
    if table is None:
        raise DatabaseError("ReconForge API session schema is not initialized. Run 'reconforge db migrate' first.")


def create_session(connection: sqlite3.Connection, *, user: LocalUser) -> CreatedSession:
    """Create and persist a local API session, storing only the token hash."""

    ensure_session_schema(connection)
    raw_token = _new_token()
    digest = token_hash(raw_token)
    session_id = f"SES-{uuid.uuid4().hex}"
    now = utc_now_text()
    expires = _expires_at()
    try:
        connection.execute(
            """
            INSERT INTO api_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, NULL, NULL)
            """,
            (session_id, user.id, digest, now, expires),
        )
        connection.commit()
    except sqlite3.DatabaseError as exc:
        raise SessionError("Unable to create local API session.") from exc
    return CreatedSession(id=session_id, user_id=user.id, token=raw_token, expires_at=expires)


def authenticate_token(connection: sqlite3.Connection, *, token: str) -> LocalUser | None:
    """Return the active local user for a non-expired, non-revoked token."""

    ensure_session_schema(connection)
    if not token:
        return None
    digest = token_hash(token)
    try:
        rows = connection.execute(
            """
            SELECT api_sessions.*, users.username
            FROM api_sessions
            JOIN users ON users.id = api_sessions.user_id
            WHERE api_sessions.token_hash = ?
            """,
            (digest,),
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise SessionError("Unable to read local API session.") from exc

    now = datetime.now(UTC)
    for row in rows:
        stored_hash = str(row["token_hash"])
        if not hmac.compare_digest(stored_hash, digest):
            continue
        if row["revoked_at"] is not None:
            continue
        if _parse_utc(str(row["expires_at"])) <= now:
            continue
        username = str(row["username"])
        repository = UserRepository(connection)
        user = repository.get_by_username(username)
        if user is None or user.disabled:
            return None
        last_used_at = _parse_utc(str(row["last_used_at"])) if row["last_used_at"] is not None else None
        if last_used_at is None or last_used_at <= now - SESSION_LAST_USED_UPDATE_INTERVAL:
            now_text = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            threshold_text = (
                (now - SESSION_LAST_USED_UPDATE_INTERVAL).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
            try:
                cursor = connection.execute(
                    """
                    UPDATE api_sessions
                    SET last_used_at = ?
                    WHERE id = ? AND (last_used_at IS NULL OR last_used_at <= ?)
                    """,
                    (now_text, str(row["id"]), threshold_text),
                )
                if cursor.rowcount:
                    connection.commit()
            except sqlite3.DatabaseError as exc:
                raise SessionError("Unable to update local API session.") from exc
        return user
    return None


def revoke_token(connection: sqlite3.Connection, *, token: str) -> bool:
    """Revoke a local API session token."""

    ensure_session_schema(connection)
    digest = token_hash(token)
    try:
        row = connection.execute(
            "SELECT id, token_hash, revoked_at FROM api_sessions WHERE token_hash = ?",
            (digest,),
        ).fetchone()
        if row is None or row["revoked_at"] is not None:
            return False
        if not hmac.compare_digest(str(row["token_hash"]), digest):
            return False
        connection.execute("UPDATE api_sessions SET revoked_at = ? WHERE id = ?", (utc_now_text(), str(row["id"])))
        connection.commit()
    except sqlite3.DatabaseError as exc:
        raise SessionError("Unable to revoke local API session.") from exc
    return True
