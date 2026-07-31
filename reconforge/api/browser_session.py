"""Same-origin browser-session helpers without browser-readable bearer tokens."""

from __future__ import annotations

import hashlib
import hmac
from secrets import token_urlsafe

BROWSER_SESSION_COOKIE = "__Host-reconforge_session"
BROWSER_CSRF_HEADER = "x-reconforge-csrf"
_CSRF_NONCE_MAX_LENGTH = 128
_CSRF_SIGNATURE_LENGTH = 64


def issue_browser_csrf_token(session_token: str) -> str:
    """Return a browser-readable CSRF proof bound to one session token."""

    nonce = token_urlsafe(32)
    signature = hmac.new(
        session_token.encode("utf-8"), nonce.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{nonce}.{signature}"


def browser_csrf_token_is_valid(*, session_token: str, candidate: str | None) -> bool:
    """Verify a bounded double-submit proof without retaining it server-side."""

    if not isinstance(candidate, str) or len(candidate) > _CSRF_NONCE_MAX_LENGTH + 1 + _CSRF_SIGNATURE_LENGTH:
        return False
    nonce, separator, signature = candidate.partition(".")
    if (
        not separator
        or not nonce
        or not nonce.isascii()
        or len(nonce) > _CSRF_NONCE_MAX_LENGTH
        or len(signature) != _CSRF_SIGNATURE_LENGTH
    ):
        return False
    expected = hmac.new(
        session_token.encode("utf-8"), nonce.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
