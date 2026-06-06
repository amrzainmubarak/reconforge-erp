"""Local password hashing helpers for ReconForge users."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

PBKDF2_ALGORITHM = "pbkdf2_sha256"
DEFAULT_PASSWORD_ITERATIONS = 390_000
SALT_BYTES = 32


@dataclass(frozen=True)
class PasswordHash:
    """Stored password hash metadata."""

    algorithm: str
    iterations: int
    salt_hex: str
    hash_hex: str


def hash_password(password: str, *, iterations: int = DEFAULT_PASSWORD_ITERATIONS) -> PasswordHash:
    """Hash a plaintext password using PBKDF2-HMAC-SHA256 and a random salt."""

    if not password:
        raise ValueError("Password must not be empty.")
    if iterations < 100_000:
        raise ValueError("Password iteration count is too low.")

    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return PasswordHash(
        algorithm=PBKDF2_ALGORITHM,
        iterations=iterations,
        salt_hex=salt.hex(),
        hash_hex=digest.hex(),
    )


def verify_password(password: str, stored: PasswordHash) -> bool:
    """Verify a plaintext password against stored PBKDF2 metadata."""

    if stored.algorithm != PBKDF2_ALGORITHM or stored.iterations < 100_000:
        return False
    try:
        salt = bytes.fromhex(stored.salt_hex)
        expected = bytes.fromhex(stored.hash_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, stored.iterations)
    return hmac.compare_digest(actual, expected)
