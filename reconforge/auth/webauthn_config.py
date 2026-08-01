"""Closed WebAuthn relying-party configuration for the server profile."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, read_json_document


class WebAuthnConfigurationError(ValueError):
    """Raised when the relying-party boundary is unsafe or ambiguous."""


_RP_ID = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_CONFIG_POLICY = StructuredDocumentPolicy(
    max_file_bytes=64 * 1024,
    max_nodes=64,
    max_depth=4,
    max_collection_items=16,
    max_scalar_characters=2048,
    max_yaml_aliases=1,
)


@dataclass(frozen=True)
class WebAuthnRuntime:
    """Exact RP ID/origin policy; presence of this object enables WebAuthn."""

    rp_id: str
    rp_name: str
    allowed_origins: tuple[str, ...]

    def __post_init__(self) -> None:
        rp_id = self.rp_id.strip().lower().rstrip(".")
        rp_name = self.rp_name.strip()
        if not _RP_ID.fullmatch(rp_id):
            raise WebAuthnConfigurationError("WebAuthn RP ID must be a valid lowercase DNS name.")
        if not 1 <= len(rp_name) <= 128 or any(ord(char) < 32 for char in rp_name):
            raise WebAuthnConfigurationError("WebAuthn RP name must contain 1-128 printable characters.")
        if not 1 <= len(self.allowed_origins) <= 8:
            raise WebAuthnConfigurationError("WebAuthn requires between one and eight exact allowed origins.")
        normalized: list[str] = []
        for raw_origin in self.allowed_origins:
            origin = raw_origin.strip()
            parsed = urlsplit(origin)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
                raise WebAuthnConfigurationError("Each WebAuthn origin must be an absolute HTTP(S) origin.")
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise WebAuthnConfigurationError("WebAuthn origins cannot contain paths, queries, or fragments.")
            host = parsed.hostname.lower().rstrip(".")
            localhost = host == "localhost"
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
            if parsed.scheme != "https" and not (localhost or loopback):
                raise WebAuthnConfigurationError("Non-loopback WebAuthn origins must use HTTPS.")
            if host != rp_id and not host.endswith(f".{rp_id}"):
                raise WebAuthnConfigurationError("Every WebAuthn origin host must equal or be below the RP ID.")
            try:
                parsed_port = parsed.port
            except ValueError as exc:
                raise WebAuthnConfigurationError("WebAuthn origin port is invalid.") from exc
            port = f":{parsed_port}" if parsed_port is not None else ""
            normalized.append(f"{parsed.scheme}://{host}{port}")
        if len(set(normalized)) != len(normalized):
            raise WebAuthnConfigurationError("WebAuthn origins must be unique after normalization.")
        object.__setattr__(self, "rp_id", rp_id)
        object.__setattr__(self, "rp_name", rp_name)
        object.__setattr__(self, "allowed_origins", tuple(normalized))


def load_webauthn_runtime(path: Path) -> WebAuthnRuntime:
    """Load a small closed JSON RP policy containing no private key material."""

    try:
        if path.stat().st_size > 64 * 1024:
            raise WebAuthnConfigurationError("WebAuthn configuration exceeds 64 KiB.")
        payload = read_json_document(path, policy=_CONFIG_POLICY)
    except (OSError, UnicodeError, StructuredDocumentError) as exc:
        raise WebAuthnConfigurationError("WebAuthn configuration could not be read as UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "rp_id", "rp_name", "allowed_origins"}:
        raise WebAuthnConfigurationError("WebAuthn configuration must use the closed v1 object shape.")
    if payload["schema_version"] != 1 or not isinstance(payload["allowed_origins"], list):
        raise WebAuthnConfigurationError("WebAuthn configuration schema version or origins are invalid.")
    if not all(isinstance(value, str) for value in (payload["rp_id"], payload["rp_name"], *payload["allowed_origins"])):
        raise WebAuthnConfigurationError("WebAuthn configuration values must be strings.")
    return WebAuthnRuntime(
        rp_id=payload["rp_id"],
        rp_name=payload["rp_name"],
        allowed_origins=tuple(payload["allowed_origins"]),
    )
