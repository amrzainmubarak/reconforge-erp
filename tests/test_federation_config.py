from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from reconforge.auth.federation_config import FederationConfigurationError, load_federation_runtime
from reconforge.cli import app


def _public_jwks() -> dict[str, object]:
    from joserfc.jwk import RSAKey

    key = RSAKey.generate_key(2048, parameters={"kid": "operator-key-1", "use": "sig", "alg": "RS256"})
    return {"keys": [key.as_dict(private=False)]}


def _certificate() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.now(UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Configuration IdP")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "air_gap_mode": False,
        "providers": [
            {
                "id": "corp-oidc",
                "protocol": "oidc",
                "issuer": "https://id.example/oidc",
                "audiences": ["reconforge-team"],
                "allowed_algorithms": ["RS256"],
                "group_role_mapping": {"finance-reviewers": "reviewer"},
                "allowed_roles": ["reviewer"],
                "network_required": False,
                "jwks": _public_jwks(),
            },
            {
                "id": "corp-saml",
                "protocol": "saml",
                "issuer": "https://id.example/saml",
                "audiences": ["https://reconforge.example/saml/metadata"],
                "allowed_algorithms": ["http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"],
                "group_role_mapping": {"finance-reviewers": "reviewer"},
                "allowed_roles": ["reviewer"],
                "network_required": False,
                "material": {
                    "sp_entity_id": "https://reconforge.example/saml/metadata",
                    "acs_url": "https://reconforge.example/saml/acs",
                    "idp_sso_url": "https://id.example/saml/sso",
                    "idp_certificate_pem": _certificate(),
                },
            },
        ],
    }


def _write(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_bounded_configuration_builds_both_reviewed_verifiers(tmp_path: Path) -> None:
    runtime = load_federation_runtime(_write(tmp_path / "federation.json", _document()))

    assert tuple(runtime.providers) == ("corp-oidc", "corp-saml")
    assert set(runtime.verifiers) == {"oidc", "saml"}
    assert runtime.air_gap_mode is False


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "private_jwk", "bad_certificate"])
def test_configuration_rejects_unknown_duplicate_or_private_material(tmp_path: Path, mutation: str) -> None:
    document = _document()
    providers = document["providers"]
    assert isinstance(providers, list)
    first = providers[0]
    assert isinstance(first, dict)
    if mutation == "extra":
        document["unexpected"] = True
    elif mutation == "duplicate":
        second = providers[1]
        assert isinstance(second, dict)
        second["id"] = "corp-oidc"
    elif mutation == "private_jwk":
        jwks = first["jwks"]
        assert isinstance(jwks, dict)
        keys = jwks["keys"]
        assert isinstance(keys, list) and isinstance(keys[0], dict)
        keys[0]["d"] = "private-component"
    else:
        second = providers[1]
        assert isinstance(second, dict) and isinstance(second["material"], dict)
        second["material"]["idp_certificate_pem"] = "-----BEGIN PRIVATE KEY-----\nunsafe\n"

    with pytest.raises(FederationConfigurationError, match=r"^Federation configuration is invalid\.$"):
        load_federation_runtime(_write(tmp_path / "federation.json", document))


def test_cli_loads_operator_configuration_without_starting_network(monkeypatch: Any, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def run(application: Any, **kwargs: object) -> None:
        captured["providers"] = application.state.federation_providers
        captured["verifiers"] = application.state.federation_verifiers
        captured["kwargs"] = kwargs

    monkeypatch.setattr("reconforge.cli.uvicorn.run", run)
    result = CliRunner().invoke(
        app,
        [
            "api",
            "serve",
            "--db",
            str(tmp_path / "unused.db"),
            "--tenant-db-root",
            str(tmp_path / "tenants"),
            "--postgres-dsn",
            "postgresql://operator.test/reconforge",
            "--postgres-no-tls",
            "--federation-config",
            str(_write(tmp_path / "federation.json", _document())),
        ],
    )

    assert result.exit_code == 0, result.output
    assert set(captured["providers"]) == {"corp-oidc", "corp-saml"}  # type: ignore[arg-type]
    assert set(captured["verifiers"]) == {"oidc", "saml"}  # type: ignore[arg-type]


def test_cli_refuses_federation_without_postgresql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("RECONFORGE_POSTGRES_DSN", raising=False)
    result = CliRunner().invoke(
        app,
        [
            "api",
            "serve",
            "--tenant-db-root",
            str(tmp_path / "tenants"),
            "--federation-config",
            str(_write(tmp_path / "federation.json", _document())),
        ],
    )

    assert result.exit_code == 1
    assert "requires the PostgreSQL server-auth profile" in result.output
