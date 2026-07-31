from __future__ import annotations

import pytest

from reconforge.auth.webauthn_config import WebAuthnConfigurationError, WebAuthnRuntime, load_webauthn_runtime


def test_webauthn_runtime_normalizes_exact_safe_origins() -> None:
    runtime = WebAuthnRuntime(
        rp_id="EXAMPLE.COM.",
        rp_name="ReconForge Test",
        allowed_origins=("https://example.com/", "https://ops.example.com:8443"),
    )

    assert runtime.rp_id == "example.com"
    assert runtime.allowed_origins == ("https://example.com", "https://ops.example.com:8443")


@pytest.mark.parametrize(
    ("rp_id", "origin"),
    [
        ("example.com/path", "https://example.com"),
        ("example.com", "http://example.com"),
        ("example.com", "https://evil.example.net"),
        ("example.com", "https://user:secret@example.com"),
        ("example.com", "https://example.com/path"),
        ("example.com", "https://example.com:99999"),
        ("localhost", "http://127.0.0.1:8765"),
    ],
)
def test_webauthn_runtime_rejects_unsafe_or_ambiguous_scope(rp_id: str, origin: str) -> None:
    with pytest.raises(WebAuthnConfigurationError):
        WebAuthnRuntime(rp_id=rp_id, rp_name="ReconForge", allowed_origins=(origin,))


def test_webauthn_runtime_allows_http_only_for_matching_loopback_rp() -> None:
    runtime = WebAuthnRuntime(
        rp_id="localhost",
        rp_name="ReconForge Local",
        allowed_origins=("http://localhost:8765",),
    )

    assert runtime.allowed_origins == ("http://localhost:8765",)


def test_webauthn_config_loader_is_closed_bounded_and_versioned(tmp_path) -> None:
    path = tmp_path / "webauthn.json"
    path.write_text(
        '{"schema_version":1,"rp_id":"example.test","rp_name":"ReconForge","allowed_origins":["https://example.test"]}',
        encoding="utf-8",
    )
    assert load_webauthn_runtime(path).rp_id == "example.test"

    path.write_text(
        '{"schema_version":1,"rp_id":"example.test","rp_name":"ReconForge","allowed_origins":["https://example.test"],"private_key":"forbidden"}',
        encoding="utf-8",
    )
    with pytest.raises(WebAuthnConfigurationError, match="closed"):
        load_webauthn_runtime(path)
