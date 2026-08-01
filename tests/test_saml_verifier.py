from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from reconforge.auth.federation import FederationProvider, FederationRequest
from reconforge.infrastructure.saml import RSA_SHA256, SAMLProviderMaterial, SAMLResponseVerifier, SAMLVerificationError

ISSUER = "https://id.example/saml"
SP_ENTITY_ID = "https://reconforge.example/saml/metadata"
ACS_URL = "https://reconforge.example/saml/acs"
REQUEST_ID = "_request-123"
def _certificate() -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.now(UTC).replace(microsecond=0)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic ReconForge Test IdP")])
    cert = (
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
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return private_pem, cert_pem


def _time(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _response_xml(*, issuer: str = ISSUER, audience: str = SP_ENTITY_ID, request_id: str = REQUEST_ID) -> str:
    now = datetime.now(UTC).replace(microsecond=0)
    return f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
 xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_response-123" Version="2.0"
 IssueInstant="{_time(now)}" Destination="{ACS_URL}" InResponseTo="{request_id}">
 <saml:Issuer>{issuer}</saml:Issuer>
 <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
 <saml:Assertion ID="_assertion-123" Version="2.0" IssueInstant="{_time(now)}">
  <saml:Issuer>{issuer}</saml:Issuer>
  <saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">user-123</saml:NameID>
   <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
    <saml:SubjectConfirmationData InResponseTo="{request_id}" Recipient="{ACS_URL}"
      NotOnOrAfter="{_time(now + timedelta(minutes=5))}"/>
   </saml:SubjectConfirmation>
  </saml:Subject>
  <saml:Conditions NotBefore="{_time(now - timedelta(minutes=1))}" NotOnOrAfter="{_time(now + timedelta(minutes=5))}">
   <saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>
  </saml:Conditions>
  <saml:AuthnStatement AuthnInstant="{_time(now)}" SessionIndex="session-123">
   <saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef></saml:AuthnContext>
  </saml:AuthnStatement>
  <saml:AttributeStatement>
   <saml:Attribute Name="groups"><saml:AttributeValue xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="xs:string" xmlns:xs="http://www.w3.org/2001/XMLSchema">finance-reviewers</saml:AttributeValue></saml:Attribute>
   <saml:Attribute Name="displayName"><saml:AttributeValue>Finance Reviewer</saml:AttributeValue></saml:Attribute>
   <saml:Attribute Name="email"><saml:AttributeValue>reviewer@example.test</saml:AttributeValue></saml:Attribute>
  </saml:AttributeStatement>
 </saml:Assertion>
</samlp:Response>"""


def _signed_response(private_pem: str, cert_pem: str, **changes: str) -> str:
    from onelogin.saml2.utils import OneLogin_Saml2_Utils

    signed = OneLogin_Saml2_Utils.add_sign(_response_xml(**changes), private_pem, cert_pem)
    return base64.b64encode(signed).decode("ascii")


def _provider() -> FederationProvider:
    return FederationProvider(
        id="corp-saml",
        protocol="saml",
        issuer=ISSUER,
        audiences=(SP_ENTITY_ID,),
        allowed_algorithms=(RSA_SHA256,),
        group_role_mapping={"finance-reviewers": "reviewer"},
        allowed_roles=frozenset({"reviewer"}),
    )


def _verifier(cert_pem: str) -> SAMLResponseVerifier:
    return SAMLResponseVerifier(
        {
            "corp-saml": SAMLProviderMaterial(
                sp_entity_id=SP_ENTITY_ID,
                acs_url=ACS_URL,
                idp_sso_url="https://id.example/saml/sso",
                idp_certificate_pem=cert_pem,
            )
        }
    )


def _request(encoded: str, *, request_id: str = REQUEST_ID) -> FederationRequest:
    return FederationRequest(provider_id="corp-saml", encoded_assertion=encoded, request_id=request_id)


def test_real_signed_saml_response_is_verified_and_normalized() -> None:
    private_pem, cert_pem = _certificate()
    assertion = _verifier(cert_pem).verify(_provider(), _request(_signed_response(private_pem, cert_pem)))

    assert assertion.signature_verified is True
    assert assertion.algorithm == RSA_SHA256
    assert assertion.subject == "user-123"
    assert assertion.audiences == (SP_ENTITY_ID,)
    assert assertion.groups == ("finance-reviewers",)
    assert assertion.in_response_to == REQUEST_ID


@pytest.mark.parametrize(
    ("change", "value"),
    [("issuer", "https://evil.example"), ("audience", "https://other.example"), ("request_id", "_other")],
)
def test_signed_but_wrong_saml_scope_is_rejected(change: str, value: str) -> None:
    private_pem, cert_pem = _certificate()
    with pytest.raises(SAMLVerificationError, match="^SAML verification failed\\.$"):
        _verifier(cert_pem).verify(
            _provider(),
            _request(_signed_response(private_pem, cert_pem, **{change: value})),
        )


def test_tamper_wrong_certificate_and_request_replay_correlation_fail_closed() -> None:
    private_pem, cert_pem = _certificate()
    encoded = _signed_response(private_pem, cert_pem)
    raw = base64.b64decode(encoded).replace(b"finance-reviewers", b"finance-attackers")
    with pytest.raises(SAMLVerificationError):
        _verifier(cert_pem).verify(_provider(), _request(base64.b64encode(raw).decode("ascii")))

    _, other_cert = _certificate()
    with pytest.raises(SAMLVerificationError):
        _verifier(other_cert).verify(_provider(), _request(encoded))
    with pytest.raises(SAMLVerificationError):
        _verifier(cert_pem).verify(_provider(), _request(encoded, request_id="_unexpected"))


def test_material_rejects_non_https_or_credentialed_endpoints() -> None:
    _, cert_pem = _certificate()
    base = {
        "sp_entity_id": SP_ENTITY_ID,
        "acs_url": ACS_URL,
        "idp_sso_url": "https://id.example/saml/sso",
        "idp_certificate_pem": cert_pem,
    }
    with pytest.raises(ValueError, match="HTTPS"):
        SAMLProviderMaterial.model_validate(base | {"acs_url": "http://reconforge.example/acs"})
    with pytest.raises(ValueError, match="HTTPS"):
        SAMLProviderMaterial.model_validate(base | {"idp_sso_url": "https://user:pass@id.example/sso"})
