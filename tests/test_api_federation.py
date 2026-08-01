from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import auth as auth_routes
from reconforge.auth.federation import (
    FederatedPrincipal,
    FederationProvider,
    InMemoryFederationReplayStore,
    VerifiedFederationAssertion,
)
from reconforge.infrastructure.oidc import OIDCStaticJWKSVerifier
from reconforge.infrastructure.postgres_federation import FederationLoginChallenge
from reconforge.infrastructure.postgres_identity import PostgresSession
from reconforge.infrastructure.saml import RSA_SHA256, SAMLProviderMaterial, SAMLResponseVerifier

CHALLENGE_ID = "server-issued-challenge-id-0123456789abcdef"


class _Verifier:
    def verify(self, provider: FederationProvider, request: Any) -> VerifiedFederationAssertion:
        now = datetime.now(UTC)
        return VerifiedFederationAssertion(
            protocol=provider.protocol,
            issuer=provider.issuer,
            subject="external-sensitive-subject",
            audiences=provider.audiences,
            assertion_id="assertion-1",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            nonce=request.expected_nonce,
            groups=("finance-reviewers",),
            signature_verified=True,
            algorithm="RS256",
        )


class _Repository:
    def __init__(self, *, linked: bool = True) -> None:
        self.linked = linked

    def complete_login(self, *, tenant_id: str, principal: Any) -> PostgresSession:
        assert tenant_id == "tenant-a"
        assert principal.roles == ("reviewer",)
        if not self.linked:
            from reconforge.infrastructure.postgres_federation import PostgresFederationError

            raise PostgresFederationError("not linked")
        return PostgresSession(
            id="ses-federated",
            user_id="user-a",
            token="federated-session-token",
            expires_at="2026-07-29T00:00:00Z",
        )

    def consume_challenge(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        protocol: str,
        challenge_id: str,
        correlation: str,
    ) -> bool:
        assert tenant_id == "tenant-a"
        assert provider_id in {"corp-oidc", "corp-saml"}
        assert protocol in {"oidc", "saml"}
        return challenge_id == CHALLENGE_ID and bool(correlation)

    def issue_challenge(self, *, tenant_id: str, provider_id: str, protocol: str) -> FederationLoginChallenge:
        assert tenant_id == "tenant-a"
        correlation = "nonce-value-1234567890" if protocol == "oidc" else "_http-request"
        return FederationLoginChallenge(CHALLENGE_ID, correlation, protocol, "2026-07-29T00:00:00+00:00")


class _Audit:
    def __init__(self, provider_id: str = "corp-oidc") -> None:
        self.provider_id = provider_id
        self.events: list[tuple[str, str | None]] = []

    def record(self, *, action: str, provider_id: str, outcome: str, reason_code: str | None) -> None:
        assert action == "federation_authenticate"
        assert provider_id == self.provider_id
        self.events.append((outcome, reason_code))


def _app(tmp_path: Path) -> Any:
    provider = FederationProvider(
        id="corp-oidc",
        protocol="oidc",
        issuer="https://id.example/oidc",
        audiences=("reconforge",),
        allowed_algorithms=("RS256",),
        group_role_mapping={"finance-reviewers": "reviewer"},
        allowed_roles=frozenset({"reviewer"}),
        network_required=False,
    )
    return create_api_app(
        tmp_path / "local.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn="postgresql://federation.test/reconforge",
        postgres_require_tls=False,
        federation_providers={provider.id: provider},
        federation_verifiers={"oidc": _Verifier()},
    )


def _oidc_material() -> tuple[Any, dict[str, object]]:
    from joserfc.jwk import RSAKey

    private = RSAKey.generate_key(2048, parameters={"kid": "http-rsa-1", "use": "sig", "alg": "RS256"})
    return private, {"keys": [private.as_dict(private=False)]}


def _oidc_token(
    private: Any,
    *,
    subject: str = "external-sensitive-subject",
    nonce: str = "nonce-0123456789abcdef",
) -> str:
    from joserfc import jwt

    now = datetime.now(UTC).replace(microsecond=0)
    claims = {
        "iss": "https://id.example/oidc",
        "sub": subject,
        "aud": "reconforge-team",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": nonce,
        "groups": ["finance-reviewers"],
    }
    return jwt.encode({"alg": "RS256", "kid": "http-rsa-1"}, claims, private, algorithms=["RS256"])


def _oidc_provider(*, network_required: bool = False) -> FederationProvider:
    return FederationProvider(
        id="corp-oidc",
        protocol="oidc",
        issuer="https://id.example/oidc",
        audiences=("reconforge-team",),
        allowed_algorithms=("RS256",),
        group_role_mapping={"finance-reviewers": "reviewer"},
        allowed_roles=frozenset({"reviewer"}),
        network_required=network_required,
    )


def _saml_material() -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.now(UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic HTTP IdP")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return private_pem, certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _signed_saml(private_pem: str, certificate_pem: str, *, request_id: str = "_http-request") -> str:
    from onelogin.saml2.utils import OneLogin_Saml2_Utils

    now = datetime.now(UTC).replace(microsecond=0)
    issued = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    not_before = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    expires = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
 xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_http-response" Version="2.0"
 IssueInstant="{issued}" Destination="https://reconforge.example/saml/acs" InResponseTo="{request_id}">
 <saml:Issuer>https://id.example/saml</saml:Issuer>
 <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
 <saml:Assertion ID="_http-assertion" Version="2.0" IssueInstant="{issued}">
  <saml:Issuer>https://id.example/saml</saml:Issuer>
  <saml:Subject><saml:NameID>external-sensitive-subject</saml:NameID><saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData InResponseTo="{request_id}" Recipient="https://reconforge.example/saml/acs" NotOnOrAfter="{expires}"/></saml:SubjectConfirmation></saml:Subject>
  <saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{expires}"><saml:AudienceRestriction><saml:Audience>https://reconforge.example/saml/metadata</saml:Audience></saml:AudienceRestriction></saml:Conditions>
  <saml:AuthnStatement AuthnInstant="{issued}"><saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>
  <saml:AttributeStatement><saml:Attribute Name="groups"><saml:AttributeValue>finance-reviewers</saml:AttributeValue></saml:Attribute></saml:AttributeStatement>
 </saml:Assertion>
</samlp:Response>"""
    return base64.b64encode(OneLogin_Saml2_Utils.add_sign(xml, private_pem, certificate_pem)).decode("ascii")
def test_federated_login_uses_prelinked_session_and_records_allowed(monkeypatch: Any, tmp_path: Path) -> None:
    audit = _Audit()

    def execute(request: Any, operation: Any) -> Any:
        assert request.headers["x-reconforge-tenant"] == "tenant-a"
        return operation(InMemoryFederationReplayStore(), _Repository(), audit, "tenant-a")

    monkeypatch.setattr(auth_routes, "execute_postgres_federation", execute)
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/v1/auth/federated-login",
        headers={"x-reconforge-tenant": "tenant-a"},
        json={
            "provider_id": "corp-oidc",
            "encoded_assertion": "signed-token-placeholder",
            "challenge_id": CHALLENGE_ID,
            "expected_nonce": "nonce-value-1234567890",
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "federated-session-token"
    assert audit.events == [("allowed", None)]


def test_federated_login_link_failure_is_uniform_denial_and_committed_audit(
    monkeypatch: Any, tmp_path: Path
) -> None:
    audit = _Audit()

    def execute(request: Any, operation: Any) -> Any:
        return operation(InMemoryFederationReplayStore(), _Repository(linked=False), audit, "tenant-a")

    monkeypatch.setattr(auth_routes, "execute_postgres_federation", execute)
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/v1/auth/federated-login",
        headers={"x-reconforge-tenant": "tenant-a"},
        json={
            "provider_id": "corp-oidc",
            "encoded_assertion": "signed-token-placeholder",
            "challenge_id": CHALLENGE_ID,
            "expected_nonce": "nonce-value-1234567890",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "federated_authentication_failed"
    assert "subject" not in response.text
    assert audit.events == [("denied", "identity_link_invalid")]


def test_federated_login_is_closed_when_not_operator_configured(tmp_path: Path) -> None:
    app = create_api_app(tmp_path / "local.db")
    response = TestClient(app).post(
        "/api/v1/auth/federated-login",
        json={
            "provider_id": "corp-oidc",
            "encoded_assertion": "token",
            "challenge_id": CHALLENGE_ID,
            "expected_nonce": "nonce-value-1234567890",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "federation_not_configured"


def test_federated_login_rejects_unknown_fields_and_unsafe_provider_before_verification(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/v1/auth/federated-login",
        headers={"x-reconforge-tenant": "tenant-a"},
        json={"provider_id": "../provider", "encoded_assertion": "token", "unexpected": True},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_real_signed_oidc_traverses_http_and_replay_is_denied(monkeypatch: Any, tmp_path: Path) -> None:
    private, jwks = _oidc_material()
    provider = _oidc_provider()
    replay = InMemoryFederationReplayStore()
    audit = _Audit()

    def execute(request: Any, operation: Any) -> Any:
        return operation(replay, _Repository(), audit, "tenant-a")

    monkeypatch.setattr(auth_routes, "execute_postgres_federation", execute)
    application = create_api_app(
        tmp_path / "local.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn="postgresql://federation.test/reconforge",
        postgres_require_tls=False,
        federation_providers={provider.id: provider},
        federation_verifiers={"oidc": OIDCStaticJWKSVerifier({provider.id: jwks})},
    )
    client = TestClient(application)
    payload = {
        "provider_id": provider.id,
        "encoded_assertion": _oidc_token(private),
        "challenge_id": CHALLENGE_ID,
        "expected_nonce": "nonce-0123456789abcdef",
    }

    allowed = client.post(
        "/api/v1/auth/federated-login", headers={"x-reconforge-tenant": "tenant-a"}, json=payload
    )
    replayed = client.post(
        "/api/v1/auth/federated-login", headers={"x-reconforge-tenant": "tenant-a"}, json=payload
    )

    assert allowed.status_code == 200
    assert replayed.status_code == 401
    assert replayed.json()["error"]["code"] == "federated_authentication_failed"
    assert audit.events == [("allowed", None), ("denied", "assertion_replayed")]


def test_real_signed_saml_traverses_http(monkeypatch: Any, tmp_path: Path) -> None:
    private_pem, certificate_pem = _saml_material()
    provider = FederationProvider(
        id="corp-saml",
        protocol="saml",
        issuer="https://id.example/saml",
        audiences=("https://reconforge.example/saml/metadata",),
        allowed_algorithms=(RSA_SHA256,),
        group_role_mapping={"finance-reviewers": "reviewer"},
        allowed_roles=frozenset({"reviewer"}),
        network_required=False,
    )
    material = SAMLProviderMaterial(
        sp_entity_id="https://reconforge.example/saml/metadata",
        acs_url="https://reconforge.example/saml/acs",
        idp_sso_url="https://id.example/saml/sso",
        idp_certificate_pem=certificate_pem,
    )
    audit = _Audit("corp-saml")

    def execute(request: Any, operation: Any) -> Any:
        return operation(InMemoryFederationReplayStore(), _Repository(), audit, "tenant-a")

    monkeypatch.setattr(auth_routes, "execute_postgres_federation", execute)
    application = create_api_app(
        tmp_path / "local.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn="postgresql://federation.test/reconforge",
        postgres_require_tls=False,
        federation_providers={provider.id: provider},
        federation_verifiers={"saml": SAMLResponseVerifier({provider.id: material})},
    )
    client = TestClient(application)
    challenge_response = client.post(
        "/api/v1/auth/federation/challenge",
        headers={"x-reconforge-tenant": "tenant-a"},
        json={"provider_id": provider.id},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    response = client.post(
        "/api/v1/auth/federated-login",
        headers={"x-reconforge-tenant": "tenant-a"},
        json={
            "provider_id": provider.id,
            "encoded_assertion": _signed_saml(private_pem, certificate_pem, request_id=challenge["request_id"]),
            "challenge_id": challenge["challenge_id"],
            "request_id": challenge["request_id"],
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "federated-session-token"
    assert audit.events == [("allowed", None)]


def test_air_gap_mode_denies_network_required_provider_before_verifier(monkeypatch: Any, tmp_path: Path) -> None:
    private, jwks = _oidc_material()
    provider = _oidc_provider(network_required=True)
    audit = _Audit()

    def execute(request: Any, operation: Any) -> Any:
        return operation(InMemoryFederationReplayStore(), _Repository(), audit, "tenant-a")

    monkeypatch.setattr(auth_routes, "execute_postgres_federation", execute)
    application = create_api_app(
        tmp_path / "local.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn="postgresql://federation.test/reconforge",
        postgres_require_tls=False,
        federation_providers={provider.id: provider},
        federation_verifiers={"oidc": OIDCStaticJWKSVerifier({provider.id: jwks})},
        federation_air_gap_mode=True,
    )
    response = TestClient(application).post(
        "/api/v1/auth/federated-login",
        headers={"x-reconforge-tenant": "tenant-a"},
        json={
            "provider_id": provider.id,
            "encoded_assertion": _oidc_token(private),
            "challenge_id": CHALLENGE_ID,
            "expected_nonce": "nonce-0123456789abcdef",
        },
    )

    assert response.status_code == 401
    assert audit.events == [("denied", "federation_disabled_in_air_gap")]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_http_oidc_session_logout_replay_and_tenant_isolation(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_federation import (
        POSTGRES_FEDERATION_SCHEMA_SQL,
        PostgresFederationRepository,
    )
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL, PostgresIdentityRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    tenant_a = "federation_http_a"
    tenant_b = "federation_http_b"
    provider = _oidc_provider()
    private, jwks = _oidc_material()
    principal = FederatedPrincipal(
        provider_id=provider.id,
        issuer=provider.issuer,
        subject="external-sensitive-subject",
        roles=("reviewer",),
        assertion_id="setup-only",
    )
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_FEDERATION_SCHEMA_SQL)
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                    f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                    f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                    f"reconforge.identity_sessions, reconforge.federation_login_challenges, "
                    f"reconforge.federation_assertion_replays, "
                    f"reconforge.federation_identity_links, reconforge.federation_identity_events TO {app_user}"
                )
        for tenant_id in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                connection.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant_id, tenant_id))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="reviewer")
            identity.create_user(
                tenant_id=tenant_a,
                user_id="user-a",
                username="federated.http",
                password="Synthetic-local-fallback-123",
                role_name="reviewer",
            )
            PostgresFederationRepository(connection).link_identity(
                tenant_id=tenant_a,
                principal=principal,
                user_id="user-a",
                actor_id="security-admin",
            )
        application = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tmp_path / "tenants",
            postgres_dsn=dsn,
            postgres_require_tls=False,
            federation_providers={provider.id: provider},
            federation_verifiers={"oidc": OIDCStaticJWKSVerifier({provider.id: jwks})},
        )
        client = TestClient(application)
        challenge_response = client.post(
            "/api/v1/auth/federation/challenge",
            headers={"x-reconforge-tenant": tenant_a},
            json={"provider_id": provider.id},
        )
        assert challenge_response.status_code == 200
        challenge = challenge_response.json()
        payload = {
            "provider_id": provider.id,
            "encoded_assertion": _oidc_token(private, nonce=challenge["nonce"]),
            "challenge_id": challenge["challenge_id"],
            "expected_nonce": challenge["nonce"],
        }
        login = client.post(
            "/api/v1/auth/federated-login", headers={"x-reconforge-tenant": tenant_a}, json=payload
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"x-reconforge-tenant": tenant_a, "authorization": f"Bearer {token}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200 and logout.json()["revoked"] is True
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        replayed = client.post(
            "/api/v1/auth/federated-login", headers={"x-reconforge-tenant": tenant_a}, json=payload
        )
        cross_tenant = client.post(
            "/api/v1/auth/federated-login", headers={"x-reconforge-tenant": tenant_b}, json=payload
        )
        assert replayed.status_code == 401
        assert cross_tenant.status_code == 401
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            counts = connection.execute(
                "SELECT count(*), count(*) FILTER (WHERE outcome='DENIED') "
                "FROM reconforge.federation_identity_events"
            ).fetchone()
            assert counts[0] >= 3 and counts[1] >= 1
            assert connection.execute(
                "SELECT count(*) FROM reconforge.federation_identity_links WHERE external_subject_hash=%s",
                ("external-sensitive-subject",),
            ).fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "DELETE FROM reconforge.federation_identity_links WHERE tenant_id IN (%s, %s)",
                    (tenant_a, tenant_b),
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
        finally:
            admin.close()
