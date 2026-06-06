from __future__ import annotations

from reconforge.auth.passwords import PBKDF2_ALGORITHM, hash_password, verify_password


def test_password_hash_never_stores_plaintext_and_verifies() -> None:
    password = "correct horse battery staple"

    stored = hash_password(password)

    assert stored.algorithm == PBKDF2_ALGORITHM
    assert stored.iterations >= 100_000
    assert stored.hash_hex != password
    assert stored.salt_hex != password
    assert password not in stored.hash_hex
    assert password not in stored.salt_hex
    assert verify_password(password, stored)


def test_password_hash_uses_random_salt() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first.salt_hex != second.salt_hex
    assert first.hash_hex != second.hash_hex


def test_wrong_password_fails() -> None:
    stored = hash_password("right-password")

    assert not verify_password("wrong-password", stored)
